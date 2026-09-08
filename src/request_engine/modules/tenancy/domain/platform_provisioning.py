from dataclasses import dataclass

from request_engine.modules.tenancy.domain.principal_authority import (
    AuthorityAssignmentRejected,
    ProvisioningAuthorityCeiling,
)
from request_engine.platform.security.capabilities import (
    AuthorityPlane,
    capability_definition,
)

_PLATFORM_PROVISION_CAPABILITY = "platform.principal.provision"


@dataclass(frozen=True, slots=True)
class PlatformPrincipalProvisioningRequest:
    external_subject: str
    desired_capabilities: frozenset[str]
    delegable_capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if not self.external_subject.strip():
            raise ValueError("platform Principal external_subject must be nonblank")
        if not self.desired_capabilities:
            raise ValueError("platform Principal provisioning requires explicit authority")
        if not self.delegable_capabilities <= self.desired_capabilities:
            raise ValueError("delegable authority must be a subset of possessed authority")


def require_platform_principal_assignment(
    *,
    creator_capabilities: frozenset[str],
    creator_delegable: frozenset[str],
    policy_ceiling: frozenset[str],
    request: PlatformPrincipalProvisioningRequest,
) -> None:
    if _PLATFORM_PROVISION_CAPABILITY not in creator_capabilities:
        raise AuthorityAssignmentRejected("creator lacks platform.principal.provision")

    requested = request.desired_capabilities
    for key in requested:
        definition = capability_definition(key)
        if definition is None:
            raise AuthorityAssignmentRejected(f"unknown capability cannot be provisioned: {key}")
        if definition.authority_plane is not AuthorityPlane.PLATFORM:
            raise AuthorityAssignmentRejected(
                f"non-platform capability cannot be assigned to a platform Principal: {key}"
            )

    ceiling = ProvisioningAuthorityCeiling(
        creator_delegable=creator_delegable,
        provisioning_policy=policy_ceiling,
    )
    ceiling.require_assignment(requested)
    ceiling.require_assignment(request.delegable_capabilities)
