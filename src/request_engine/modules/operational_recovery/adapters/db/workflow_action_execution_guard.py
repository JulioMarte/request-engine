from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory

_LOCK_NAMESPACE = 0x5245434F  # "RECO"


@asynccontextmanager
async def serialize_recovery_action_execution(
    session_factory: SessionFactory,
    *,
    action_id: UUID,
) -> AsyncIterator[None]:
    """Allow only one active executor for one durable RecoveryAction.

    The transaction owns only a PostgreSQL advisory lock. Business owner writes
    keep their existing short module-owned transactions. PostgreSQL releases the
    lock automatically if this process/connection disappears, so crash/retry can
    reacquire the same action and resume from its durable owner-step state.
    """

    lock_identity = str(action_id)
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    :namespace,
                    hashtext(:lock_identity)
                )
                """
            ),
            {
                "namespace": _LOCK_NAMESPACE,
                "lock_identity": lock_identity,
            },
        )
        yield
