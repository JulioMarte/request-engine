from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_race_support import create_principal
from f3_live_ops_seed import PgConnection

from request_engine.modules.delivery.adapters.db.live_capacity_source import (
    PostgresDeliveryProjectionSource,
)
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.temporal
@pytest.mark.provenance
async def test_history_reader_excludes_interruption_and_respects_lookback(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    started_at = datetime(2035, 1, 1, 9, 30, tzinfo=UTC)
    paused_at = datetime(2035, 1, 1, 9, 40, tzinfo=UTC)
    resumed_at = datetime(2035, 1, 1, 9, 45, tzinfo=UTC)
    completed_at = datetime(2035, 1, 1, 10, 0, tzinfo=UTC)

    with admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (started_at, setup.entry_a_id),
        )
        row = admin_conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,"
            "actual_workload_classification_id,started_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                setup.organization_id,
                setup.entry_a_id,
                setup.resource_id,
                setup.location_id,
                setup.actual_workload_id,
                started_at,
            ),
        ).fetchone()
        assert row is not None
        session_id = cast(UUID, row[0])
        admin_conn.execute(
            "UPDATE request_engine.service_sessions SET status='paused',revision=revision+1 "
            "WHERE id=%s",
            (session_id,),
        )
        admin_conn.execute(
            "INSERT INTO request_engine.service_session_interruptions "
            "(organization_id,service_session_id,kind,started_at,ended_at,"
            "started_by_principal_id,ended_by_principal_id) "
            "VALUES (%s,%s,'break',%s,%s,%s,%s)",
            (setup.organization_id, session_id, paused_at, resumed_at, principal_id, principal_id),
        )
        admin_conn.execute(
            "UPDATE request_engine.service_sessions SET status='active',revision=revision+1 "
            "WHERE id=%s",
            (session_id,),
        )
        admin_conn.execute(
            "UPDATE request_engine.service_sessions SET status='completed',completed_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (completed_at, session_id),
        )
        admin_conn.execute(
            "UPDATE request_engine.queue_entries SET status='completed',completed_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (completed_at, setup.entry_a_id),
        )

    source = PostgresDeliveryProjectionSource()
    observed_at = datetime(2035, 1, 1, 11, 0, tzinfo=UTC)
    async with tenant_read_snapshot(command_session_factory, setup.organization_id) as snapshot:
        observations = await source.read_completed_history(
            snapshot,
            organization_id=setup.organization_id,
            resource_id=setup.resource_id,
            workload_classification_id=setup.actual_workload_id,
            observed_at=observed_at,
            lookback_days=90,
            limit=64,
            resource_specific=True,
        )
        expired = await source.read_completed_history(
            snapshot,
            organization_id=setup.organization_id,
            resource_id=setup.resource_id,
            workload_classification_id=setup.actual_workload_id,
            observed_at=datetime(2035, 5, 1, tzinfo=UTC),
            lookback_days=90,
            limit=64,
            resource_specific=True,
        )

    assert len(observations) == 1
    assert observations[0].service_session_id == session_id
    assert observations[0].active_service_seconds == 1500
    assert expired == ()
