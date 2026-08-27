from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.live_capacity.contracts.projection import ProjectionReason, ProjectionState
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacityCheckpoint,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    classify_recovery_assessment,
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ORG = UUID(int=1)
QUEUE = UUID(int=2)
RESOURCE = UUID(int=3)
LOCATION = UUID(int=4)


def _assessment(**changes: object) -> RecoveryCapacityAssessment:
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


class FakeCapacity:
    def __init__(self, assessment: RecoveryCapacityAssessment) -> None:
        self.assessment = assessment

    async def assess_recovery_capacity(self, *, organization_id: UUID, service_queue_id: UUID):
        assert organization_id == ORG
        assert service_queue_id == QUEUE
        return self.assessment


class FakeRepository:
    def __init__(self, existing: RecoveryIncident | None = None) -> None:
        self.existing = existing
        self.upserts: list[dict[str, object]] = []

    async def get_open_incident(self, *, organization_id: UUID, service_queue_id: UUID):
        return self.existing

    async def upsert_assessment(self, **kwargs: object):
        self.upserts.append(dict(kwargs))
        status = RecoveryIncidentStatus.RESOLVED if kwargs["resolve"] else RecoveryIncidentStatus.OPEN
        return RecoveryIncident(
            id=UUID(int=9), organization_id=ORG, service_queue_id=QUEUE,
            resource_id=RESOURCE, location_id=LOCATION, status=status,
            impact_kind=kwargs["impact_kind"], escalation_level=kwargs["escalation_level"],
            source_revision=kwargs["source_revision"], source_fingerprint=kwargs["source_fingerprint"],
            current_proposal_id=None, opened_at=NOW, last_assessed_at=NOW,
            resolved_at=NOW if status is RecoveryIncidentStatus.RESOLVED else None, revision=2,
        )


def _incident() -> RecoveryIncident:
    return RecoveryIncident(
        id=UUID(int=8), organization_id=ORG, service_queue_id=QUEUE,
        resource_id=RESOURCE, location_id=LOCATION, status=RecoveryIncidentStatus.OPEN,
        impact_kind=RecoveryImpactKind.CAPACITY_SHORTFALL, escalation_level=2,
        source_revision=1, source_fingerprint="source:1", current_proposal_id=None,
        opened_at=NOW, last_assessed_at=NOW, resolved_at=None, revision=1,
    )


def test_indeterminate_projection_is_material_without_numeric_shortfall() -> None:
    decision = classify_recovery_assessment(
        _assessment(
            projection_state=ProjectionState.INDETERMINATE,
            projection_reasons=(ProjectionReason.OPEN_INTERRUPTION,),
        )
    )
    assert decision.material is True
    assert decision.impact_kind is RecoveryImpactKind.INDETERMINATE


def test_live_only_shortfall_is_delay_and_not_structural_capacity_shortfall() -> None:
    decision = classify_recovery_assessment(
        _assessment(live_shortfall_seconds=1800, shortfall_seconds=1800)
    )
    assert decision.material is True
    assert decision.impact_kind is RecoveryImpactKind.DELAY
    assert decision.escalation_level == 1


@pytest.mark.asyncio
async def test_healthy_scope_without_incident_is_noop() -> None:
    repository = FakeRepository()
    assessment, incident = await reconcile_recovery_incident(
        organization_id=ORG,
        service_queue_id=QUEUE,
        repository=repository,
        capacity=FakeCapacity(_assessment()),
    )
    assert assessment.shortfall_seconds == 0
    assert incident is None
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_existing_incident_resolves_only_from_fresh_healthy_assessment() -> None:
    repository = FakeRepository(_incident())
    _, incident = await reconcile_recovery_incident(
        organization_id=ORG,
        service_queue_id=QUEUE,
        repository=repository,
        capacity=FakeCapacity(_assessment()),
    )
    assert incident is not None
    assert incident.status is RecoveryIncidentStatus.RESOLVED
    assert repository.upserts[0]["resolve"] is True
