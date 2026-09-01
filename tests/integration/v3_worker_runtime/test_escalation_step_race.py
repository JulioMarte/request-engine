"""PostgreSQL proof (race): concurrent escalations serialize to one child.

docs/v3/40 T4: two independent transactions trigger the same escalation
simultaneously. Deterministic synchronization holds the first at its ledger
append while it owns the parent task lock; the second blocks on the parent
lock. Exactly one child task, one ledger row and one initial dispatch intent
exist; the loser is a no-op that observes the lineage already advanced.
"""

import asyncio

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]


async def wait_until_query_blocked(
    observer: world.PgConnection, query_pattern: str, failure: str
) -> None:
    """Deterministic race synchronization: poll pg_stat_activity for a lock waiter."""

    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        row = observer.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND wait_event_type = 'Lock'
              AND query ILIKE %s
            """,
            (query_pattern,),
        ).fetchone()
        assert row is not None
        if int(row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(failure)


@pytest.mark.asyncio
async def test_concurrent_escalations_create_exactly_one_child(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "race-c")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    sms = world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="failed",
    )
    world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")

    blocker = world.connect()
    try:
        actions.lock_escalation_barrier(blocker)
        first = asyncio.create_task(actions.run_escalation(app_session_factory, org, task))
        await wait_until_query_blocked(
            admin_conn,
            "%FROM request_engine.communication_escalations%",
            "first escalation never parked at the ledger read point",
        )
        second = asyncio.create_task(actions.run_escalation(app_session_factory, org, task))
        await wait_until_query_blocked(
            admin_conn,
            "%communication_tasks%FOR UPDATE%",
            "second escalation never blocked on the parent task lock",
        )
        blocker.rollback()
        first_outcome = await asyncio.wait_for(first, timeout=10)
        second_outcome = await asyncio.wait_for(second, timeout=10)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()

    assert first_outcome.state == "escalated"
    assert second_outcome.state == "no_op"
    assert second_outcome.child_task_id is None

    children = actions.child_tasks(admin_conn, org, task)
    assert len(children) == 1
    assert children[0]["contact_point_id"] == sms
    assert children[0]["escalation_ordinal"] == 1
    assert len(actions.ledger_rows(admin_conn, org, task)) == 1
    assert len(actions.outbox_payloads(admin_conn, org, "communication.task_escalated.v1")) == 1
    assert (
        world.scalar(
            admin_conn,
            """
            SELECT count(*) FROM request_engine.scheduled_actions
            WHERE owner_module = 'communications' AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask' AND subject_id = %s
            """,
            children[0]["id"],
        )
        == 1
    )
