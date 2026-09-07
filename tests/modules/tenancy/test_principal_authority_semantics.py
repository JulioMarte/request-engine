from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.domain.principal_authority import (
    AuthorityAssignmentRejected,
    DelegationGrant,
    DelegationStatus,
    ProvisioningAuthorityCeiling,
    effective_delegated_capabilities,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_provisioning_assignment_is_bounded_by_both_ceilings() -> None:
    ceiling = ProvisioningAuthorityCeiling(
        creator_delegable=frozenset({"organization.provision", "staff.read"}),
        provisioning_policy=frozenset({"organization.provision"}),
    )

    ceiling.require_assignment(frozenset({"organization.provision"}))
    with pytest.raises(AuthorityAssignmentRejected, match="staff.read"):
        ceiling.require_assignment(frozenset({"organization.provision", "staff.read"}))


def test_possession_does_not_imply_delegability() -> None:
    ceiling = ProvisioningAuthorityCeiling(
        creator_delegable=frozenset(),
        provisioning_policy=frozenset({"organization.provision"}),
    )

    with pytest.raises(AuthorityAssignmentRejected, match="organization.provision"):
        ceiling.require_assignment(frozenset({"organization.provision"}))


def test_delegated_agent_authority_is_intersection_not_union() -> None:
    now = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)
    grant = DelegationGrant(
        id=uuid4(),
        organization_id=uuid4(),
        delegator_principal_id=uuid4(),
        delegate_principal_id=uuid4(),
        allowed_capabilities=frozenset({"appointments.reschedule", "staff.read"}),
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
        revision=3,
    )

    effective = effective_delegated_capabilities(
        grant=grant,
        now=now,
        agent_policy_ceiling=frozenset({"appointments.reschedule", "catalog.search_offerings"}),
        delegator_current_delegable=frozenset({"appointments.reschedule", "staff.read"}),
        current_tool_policy=frozenset({"appointments.reschedule", "staff.read"}),
        current_context_policy=frozenset({"appointments.reschedule"}),
    )

    assert effective == frozenset({"appointments.reschedule"})
    assert "staff.read" not in effective
    assert "catalog.search_offerings" not in effective


def test_expired_or_revoked_delegation_has_no_effective_authority() -> None:
    now = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)
    common = dict(
        organization_id=uuid4(),
        delegator_principal_id=uuid4(),
        delegate_principal_id=uuid4(),
        allowed_capabilities=frozenset({"appointments.reschedule"}),
        revision=1,
    )
    policy = frozenset({"appointments.reschedule"})

    expired = DelegationGrant(
        id=uuid4(),
        not_before=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        **common,
    )
    revoked = DelegationGrant(
        id=uuid4(),
        not_before=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        status=DelegationStatus.REVOKED,
        **common,
    )

    for grant in (expired, revoked):
        assert (
            effective_delegated_capabilities(
                grant=grant,
                now=now,
                agent_policy_ceiling=policy,
                delegator_current_delegable=policy,
                current_tool_policy=policy,
                current_context_policy=policy,
            )
            == frozenset()
        )


def test_principal_cannot_delegate_to_itself() -> None:
    principal_id = uuid4()
    now = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="cannot delegate authority to itself"):
        DelegationGrant(
            id=uuid4(),
            organization_id=uuid4(),
            delegator_principal_id=principal_id,
            delegate_principal_id=principal_id,
            allowed_capabilities=frozenset({"appointments.reschedule"}),
            not_before=now,
            expires_at=now + timedelta(hours=1),
            revision=1,
        )
