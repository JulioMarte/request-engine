from request_engine.platform.security.capability_types import (
    AuthorityPlane,
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
)


def _authority_capability(
    key: str,
    plane: AuthorityPlane,
    description: str,
) -> CapabilityDefinition:
    return command_capability(
        key,
        CapabilityExposure.INTERNAL,
        description,
        authority_plane=plane,
        runtime_available=False,
    )


def _staff_capability(
    key: str,
    description: str,
    *,
    revision: RevisionPolicy = RevisionPolicy.NONE,
) -> CapabilityDefinition:
    return command_capability(
        key,
        CapabilityExposure.OPERATOR,
        description,
        authority_plane=AuthorityPlane.TENANT_CONTROL,
        revision=revision,
    )


def _agent_capability(key: str, description: str) -> CapabilityDefinition:
    return command_capability(
        key,
        CapabilityExposure.OPERATOR,
        description,
        authority_plane=AuthorityPlane.TENANT_CONTROL,
    )


IDENTITY_AUTHORITY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    _authority_capability(
        "platform.principal.provision",
        AuthorityPlane.PLATFORM,
        "Provision a platform-scoped Principal within a bounded authority ceiling.",
    ),
    _authority_capability(
        "platform.tenant_provisioner.provision",
        AuthorityPlane.PLATFORM,
        "Provision a Principal that may create organizations without inheriting tenant control.",
    ),
    _authority_capability(
        "organization.provision",
        AuthorityPlane.PLATFORM,
        "Create a new organization through the zero-to-one provisioning boundary.",
    ),
    _authority_capability(
        "platform.identity.recover",
        AuthorityPlane.PLATFORM,
        "Execute the narrowly governed platform identity recovery workflow.",
    ),
    _staff_capability(
        "staff.invite",
        "Invite a credentialed Native human identity into the current tenant.",
    ),
    _staff_capability(
        "staff.manage_membership",
        "Activate, suspend, or revoke human staff membership in the current tenant.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _staff_capability(
        "staff.manage_authority",
        "Replace bounded tenant-control authority for human staff.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _agent_capability(
        "agent.provision",
        "Provision an Agent Principal and its workload identity in the current tenant.",
    ),
    _agent_capability(
        "agent.manage_authority",
        "Assign or revoke bounded standing authority for an Agent Principal.",
    ),
    _agent_capability(
        "agent.suspend",
        "Suspend, reactivate, or revoke an Agent Principal in the current tenant.",
    ),
    _agent_capability(
        "delegation.create",
        "Delegate bounded temporary authority the delegator may itself delegate.",
    ),
    _agent_capability(
        "delegation.revoke",
        "Revoke a bounded temporary delegation in the current tenant.",
    ),
    _authority_capability(
        "identity.bind",
        AuthorityPlane.TENANT_CONTROL,
        "Bind an authenticated external or native subject to an existing Principal.",
    ),
)
