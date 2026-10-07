from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.api.controller_policy_adoption_routes import (
    controller_policy_adoption_review_view,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ControllerPolicyAdoptionReview,
    ControllerPolicyAdoptionSummary,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.security]


def _review(*, revoked_capabilities: tuple[str, ...]) -> ControllerPolicyAdoptionReview:
    now = datetime.now(UTC)
    return ControllerPolicyAdoptionReview(
        request=ControllerPolicyAdoptionSummary(
            request_id=uuid4(),
            organization_id=uuid4(),
            controller_principal_id=uuid4(),
            source_policy_key="tenant-controller-v1",
            target_policy_key="tenant-controller-v6",
            expected_authority_revision=1,
            status="pending",
            request_revision=1,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        ),
        reason="Review only",
        current_authority_revision=1,
        proposed_capabilities=("booking.book",),
        revoked_capabilities=revoked_capabilities,
    )


def test_review_projection_names_the_revoked_grant_signal_without_claiming_eligibility() -> None:
    clean = controller_policy_adoption_review_view(_review(revoked_capabilities=()))
    restoration_blocked = controller_policy_adoption_review_view(
        _review(revoked_capabilities=("booking.book",))
    )

    assert clean.proposed_delta_does_not_restore_revoked_capabilities is True
    assert restoration_blocked.proposed_delta_does_not_restore_revoked_capabilities is False
    assert "proposed_delta_does_not_restore_revoked_capabilities" in clean.model_dump()
    assert "capability_delta_is_non_revoking" not in clean.model_dump()
