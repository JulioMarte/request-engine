from uuid import UUID

import pytest

from request_engine.modules.operational_recovery.application.recovery_escalation_policy import (
    NEWLY_MATERIAL,
    WORSENING_SEVERITY,
    evaluate_recovery_escalation_policy,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryImpactKind

from .workflow_assessment_test_support import incident

PARTY_A = UUID(int=21)
PARTY_B = UUID(int=22)
PARTIES = (PARTY_A, PARTY_B)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


def decision(
    impact: RecoveryImpactKind = RecoveryImpactKind.CAPACITY_SHORTFALL,
    level: int = 2,
    *,
    material: bool = True,
    resolve: bool = False,
) -> RecoveryAssessmentDecision:
    return RecoveryAssessmentDecision(
        material=material,
        resolve=resolve,
        impact_kind=impact,
        escalation_level=level,
    )


def test_newly_material_incident_requires_operator_escalation_and_impact_notice() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(),
        previous=None,
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is True
    assert outcome.escalation_reason == NEWLY_MATERIAL
    assert outcome.customer_impact_required is True
    assert outcome.impact_recipient_party_ids == PARTIES


def test_unchanged_severity_does_not_re_escalate_but_keeps_impact_notice() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(),
        previous=incident(),
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is False
    assert outcome.escalation_reason is None
    assert outcome.customer_impact_required is True
    assert outcome.impact_recipient_party_ids == PARTIES


def test_worsening_severity_re_escalates() -> None:
    previous = incident()
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(RecoveryImpactKind.INDETERMINATE, 3),
        previous=previous,
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is True
    assert outcome.escalation_reason == WORSENING_SEVERITY


def test_improved_severity_does_not_escalate() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(RecoveryImpactKind.DELAY, 1),
        previous=incident(),
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is False
    assert outcome.escalation_reason is None
    assert outcome.customer_impact_required is True


def test_resolution_clears_escalation_and_impact_requirements() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(material=False, resolve=True),
        previous=incident(),
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is False
    assert outcome.customer_impact_required is False
    assert outcome.impact_recipient_party_ids == ()


def test_indeterminate_truth_never_claims_customer_impact() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(RecoveryImpactKind.INDETERMINATE, 3),
        previous=None,
        affected_subject_party_ids=PARTIES,
    )
    assert outcome.operator_escalation_required is True
    assert outcome.customer_impact_required is False
    assert outcome.impact_recipient_party_ids == ()


def test_live_only_delay_without_affected_commitments_notifies_nobody() -> None:
    outcome = evaluate_recovery_escalation_policy(
        decision=decision(RecoveryImpactKind.DELAY, 1),
        previous=None,
        affected_subject_party_ids=(),
    )
    assert outcome.operator_escalation_required is True
    assert outcome.customer_impact_required is False
    assert outcome.impact_recipient_party_ids == ()
