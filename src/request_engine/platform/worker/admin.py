from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext


class PostgresWorkerReplayAdmin:
    """Internal operator surface for audited dead-letter replay.

    Actor identity is taken from a trusted authenticated execution context. Callers
    cannot provide an arbitrary Principal UUID to attribute the audit record.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def replay_scheduled_action(
        self,
        *,
        actor: ActorContext,
        action_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_dead_scheduled_action(
                :organization_id, :work_id, :additional_attempts, :reason
            )
            """,
            actor=actor,
            work_id=action_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def replay_outbox_message(
        self,
        *,
        actor: ActorContext,
        message_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_dead_outbox_message(
                :organization_id, :work_id, :additional_attempts, :reason
            )
            """,
            actor=actor,
            work_id=message_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def replay_provider_event(
        self,
        *,
        actor: ActorContext,
        provider_event_row_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_provider_event(
                :organization_id, :work_id, :additional_attempts, :reason
            )
            """,
            actor=actor,
            work_id=provider_event_row_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def _call(
        self,
        sql: str,
        *,
        actor: ActorContext,
        work_id: UUID,
        reason: str,
        additional_attempts: int,
    ) -> bool:
        if not reason.strip():
            raise ValueError("replay reason is required")
        if additional_attempts <= 0 or additional_attempts > 100:
            raise ValueError("additional_attempts must be between 1 and 100")

        async with actor_transaction(self._session_factory, actor) as session:
            result = await session.execute(
                text(sql),
                {
                    "organization_id": actor.organization_id,
                    "work_id": work_id,
                    "additional_attempts": additional_attempts,
                    "reason": reason,
                },
            )
            return bool(result.scalar_one())
