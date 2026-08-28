from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial
from uuid import uuid4

import pytest

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

from . import f5_multi_action_support as multi
from .f3_acceptance_assertions import seed_walk_in_subject
from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_fixture import close_location_after_slots, grant_extend_day_authority
from .f5_extend_day_support import owner_revisions
from .f5_recovery_support import book_commitments, f5_actor
from .f5_scheduled_assessment_support import current_source_revision as source_revision
from .f5_scheduled_assessment_support import incident_revision, lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.concurrency,
]


async def test_f5_multi_action_workflow_reprojects_between_actions_and_converges(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-multi-action-workflow")
    booking = five_minute_sandbox(e2e_admin_conn, sandbox)
    grant_extend_day_authority(e2e_admin_conn, booking)
    seed_today_schedule(e2e_admin_conn, booking)
    supply = contextualize_recovery_supply(e2e_admin_conn, booking)
    actors = {sandbox.token: f5_actor(sandbox)}
    handler = build_recovery_assessment_handler(e2e_session_factory)
    async with client_with_actors(e2e_session_factory, actors) as setup:
        await configure_projection(setup, booking)
        _, slots = await book_commitments(setup, e2e_admin_conn, booking)
        restrict_contextual_capacity(e2e_admin_conn, booking, supply, slots, count=6)
        close_location_after_slots(e2e_admin_conn, booking, slots, count=6)
    revision = source_revision(e2e_admin_conn, booking)
    opened = await handler.handle(lease_reassessment(e2e_admin_conn, booking, revision))
    assert opened.applied is True and opened.incident is not None
    incident_id = opened.incident.id
    assert incident_revision(e2e_admin_conn, booking) == (revision, 1)
    subject = seed_walk_in_subject(e2e_admin_conn, booking)
    entries = multi.queue_entry_count(e2e_admin_conn, booking)
    start_at = datetime.fromisoformat(slots[6]["start_at"])
    end_at = datetime.fromisoformat(slots[9]["end_at"])
    stop = dict(expected_source_revision=revision, expected_intake_revision=1, accepting=False)
    stop_key = f"f5-multi-stop-{uuid4().hex}"

    async with client_with_actors(e2e_session_factory, actors) as client:
        raced = await asyncio.gather(
            multi.post_intake_control(client, booking, incident_id, body=stop, key=stop_key),
            multi.post_intake_control(client, booking, incident_id, body=stop, key=stop_key),
        )
        assert all(r.status_code == 200 and r.json()["status"] == "succeeded" for r in raced)
        assert len({r.json()["id"] for r in raced}) == 1
        blocked = await multi.walk_in(client, booking, subject)
        assert blocked.status_code == 409 and multi.error_code(blocked) == "queue_intake_stopped"
        assert multi.queue_entry_count(e2e_admin_conn, booking) == entries

        stop_reprojected = await handler.handle(
            lease_reassessment(e2e_admin_conn, booking, revision + 1)
        )
        assert stop_reprojected.applied is True
        assert incident_revision(e2e_admin_conn, booking) == (revision + 1, 2)

        multi.seed_future_hours_exception(e2e_admin_conn, booking)
        refreshed = source_revision(e2e_admin_conn, booking)
        reprojected = await handler.handle(lease_reassessment(e2e_admin_conn, booking, refreshed))
        assert refreshed == revision + 2 and reprojected.applied is True
        assert incident_revision(e2e_admin_conn, booking) == (refreshed, 3)
        revs = owner_revisions(e2e_admin_conn, booking)

    ext: multi.ExtendCall = {
        "assignment_id": supply.assignment_id,
        "window": (start_at, end_at),
        "owner_revisions": revs,
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        extend_for = partial(multi.post_extend_day, client, booking, incident_id, **ext)

        location_exceptions = multi.location_exception_count(e2e_admin_conn, booking)
        stale_key = f"f5-multi-extend-stale-{uuid4().hex}"
        stale = await extend_for(source_revision=revision, key=stale_key)
        assert stale.status_code == 409 and multi.error_code(stale) == "STALE_RECOVERY_INCIDENT"
        assert multi.location_exception_count(e2e_admin_conn, booking) == location_exceptions
        assert multi.assignment_exception_count(e2e_admin_conn, booking, supply.assignment_id) == 0

        extend_key = f"f5-multi-extend-{uuid4().hex}"
        applied = await extend_for(source_revision=refreshed, key=extend_key)
        body = applied.json()
        assert applied.status_code == 200 and body["status"] == "succeeded"
        reassessment = body["owner_steps"]["reassessment"]
        assert reassessment["scheduled_shortfall_seconds"] == 0
        assert reassessment["incident_status"] == "resolved"
        assert reassessment["source_revision"] > refreshed
        applied_replay = await extend_for(source_revision=refreshed, key=extend_key)
        assert applied_replay.status_code == 200 and applied_replay.json() == body
        still_blocked = await multi.walk_in(client, booking, subject)
        assert still_blocked.status_code == 409

    facts = multi.incident_facts(e2e_admin_conn, booking)
    assert incident_revision(e2e_admin_conn, booking) is None and len(facts) == 1
    assert facts[0][1:3] == ("resolved", source_revision(e2e_admin_conn, booking))
    assert multi.location_exception_count(e2e_admin_conn, booking) == location_exceptions + 1
    assert multi.assignment_exception_count(e2e_admin_conn, booking, supply.assignment_id) == 1
    assert multi.intake_state(e2e_admin_conn, booking) == (False, 2)

    actions = multi.action_rows(e2e_admin_conn, booking, incident_id)
    stop_row, rejected_row, succeeded_row = actions
    kinds = [(row[0], row[1]) for row in actions]
    assert kinds == [
        ("stop_intake", "succeeded"),
        ("extend_day", "rejected"),
        ("extend_day", "succeeded"),
    ]
    want_intake = {"service_queue_id": str(booking.queue_id), "revision": 2, "accepting": False}
    assert stop_row[2:5] == (sandbox.principal_id, revision, {"queue_intake": want_intake})
    assert stop_row[5] is None and stop_row[6] == stop_key
    assert rejected_row[3:6] == (revision, {}, "STALE_RECOVERY_INCIDENT")
    assert succeeded_row[3] == refreshed
    assert set(succeeded_row[4]) == {"catalog_location", "booking_schedule", "reassessment"}
    assert {row[2] for row in actions} == {sandbox.principal_id}
    assert len({row[6] for row in actions}) == 3
