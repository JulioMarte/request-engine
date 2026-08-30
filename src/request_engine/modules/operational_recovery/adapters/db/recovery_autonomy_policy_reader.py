from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.application.recovery_autonomy_policy import (
    RecoveryAutonomyPolicy,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_SELECT_ACTIVE = text(
    """
    SELECT organization_id, service_queue_id, enabled, max_delay_minutes,
           max_auto_actions_per_incident, granted_by
    FROM request_engine.operational_recovery_autonomy_policies
    WHERE organization_id = :organization_id
      AND service_queue_id = :service_queue_id
      AND enabled
    """
)

_ATTEMPT_KEYS = text(
    """
    SELECT idempotency_key FROM request_engine.operational_recovery_actions
    WHERE organization_id = :organization_id AND incident_id = :incident_id
      AND idempotency_key LIKE 'recovery-auto:%'
    """
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


class PostgresRecoveryAutonomyPolicyReader:
    """Runtime reads for the autonomy envelope: the currently active policy of
    a queue and the durable attempt ledger of one incident."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def active_policy(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> RecoveryAutonomyPolicy | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                await session.execute(
                    _SELECT_ACTIVE,
                    {"organization_id": organization_id, "service_queue_id": service_queue_id},
                )
            ).first()
        return None if row is None else _policy(row)

    async def autonomous_attempt_keys(
        self, *, organization_id: UUID, incident_id: UUID
    ) -> frozenset[str]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        _ATTEMPT_KEYS,
                        {"organization_id": organization_id, "incident_id": incident_id},
                    )
                )
                .scalars()
                .all()
            )
        return frozenset(cast("list[str]", rows))
