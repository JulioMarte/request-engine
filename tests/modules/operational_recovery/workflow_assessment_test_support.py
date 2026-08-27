from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from request_engine.modules.live_capacity.contracts.projection import ProjectionState
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacityCheckpoint,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ORG = UUID(int=1)
QUEUE = UUID(int=2)
RESOURCE = UUID(int=3)
LOCATION = UUID(int=4)


def assessment(**changes: object) -> RecoveryCapacityAssessment:
    base = RecoveryCapacityAssessment(
        service_queue_id=QUEUE,
        resource_id=RESOURCE,
        location_id=LOCATION,
        observed_at=NOW,
        horizon_end=NOW + timedelta(hours=8),
        projection_state=ProjectionState.KNOWN,
        projection_reasons=(),
        executable_capacity_seconds=7200,
        committed_capacity_seconds=3600,
        scheduled_shortfall_seconds=0,
        live_shortfall_seconds=0,
        shortfall_seconds=0,
        source_fingerprint="source:2",
        source_snapshot={},
        checkpoint=RecoveryCapacityCheckpoint(1, 1, 1, 2, ()),
        affected_commitments=(),
    )
    return replace(base, **changes)


def incident() -> RecoveryIncident:
    return RecoveryIncident(
        id=UUID(int=8),
        organization_id=ORG,
        service_queue_id=QUEUE,
        resource_id=RESOURCE,
        location_id=LOCATION,
        status=RecoveryIncidentStatus.OPEN,
        impact_kind=RecoveryImpactKind.CAPACITY_SHORTFALL,
        escalation_level=2,
        source_revision=1,
        source_fingerprint="source:1",
        current_proposal_id=None,
        opened_at=NOW,
        last_assessed_at=NOW,
        resolved_at=None,
        revision=1,
    )


class FakeCapacity:
    def __init__(self, value: RecoveryCapacityAssessment) -> None:
        self.value = value

    async def assess_recovery_capacity(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryCapacityAssessment:
        assert organization_id == ORG
        assert service_queue_id == QUEUE
        return self.value


class FakeRepository:
    def __init__(self, existing: RecoveryIncident | None = None) -> None:
        self.existing = existing
        self.upserts: list[dict[str, object]] = []

    async def get_open_incident(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryIncident | None:
        return self.existing

    async def upsert_assessment(self, **kwargs: object) -> RecoveryIncident:
        self.upserts.append(dict(kwargs))
        status = RecoveryIncidentStatus.RESOLVED if kwargs["resolve"] else RecoveryIncidentStatus.OPEN
        return RecoveryIncident(
            id=UUID(int=9),
            organization_id=ORG,
            service_queue_id=QUEUE,
            resource_id=RESOURCE,
            location_id=LOCATION,
            status=status,
            impact_kind=kwargs["impact_kind"],
            escalation_level=kwargs["escalation_level"],
            source_revision=kwargs["source_revision"],
            source_fingerprint=kwargs["source_fingerprint"],
            current_proposal_id=None,
            opened_at=NOW,
            last_assessed_at=NOW,
            resolved_at=NOW if status is RecoveryIncidentStatus.RESOLVED else None,
            revision=2,
        )
