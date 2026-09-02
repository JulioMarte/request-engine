from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.workflow_action_store import (
    PostgresRecoveryActionStore,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_store import (
    PostgresRecoveryIncidentStore,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryWorkflowRepository(RecoveryWorkflowRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._incidents = PostgresRecoveryIncidentStore(session_factory)
        self._actions = PostgresRecoveryActionStore(session_factory)

    async def get_incident(self, **kwargs: object) -> RecoveryIncident | None:
        return await self._incidents.get_incident(**kwargs)  # type: ignore[arg-type]

    async def get_open_incident(self, **kwargs: object) -> RecoveryIncident | None:
        return await self._incidents.get_open_incident(**kwargs)  # type: ignore[arg-type]

    async def upsert_assessment(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
        resource_id: UUID,
        location_id: UUID,
        source_revision: int,
        source_fingerprint: str,
        impact_kind: RecoveryImpactKind,
        escalation_level: int,
        current_proposal_id: UUID | None,
        resolve: bool,
    ) -> RecoveryIncident:
        return await self._incidents.upsert_assessment(
            organization_id=organization_id,
            service_queue_id=service_queue_id,
            resource_id=resource_id,
            location_id=location_id,
            source_revision=source_revision,
            source_fingerprint=source_fingerprint,
            impact_kind=impact_kind,
            escalation_level=escalation_level,
            current_proposal_id=current_proposal_id,
            resolve=resolve,
        )

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
        return await self._actions.prepare_action(
            organization_id=organization_id,
            incident_id=incident_id,
            principal_id=principal_id,
            action_kind=action_kind,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            expected_source_revision=expected_source_revision,
            payload=payload,
        )

    def serialize_action_execution(self, *, action_id: UUID) -> AbstractAsyncContextManager[None]:
        return self._actions.serialize_action_execution(action_id=action_id)

    async def transition_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        expected_status: RecoveryActionStatus,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
    ) -> RecoveryAction:
        return await self._actions.transition_action(
            organization_id=organization_id,
            action_id=action_id,
            expected_status=expected_status,
            status=status,
            owner_steps=owner_steps,
            failure_code=failure_code,
        )
