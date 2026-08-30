from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.application.recovery_autonomy_configure import (
    CONFIGURE_CAPABILITY,
    configure_fingerprint,
    policy_from_result,
    policy_result,
)
from request_engine.modules.operational_recovery.application.recovery_autonomy_policy import (
    ConfigureRecoveryAutonomyCommand,
    RecoveryAutonomyPolicy,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryQueueNotFound
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)

_UPSERT = text(
    """
    INSERT INTO request_engine.operational_recovery_autonomy_policies (
        organization_id, service_queue_id, enabled, max_delay_minutes,
        max_auto_actions_per_incident, granted_by
    ) VALUES (
        :organization_id, :service_queue_id, :enabled,
        :max_delay_minutes, :max_auto_actions_per_incident, :granted_by
    )
    ON CONFLICT (organization_id, service_queue_id) DO UPDATE SET
        enabled = EXCLUDED.enabled,
        max_delay_minutes = EXCLUDED.max_delay_minutes,
        max_auto_actions_per_incident = EXCLUDED.max_auto_actions_per_incident,
        granted_by = EXCLUDED.granted_by,
        granted_at = clock_timestamp(), updated_at = clock_timestamp()
    RETURNING organization_id, service_queue_id, enabled, max_delay_minutes,
        max_auto_actions_per_incident, granted_by
    """
)

_QUEUE_EXISTS = text(
    "SELECT count(*) FROM request_engine.service_queues "
    "WHERE organization_id = :organization_id AND id = :service_queue_id"
)


def _policy(row: Any) -> RecoveryAutonomyPolicy:
    return RecoveryAutonomyPolicy(
        organization_id=cast(UUID, row[0]),
        service_queue_id=cast(UUID, row[1]),
        enabled=cast(bool, row[2]),
        max_delay_minutes=cast(int, row[3]),
        max_auto_actions_per_incident=cast(int, row[4]),
        granted_by=cast(UUID, row[5]),
    )


class PostgresRecoveryAutonomyPolicyStore:
    """Durable operator-granted envelope for one service queue, dormant until
    an operator explicitly enables it and revocable by disabling it again."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def configure(self, command: ConfigureRecoveryAutonomyCommand) -> RecoveryAutonomyPolicy:
        fingerprint = configure_fingerprint(command)
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=CONFIGURE_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return policy_from_result(replay)
            return await self._upsert(session, command, idempotency_id)

    async def _upsert(
        self,
        session: AsyncSession,
        command: ConfigureRecoveryAutonomyCommand,
        idempotency_id: UUID,
    ) -> RecoveryAutonomyPolicy:
        if (
            await session.execute(
                _QUEUE_EXISTS,
                {
                    "organization_id": command.organization_id,
                    "service_queue_id": command.service_queue_id,
                },
            )
        ).scalar_one() != 1:
            raise RecoveryQueueNotFound(command.service_queue_id)
        row = (
            await session.execute(
                _UPSERT,
                {
                    "organization_id": command.organization_id,
                    "service_queue_id": command.service_queue_id,
                    "enabled": command.enabled,
                    "max_delay_minutes": command.max_delay_minutes,
                    "max_auto_actions_per_incident": command.max_auto_actions_per_incident,
                    "granted_by": command.principal_id,
                },
            )
        ).one()
        policy = _policy(row)
        await complete_idempotency(session, idempotency_id, policy_result(policy))
        return policy
