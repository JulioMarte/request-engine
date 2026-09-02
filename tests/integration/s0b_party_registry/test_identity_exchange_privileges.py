from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import SessionFactory, tenant_transaction

from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]

_GLOBAL_TABLES = (
    "portable_person_identities",
    "portable_person_identifiers",
    "portable_person_profiles",
    "identity_exchange_candidates",
)


async def _assert_no_global_select(
    session_factory: SessionFactory,
    organization_id: UUID,
) -> None:
    for table in _GLOBAL_TABLES:
        with pytest.raises(DBAPIError):
            async with tenant_transaction(session_factory, organization_id) as session:
                await session.execute(text(f"SELECT * FROM request_engine.{table}"))


@pytest.mark.asyncio
async def test_runtime_app_has_no_direct_global_identity_reads(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0d-app-privileges")
    await _assert_no_global_select(app_session_factory, world.organization_id)


@pytest.mark.asyncio
async def test_runtime_worker_has_no_direct_global_identity_reads(
    admin_conn: PgConnection,
    worker_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0d-worker-privileges")
    await _assert_no_global_select(worker_session_factory, world.organization_id)
