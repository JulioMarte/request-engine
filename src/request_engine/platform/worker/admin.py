from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


class PostgresWorkerReplayAdmin:
    """Internal operator surface for audited dead-letter replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def replay_scheduled_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        actor_principal_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_dead_scheduled_action(
                :organization_id, :work_id, :actor_principal_id,
                :additional_attempts, :reason
            )
            """,
            organization_id=organization_id,
            work_id=action_id,
            actor_principal_id=actor_principal_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def replay_outbox_message(
        self,
        *,
        organization_id: UUID,
        message_id: UUID,
        actor_principal_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_dead_outbox_message(
                :organization_id, :work_id, :actor_principal_id,
                :additional_attempts, :reason
            )
            """,
            organization_id=organization_id,
            work_id=message_id,
            actor_principal_id=actor_principal_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def replay_provider_event(
        self,
        *,
        organization_id: UUID,
        provider_event_row_id: UUID,
        actor_principal_id: UUID,
        reason: str,
        additional_attempts: int = 3,
    ) -> bool:
        return await self._call(
            """
            SELECT request_admin.replay_provider_event(
                :organization_id, :work_id, :actor_principal_id,
                :additional_attempts, :reason
            )
            """,
            organization_id=organization_id,
            work_id=provider_event_row_id,
            actor_principal_id=actor_principal_id,
            reason=reason,
            additional_attempts=additional_attempts,
        )

    async def _call(
        self,
        sql: str,
        *,
        organization_id: UUID,
        work_id: UUID,
        actor_principal_id: UUID,
        reason: str,
        additional_attempts: int,
    ) -> bool:
        if not reason.strip():
            raise ValueError("replay reason is required")
        if additional_attempts <= 0 or additional_attempts > 100:
            raise ValueError("additional_attempts must be between 1 and 100")
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(sql),
                {
                    "organization_id": organization_id,
                    "work_id": work_id,
                    "actor_principal_id": actor_principal_id,
                    "additional_attempts": additional_attempts,
                    "reason": reason,
                },
            )
            return bool(result.scalar_one())
