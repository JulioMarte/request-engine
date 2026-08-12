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

SessionFactory = async_sessionmaker[AsyncSession]


def create_postgres_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the process-level async PostgreSQL engine."""

    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
    )


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


@asynccontextmanager
async def tenant_transaction(
    session_factory: SessionFactory,
    organization_id: UUID,
) -> AsyncGenerator[AsyncSession]:
    """Open one task-local session and one explicit tenant-scoped transaction."""

    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id)
        yield session
