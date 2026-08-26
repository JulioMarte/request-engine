from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.read_snapshot_types import ReadSnapshot
from request_engine.platform.db.session import (
    SessionFactory,
    set_actor_context,
    set_tenant_context,
)
from request_engine.platform.security.execution_context import current_actor_context


@dataclass(frozen=True, slots=True)
class PostgresReadSnapshot:
    organization_id: UUID
    session: AsyncSession


def postgres_snapshot_session(snapshot: ReadSnapshot) -> AsyncSession:
    if not isinstance(snapshot, PostgresReadSnapshot):
        raise TypeError("read snapshot is not backed by PostgreSQL")
    return snapshot.session


@asynccontextmanager
async def tenant_read_snapshot(
    session_factory: SessionFactory,
    organization_id: UUID,
) -> AsyncGenerator[ReadSnapshot]:
    """Open one tenant-scoped, read-only REPEATABLE READ PostgreSQL snapshot."""

    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        actor = current_actor_context()
        if actor is not None:
            if actor.organization_id != organization_id:
                raise RuntimeError("task-local actor tenant does not match snapshot tenant")
            await set_actor_context(session, actor)
        else:
            await set_tenant_context(session, organization_id)
        yield PostgresReadSnapshot(organization_id=organization_id, session=session)
