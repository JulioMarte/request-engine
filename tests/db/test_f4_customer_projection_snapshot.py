import psycopg
import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection
from f4_customer_projection_fixture import (
    create_principal,
    create_representation,
)

from request_engine.modules.queue.adapters.db.live_capacity_source import (
    PostgresQueueProjectionSource,
)
from request_engine.modules.queue.application.errors import SubjectAuthorityRequired
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_customer_projection_read_does_not_lock_authority_and_is_snapshot_coherent(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
) -> None:
    fixture = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, fixture.organization_id)
    representation_id = create_representation(
        admin_conn,
        organization_id=fixture.organization_id,
        principal_id=principal_id,
        party_id=fixture.party_b_id,
    )
    source = PostgresQueueProjectionSource()

    async with tenant_read_snapshot(command_session_factory, fixture.organization_id) as snapshot:
        first = await source.read_customer_projection_target(
            snapshot,
            organization_id=fixture.organization_id,
            principal_id=principal_id,
            queue_id=fixture.queue_id,
            subject_party_id=fixture.party_b_id,
            allow_subject_override=False,
        )
        with psycopg.connect(pg_conninfo) as revoker:
            revoker.execute("SET LOCAL lock_timeout = '250ms'")
            updated = revoker.execute(
                "UPDATE request_engine.representations SET status='revoked',revision=revision+1 "
                "WHERE organization_id=%s AND id=%s",
                (fixture.organization_id, representation_id),
            )
            assert updated.rowcount == 1
        second = await source.read_customer_projection_target(
            snapshot,
            organization_id=fixture.organization_id,
            principal_id=principal_id,
            queue_id=fixture.queue_id,
            subject_party_id=fixture.party_b_id,
            allow_subject_override=False,
        )
        assert second == first

    async with tenant_read_snapshot(command_session_factory, fixture.organization_id) as snapshot:
        with pytest.raises(SubjectAuthorityRequired):
            await source.read_customer_projection_target(
                snapshot,
                organization_id=fixture.organization_id,
                principal_id=principal_id,
                queue_id=fixture.queue_id,
                subject_party_id=fixture.party_b_id,
                allow_subject_override=False,
            )
