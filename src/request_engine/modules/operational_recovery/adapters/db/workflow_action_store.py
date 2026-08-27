from collections.abc import Mapping
from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.workflow_action_prepare import (
    prepare_action_row,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_action_transition import (
    transition_action_row,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRecoveryActionStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare_action(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        principal_id: UUID,
        action_kind: RecoveryActionKind,
        idempotency_key: str,
        command_fingerprint: str,
        expected_source_revision: int,
        payload: Mapping[str, object],
    ) -> tuple[RecoveryAction, bool]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await prepare_action_row(
                session,
                organization_id=organization_id,
                incident_id=incident_id,
                principal_id=principal_id,
                action_kind=action_kind,
                idempotency_key=idempotency_key,
                command_fingerprint=command_fingerprint,
                expected_source_revision=expected_source_revision,
                payload=payload,
            )

    async def transition_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
    ) -> RecoveryAction:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await transition_action_row(
                session,
                organization_id=organization_id,
                action_id=action_id,
                status=status,
                owner_steps=owner_steps,
                failure_code=failure_code,
            )
