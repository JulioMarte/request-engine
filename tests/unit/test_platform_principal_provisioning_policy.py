import pytest

from request_engine.modules.tenancy.domain.platform_provisioning import (
    PlatformPrincipalProvisioningRequest,
    require_platform_principal_assignment,
)
from request_engine.modules.tenancy.domain.principal_authority import AuthorityAssignmentRejected


def _request(*capabilities: str) -> PlatformPrincipalProvisioningRequest:
    return PlatformPrincipalProvisioningRequest(
        external_subject="native:provisioner-b",
        desired_capabilities=frozenset(capabilities),
        delegable_capabilities=frozenset(capabilities),
    )


def test_platform_creator_can_only_assign_current_delegable_authority_inside_policy() -> None:
    request = _request("organization.provision")

    require_platform_principal_assignment(
        creator_capabilities=frozenset({"platform.principal.provision", "organization.provision"}),
        creator_delegable=frozenset({"organization.provision"}),
        policy_ceiling=frozenset({"organization.provision"}),
        request=request,
    )


@pytest.mark.parametrize(
    ("requested", "match"),
    [
        ("appointments.book", "non-platform capability"),
        ("staff.manage_authority", "non-platform capability"),
        ("future.superuser", "unknown capability"),
    ],
)
def test_platform_creator_cannot_assign_non_platform_or_unknown_authority(
    requested: str,
    match: str,
) -> None:
    with pytest.raises(AuthorityAssignmentRejected, match=match):
        require_platform_principal_assignment(
            creator_capabilities=frozenset(
                {"platform.principal.provision", "organization.provision"}
            ),
            creator_delegable=frozenset({requested}),
            policy_ceiling=frozenset({requested}),
            request=_request(requested),
        )


def test_possession_without_delegability_cannot_be_provisioned() -> None:
    with pytest.raises(AuthorityAssignmentRejected, match="outside creator/policy ceiling"):
        require_platform_principal_assignment(
            creator_capabilities=frozenset(
                {"platform.principal.provision", "organization.provision"}
            ),
            creator_delegable=frozenset(),
            policy_ceiling=frozenset({"organization.provision"}),
            request=_request("organization.provision"),
        )


def test_platform_principal_provision_requires_explicit_creator_capability() -> None:
    with pytest.raises(AuthorityAssignmentRejected, match="lacks platform.principal.provision"):
        require_platform_principal_assignment(
            creator_capabilities=frozenset({"organization.provision"}),
            creator_delegable=frozenset({"organization.provision"}),
            policy_ceiling=frozenset({"organization.provision"}),
            request=_request("organization.provision"),
        )


def test_delegable_subset_is_structural() -> None:
    with pytest.raises(ValueError, match="subset"):
        PlatformPrincipalProvisioningRequest(
            external_subject="native:provisioner-b",
            desired_capabilities=frozenset({"organization.provision"}),
            delegable_capabilities=frozenset({"platform.principal.provision"}),
        )
