from collections.abc import Mapping
from dataclasses import replace
from typing import cast
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionConflict,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)

from .workflow_schedule_test_support import (
    ACTION,
    INCIDENT,
    LOCATION,
    NOW,
    ORG,
    PRINCIPAL,
    QUEUE,
    RESOURCE,
)


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.incident = RecoveryIncident(
            INCIDENT,
            ORG,
            QUEUE,
            RESOURCE,
            LOCATION,
            RecoveryIncidentStatus.OPEN,
            RecoveryImpactKind.CAPACITY_SHORTFALL,
            1,
            3,
            "source:v1",
            None,
            NOW,
            NOW,
            None,
            1,
        )
        self.action: RecoveryAction | None = None

    async def get_incident(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
    ) -> RecoveryIncident | None:
        return self.incident if organization_id == ORG and incident_id == INCIDENT else None

    async def get_open_incident(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryIncident | None:
        return self.incident if organization_id == ORG and service_queue_id == QUEUE else None

    async def upsert_assessment(self, **kwargs: object) -> RecoveryIncident:
        resolve = bool(kwargs["resolve"])
        status = RecoveryIncidentStatus.RESOLVED if resolve else RecoveryIncidentStatus.OPEN
        self.incident = replace(
            self.incident,
            status=status,
            source_revision=cast(int, kwargs["source_revision"]),
            source_fingerprint=cast(str, kwargs["source_fingerprint"]),
            revision=self.incident.revision + 1,
        )
        return self.incident

    async def prepare_action(self, **kwargs: object) -> tuple[RecoveryAction, bool]:
        if self.action is not None:
            return self.action, False
        self.action = RecoveryAction(
            ACTION,
            ORG,
            INCIDENT,
            cast(RecoveryActionKind, kwargs["action_kind"]),
            RecoveryActionStatus.PREPARED,
            PRINCIPAL,
            cast(str, kwargs["idempotency_key"]),
            cast(str, kwargs["command_fingerprint"]),
            cast(int, kwargs["expected_source_revision"]),
            cast(Mapping[str, object], kwargs["payload"]),
            {},
            None,
            NOW,
            None,
            None,
        )
        return self.action, True

    async def transition_action(
        self,
        *,
        expected_status: RecoveryActionStatus,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
        **_: object,
    ) -> RecoveryAction:
        assert self.action is not None
        if self.action.status is not expected_status:
            if self.action.status is status:
                return self.action
            raise RecoveryActionConflict("simulated CAS conflict")
        self.action = replace(
            self.action,
            status=status,
            owner_steps=self.action.owner_steps if owner_steps is None else owner_steps,
            failure_code=failure_code,
        )
        return self.action
