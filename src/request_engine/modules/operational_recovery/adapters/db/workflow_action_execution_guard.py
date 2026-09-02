from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory

_LOCK_HASH_SEED = 0x5245434F  # "RECO"


@asynccontextmanager
async def serialize_recovery_action_execution(
    session_factory: SessionFactory,
    *,
    action_id: UUID,
) -> AsyncGenerator[None, None]:
    """Allow only one active executor for one durable RecoveryAction.

    The transaction owns only a PostgreSQL advisory lock. Business owner writes
    keep their existing short module-owned transactions. PostgreSQL releases the
    lock automatically if this process/connection disappears, so crash/retry can
    reacquire the same action and resume from its durable owner-step state.
    """

    lock_identity = f"request-engine:operational-recovery:action:{action_id}"
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    hashtextextended(:lock_identity, :hash_seed)
                )
                """
            ),
            {
                "lock_identity": lock_identity,
                "hash_seed": _LOCK_HASH_SEED,
            },
        )
        yield
