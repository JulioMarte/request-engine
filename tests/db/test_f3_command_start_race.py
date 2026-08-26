import asyncio
from uuid import UUID

import pytest
from f3_command_race_support import align_fixture_to_db_clock, idempotency_state
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.errors import LiveServiceRevisionConflict
from request_engine.modules.delivery.application.service_session_commands import StartServiceCommand
from request_engine.modules.delivery.contracts.service_session import ServiceSession
from request_engine.platform.db.session import SessionFactory


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) "
        "VALUES (%s,'human','f3-command-race') RETURNING id",
        (organization_id,),
    ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_start_service_command_race_has_one_effectful_winner(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    revisions = align_fixture_to_db_clock(admin_conn, setup)
    principal_id = _principal(admin_conn, setup.organization_id)
    operations = PostgresLiveServiceOperations(command_session_factory)
    commands = (
        StartServiceCommand(
            organization_id=setup.organization_id,
            principal_id=principal_id,
            queue_entry_id=entry_id,
            resource_id=setup.resource_id,
            location_id=setup.location_id,
            expected_queue_revision=revisions[entry_id],
            idempotency_key=f"start-race-{index}",
            actual_workload_classification_id=setup.actual_workload_id,
        )
        for index, entry_id in enumerate((setup.entry_a_id, setup.entry_b_id), start=1)
    )

    results = await asyncio.gather(
        *(operations.start_service(command) for command in commands),
        return_exceptions=True,
    )
    winners = [result for result in results if isinstance(result, ServiceSession)]
    losers = [result for result in results if isinstance(result, Exception)]
    detail = repr(results)
    assert len(winners) == 1, detail
    assert len(losers) == 1, detail
    assert not isinstance(losers[0], LiveServiceRevisionConflict), detail

    winner = winners[0]
    rows = admin_conn.execute(
        "SELECT queue_entry_id FROM request_engine.service_sessions "
        "WHERE organization_id=%s AND resource_id=%s AND status IN ('active','paused')",
        (setup.organization_id, setup.resource_id),
    ).fetchall()
    assert rows == [(winner.queue_entry_id,)]
    statuses = dict(
        admin_conn.execute(
            "SELECT id,status FROM request_engine.queue_entries WHERE id IN (%s,%s)",
            (setup.entry_a_id, setup.entry_b_id),
        ).fetchall()
    )
    if winner.queue_entry_id == setup.entry_a_id:
        losing_entry = setup.entry_b_id
        winner_key, loser_key = "start-race-1", "start-race-2"
    else:
        losing_entry = setup.entry_a_id
        winner_key, loser_key = "start-race-2", "start-race-1"
    assert statuses[winner.queue_entry_id] == "serving"
    assert statuses[losing_entry] == "called"
    assert idempotency_state(admin_conn, setup.organization_id, principal_id, winner_key) == (
        "completed"
    )
    assert idempotency_state(admin_conn, setup.organization_id, principal_id, loser_key) is None

    audit = admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='service_session.start'",
        (setup.organization_id,),
    ).fetchone()
    outbox = admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND event_type='service_session.started.v1'",
        (setup.organization_id,),
    ).fetchone()
    assert audit == (1,)
    assert outbox == (1,)
