from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.execution_context import current_actor_context

SessionFactory = async_sessionmaker[AsyncSession]


def create_postgres_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the process-level async PostgreSQL engine."""

    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Create task-local AsyncSession instances with explicit transaction framing."""

    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def set_tenant_context(session: AsyncSession, organization_id: UUID) -> None:
    """Bind the current transaction to one tenant for PostgreSQL RLS."""

    await session.execute(
        text("SELECT set_config('request_engine.organization_id', :organization_id, true)"),
        {"organization_id": str(organization_id)},
    )


async def set_actor_context(session: AsyncSession, actor: ActorContext) -> None:
    """Bind authenticated execution provenance to the current DB transaction."""

    await session.execute(
        text(
            """
            SELECT
                set_config('request_engine.organization_id', :organization_id, true),
                set_config('request_engine.authenticated_principal_id', :principal_id, true),
                set_config('request_engine.principal_kind', :principal_kind, true),
                set_config('request_engine.authentication_method', :authentication_method, true),
                set_config('request_engine.correlation_id', :correlation_id, true),
                set_config('request_engine.credential_id', :credential_id, true)
            """
        ),
        {
            "organization_id": str(actor.organization_id),
            "principal_id": str(actor.principal_id),
            "principal_kind": actor.principal_kind.value,
            "authentication_method": actor.authentication_method,
            "correlation_id": str(actor.correlation_id),
            "credential_id": actor.credential_id or "",
        },
    )


@asynccontextmanager
async def tenant_transaction(
    session_factory: SessionFactory,
    organization_id: UUID,
) -> AsyncGenerator[AsyncSession]:
    """Open one tenant transaction and inherit trusted request provenance when present."""

    async with session_factory() as session, session.begin():
        actor = current_actor_context()
        if actor is not None:
            if actor.organization_id != organization_id:
                raise RuntimeError("task-local actor tenant does not match transaction tenant")
            await set_actor_context(session, actor)
        else:
            await set_tenant_context(session, organization_id)
        yield session


@asynccontextmanager
async def actor_transaction(
    session_factory: SessionFactory,
    actor: ActorContext,
) -> AsyncGenerator[AsyncSession]:
    """Open a transaction bound to trusted tenant and Principal provenance."""

    async with session_factory() as session, session.begin():
        await set_actor_context(session, actor)
        yield session
