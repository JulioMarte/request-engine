"""PostgreSQL proof (race): the fatigue guard serializes across lineages.

docs/v3/40 T4 + review FIX-3: the contact fatigue guard is count-then-act
keyed on the recipient subject. Two concurrent escalations for the same
subject on DIFFERENT lineages queue on the transaction-scoped subject
advisory lock; with the daily limit set so only one further contact is
admissible, exactly one child is created and the other trigger closes its own
lineage ``fatigue_limited`` — never two extra contacts.
"""

import asyncio

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]

BLOCKED_QUERY = """
SELECT count(*) FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
  AND wait_event_type = 'Lock' AND query ILIKE %s
"""


async def wait_until_blocked(observer: world.PgConnection, expected: int, failure: str) -> None:
    """Deterministic synchronization: both escalations queued on the subject lock."""

    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        row = observer.execute(BLOCKED_QUERY, ("%pg_advisory_xact_lock%",)).fetchone()
        assert row is not None
        if int(row[0]) >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(failure)


@pytest.mark.asyncio
async def test_concurrent_subject_escalations_admit_exactly_one_extra_contact(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "fatigue-race")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    world.new_contact_point(admin_conn, org, party, "phone")
    policy = dict(world.POLICY, max_contacts_per_subject_per_day=3)
    first = world.new_task(
        admin_conn, org, party, policy=policy, contact_point_id=whatsapp, status="failed"
    )
    second = world.new_task(
        admin_conn, org, party, policy=policy, contact_point_id=whatsapp, status="failed"
    )
    world.new_attempting_delivery(admin_conn, org, first, channel="whatsapp")
    world.new_attempting_delivery(admin_conn, org, second, channel="whatsapp")

    blocker = world.connect()
    try:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s::text || ':' || %s::text, 0))",
            (str(org), str(party)),
        )
        winner = asyncio.create_task(actions.run_escalation(app_session_factory, org, first))
        await wait_until_blocked(admin_conn, 1, "winner never queued on the subject lock")
        loser = asyncio.create_task(actions.run_escalation(app_session_factory, org, second))
        await wait_until_blocked(admin_conn, 2, "loser never queued on the subject lock")
        blocker.rollback()
        first_outcome = await asyncio.wait_for(winner, timeout=10)
        second_outcome = await asyncio.wait_for(loser, timeout=10)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()

    outcomes = {first_outcome.state, second_outcome.state}
    assert outcomes == {"escalated", "terminal"}
    terminal = first_outcome if first_outcome.state == "terminal" else second_outcome
    escalated = second_outcome if first_outcome.state == "terminal" else first_outcome
    assert escalated.state == "escalated"
    assert terminal.reason == "fatigue_limited"
    children = [
        child
        for parent in (first, second)
        for child in actions.child_tasks(admin_conn, org, parent)
    ]
    assert len(children) == 1
    assert (
        world.scalar(
            admin_conn,
            """
            SELECT count(*) FROM request_engine.communication_tasks
            WHERE organization_id = %s AND recipient_party_id = %s
            """,
            org,
            party,
        )
        == 3
    )
    assert (
        len(actions.ledger_rows(admin_conn, org, first))
        + len(actions.ledger_rows(admin_conn, org, second))
        == 1
    )
    terminals = actions.outbox_payloads(admin_conn, org, "communication.lineage_unreachable.v1")
    assert len(terminals) == 1
    assert terminals[0]["reason"] == "fatigue_limited"
