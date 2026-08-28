from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
)


class RecoveryAssessmentRepository(Protocol):
    async def get_open_incident(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> RecoveryIncident | None: ...

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
    ) -> RecoveryIncident: ...


class RecoveryWorkflowRepository(RecoveryAssessmentRepository, Protocol):
    async def get_incident(
        self, *, organization_id: UUID, incident_id: UUID
    ) -> RecoveryIncident | None: ...

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
    ) -> tuple[RecoveryAction, bool]: ...

    async def transition_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        expected_status: RecoveryActionStatus,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
    ) -> RecoveryAction: ...
