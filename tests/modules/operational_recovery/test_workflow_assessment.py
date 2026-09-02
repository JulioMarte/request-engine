import pytest

from request_engine.modules.live_capacity.contracts.projection import (
    ProjectionReason,
    ProjectionState,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    classify_recovery_assessment,
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncidentStatus,
)

from .workflow_assessment_test_support import (
    ORG,
    QUEUE,
    FakeCapacity,
    FakeRepository,
    assessment,
    incident,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


def test_indeterminate_projection_is_material_without_numeric_shortfall() -> None:
    decision = classify_recovery_assessment(
        assessment(
            projection_state=ProjectionState.INDETERMINATE,
            projection_reasons=(ProjectionReason.OPEN_INTERRUPTION,),
        )
    )
    assert decision.material is True
    assert decision.impact_kind is RecoveryImpactKind.INDETERMINATE


def test_recall_hold_partial_timeline_is_not_material_without_shortfall() -> None:
    decision = classify_recovery_assessment(
        assessment(
            projection_state=ProjectionState.PARTIAL,
            projection_reasons=(ProjectionReason.ACTIVE_RECALL_HOLD,),
        )
    )
    assert decision.material is False
    assert decision.resolve is True
    assert decision.escalation_level == 0


def test_live_only_shortfall_is_delay_and_not_structural_capacity_shortfall() -> None:
    decision = classify_recovery_assessment(
        assessment(live_shortfall_seconds=1800, shortfall_seconds=1800)
    )
    assert decision.material is True
    assert decision.impact_kind is RecoveryImpactKind.DELAY
    assert decision.escalation_level == 1


@pytest.mark.asyncio
async def test_healthy_scope_without_incident_is_noop() -> None:
    repository = FakeRepository()
    current, recovery_incident = await reconcile_recovery_incident(
        organization_id=ORG,
        service_queue_id=QUEUE,
        repository=repository,
        capacity=FakeCapacity(assessment()),
    )
    assert current.shortfall_seconds == 0
    assert recovery_incident is None
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_existing_incident_resolves_only_from_fresh_healthy_assessment() -> None:
    repository = FakeRepository(incident())
    _, recovery_incident = await reconcile_recovery_incident(
        organization_id=ORG,
        service_queue_id=QUEUE,
        repository=repository,
        capacity=FakeCapacity(assessment()),
    )
    assert recovery_incident is not None
    assert recovery_incident.status is RecoveryIncidentStatus.RESOLVED
    assert repository.upserts[0]["resolve"] is True
