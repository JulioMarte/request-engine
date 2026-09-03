from datetime import UTC, datetime
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import (
    ALL_PUBLIC_CAPABILITIES,
    auth,
    client_with_actors,
    first_slot,
    seed_tenant_sandbox,
)

_FRONT_DESK_CAPABILITIES = frozenset(
    {
        "appointments.day_board",
        "queue.check_in",
        "queue.staff_read",
        "queue.recall_hold",
        "queue.release_recall_hold",
    }
)


async def _book_and_check_in(client, sandbox):
    slot = await first_slot(client, sandbox)
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    reservation = booked.json()
    checked_in = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id), "reservation_id": reservation["id"]},
        headers=auth(sandbox, idempotency_key=f"check-in-{uuid4().hex}"),
    )
    assert checked_in.status_code == 201, checked_in.text
    return reservation, checked_in.json()


def _day_params(sandbox):
    return {
        "window_start": datetime(2030, 1, 7, 0, 0, tzinfo=UTC).isoformat(),
        "window_end": datetime(2030, 1, 8, 0, 0, tzinfo=UTC).isoformat(),
        "location_id": str(sandbox.location_id),
    }


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_human_front_desk_hold_refresh_release_journey(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "front-desk-human")
    actor = ActorContext(
        sandbox.organization_id,
        sandbox.principal_id,
        ALL_PUBLIC_CAPABILITIES | _FRONT_DESK_CAPABILITIES,
    )
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        reservation, entry = await _book_and_check_in(client, sandbox)
        before = await client.get("/v1/appointments/day-board", params=_day_params(sandbox), headers=auth(sandbox))
        assert before.status_code == 200 and before.json()[0]["recall_eligible"] is True
        key = f"hold-{uuid4().hex}"
        body = {
            "condition_kind": "until_event",
            "event_key": "external_step_completed",
            "reason": "waiting for external prerequisite",
            "expected_revision": entry["revision"],
        }
        held = await client.post(f"/v1/queue-entries/{entry['id']}/recall-hold", json=body, headers=auth(sandbox, idempotency_key=key))
        replay = await client.post(f"/v1/queue-entries/{entry['id']}/recall-hold", json=body, headers=auth(sandbox, idempotency_key=key))
        assert held.status_code == replay.status_code == 200 and replay.json() == held.json()
        staff = await client.get(f"/v1/queues/{sandbox.queue_id}/staff", headers=auth(sandbox))
        board = await client.get("/v1/appointments/day-board", params=_day_params(sandbox), headers=auth(sandbox))
        assert staff.json()[0]["recall_eligible"] is False
        assert board.json()[0]["reservation_id"] == reservation["id"]
        assert board.json()[0]["recall_hold_id"] == held.json()["hold"]["id"]
        released = await client.post(
            f"/v1/queue-entries/{entry['id']}/recall-hold/release",
            json={"hold_id": held.json()["hold"]["id"], "expected_revision": held.json()["revision"]},
            headers=auth(sandbox, idempotency_key=f"release-{uuid4().hex}"),
        )
        assert released.status_code == 200
        refreshed = await client.get("/v1/appointments/day-board", params=_day_params(sandbox), headers=auth(sandbox))
        assert refreshed.json()[0]["recall_eligible"] is True
        assert refreshed.json()[0]["recall_hold_id"] is None


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_bot_retry_stale_ui_and_capability_rejection_are_fail_closed(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "front-desk-bot")
    staff = ActorContext(sandbox.organization_id, sandbox.principal_id, ALL_PUBLIC_CAPABILITIES | _FRONT_DESK_CAPABILITIES)
    read_only_token = f"read-only-{uuid4().hex}"
    read_only = ActorContext(sandbox.organization_id, sandbox.principal_id, frozenset({"appointments.day_board", "queue.staff_read"}))
    async with client_with_actors(e2e_session_factory, {sandbox.token: staff, read_only_token: read_only}) as client:
        _, entry = await _book_and_check_in(client, sandbox)
        key = f"bot-hold-{uuid4().hex}"
        held = await client.post(
            f"/v1/queue-entries/{entry['id']}/recall-hold",
            json={"condition_kind": "until_customer_initiates", "expected_revision": entry["revision"], "reason": "bot could not reach customer"},
            headers=auth(sandbox, idempotency_key=key),
        )
        assert held.status_code == 200
        stale = await client.post(
            f"/v1/queue-entries/{entry['id']}/recall-hold/release",
            json={"hold_id": held.json()["hold"]["id"], "expected_revision": entry["revision"]},
            headers=auth(sandbox, idempotency_key=f"stale-{uuid4().hex}"),
        )
        denied = await client.post(
            f"/v1/queue-entries/{entry['id']}/recall-hold/release",
            json={"hold_id": held.json()["hold"]["id"], "expected_revision": held.json()["revision"]},
            headers={"Authorization": f"Bearer {read_only_token}", "Idempotency-Key": f"denied-{uuid4().hex}"},
        )
        conflict = await client.post(
            f"/v1/queue-entries/{entry['id']}/recall-hold",
            json={"condition_kind": "until_customer_initiates", "expected_revision": held.json()["revision"], "reason": "different retry payload"},
            headers=auth(sandbox, idempotency_key=key),
        )
        assert stale.status_code == 409
        assert denied.status_code == 403
        assert conflict.status_code == 409
        visible = await client.get(f"/v1/queues/{sandbox.queue_id}/staff", headers={"Authorization": f"Bearer {read_only_token}"})
        assert visible.status_code == 200
        assert visible.json()[0]["recall_hold_id"] == held.json()["hold"]["id"]
