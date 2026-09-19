from request_engine.platform.security.capability_types import (
    AuthorityPlane,
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)
from request_engine.platform.security.operation_risk import OperationRiskClass


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
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
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
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    )


def _agent_capability(
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
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    )


def _agent_query_capability(key: str, description: str) -> CapabilityDefinition:
    return query_capability(
        key,
        CapabilityExposure.OPERATOR,
        description,
        authority_plane=AuthorityPlane.TENANT_CONTROL,
    )


def _integration_capability(
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
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    )


IDENTITY_AUTHORITY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "authority.read_self",
        CapabilityExposure.OPERATOR,
        "Inspect the current Principal's active tenant Party relationships and revisions.",
    ),
    query_capability(
        "authority.inspect_resource",
        CapabilityExposure.OPERATOR,
        "Inspect the caller's effective resource authority for an explicitly supported operation.",
    ),
    _authority_capability(
        "platform.principal.provision",
        AuthorityPlane.PLATFORM,
        "Provision a platform-scoped Principal within a bounded authority ceiling.",
    ),
    command_capability(
        "platform.tenant_provisioner.provision",
        CapabilityExposure.OPERATOR,
        "Provision a Principal that may create organizations without inheriting tenant control.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.SERVER_SELECTED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "platform.recovery_operator.provision",
        CapabilityExposure.OPERATOR,
        "Provision a bounded HUMAN platform recovery approver with no organization or "
        "recovery-issuance authority.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.SERVER_SELECTED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "organization.provision",
        CapabilityExposure.OPERATOR,
        "Create a new organization through the zero-to-one provisioning boundary.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.SERVER_SELECTED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "platform.identity.recover",
        CapabilityExposure.OPERATOR,
        "Request, issue, or revoke a governed native identity recovery case.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    query_capability(
        "platform.identity.read",
        CapabilityExposure.OPERATOR,
        "List and inspect governed identity recovery cases without exposing secrets.",
        authority_plane=AuthorityPlane.PLATFORM,
    ),
    command_capability(
        "platform.identity.recovery_approve",
        CapabilityExposure.OPERATOR,
        "Approve a governed native identity recovery case as a distinct HUMAN operator.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "platform.identity.disable",
        CapabilityExposure.OPERATOR,
        "Terminally disable a native identity across every tenant and platform binding.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    query_capability(
        "platform.provisioner.read",
        CapabilityExposure.OPERATOR,
        "List and inspect platform provisioners without exposing credentials.",
        authority_plane=AuthorityPlane.PLATFORM,
    ),
    command_capability(
        "platform.provisioner.manage_lifecycle",
        CapabilityExposure.OPERATOR,
        "Suspend, reactivate, or terminally revoke a platform provisioner.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    query_capability(
        "platform.owner.read",
        CapabilityExposure.OPERATOR,
        "List and inspect platform owners/admins without exposing invitation proofs.",
        authority_plane=AuthorityPlane.PLATFORM,
    ),
    command_capability(
        "platform.owner.invite",
        CapabilityExposure.OPERATOR,
        "Invite a credentialed Native human identity as a pending platform owner.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.NONE,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
        requires_recent_authentication=True,
    ),
    command_capability(
        "platform.owner.manage_membership",
        CapabilityExposure.OPERATOR,
        "Suspend, reactivate, or terminally revoke a platform owner membership.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
        requires_recent_authentication=True,
    ),
    command_capability(
        "platform.owner.manage_authority",
        CapabilityExposure.OPERATOR,
        "Replace bounded platform authority for another platform owner.",
        authority_plane=AuthorityPlane.PLATFORM,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
        requires_recent_authentication=True,
    ),
    _staff_capability(
        "staff.invite",
        "Invite a credentialed Native human identity into the current tenant.",
    ),
    query_capability(
        "staff.read",
        CapabilityExposure.OPERATOR,
        "Inspect tenant staff membership, standing grants and current revisions.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
    ),
    _staff_capability(
        "staff.manage_membership",
        "Activate, suspend, or revoke human staff membership in the current tenant.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _staff_capability(
        "staff.manage_authority",
        "Replace bounded operational and tenant-control authority for human staff.",
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
    _agent_query_capability(
        "agent.read",
        "Inspect tenant agent profiles, standing capabilities and current revisions.",
    ),
    _agent_query_capability(
        "agent.policy.read",
        "Read the tool/risk policy ceiling of an Agent Principal in the current tenant.",
    ),
    _agent_capability(
        "agent.manage_policy",
        "Replace the tool/risk policy ceiling of an Agent Principal in the current tenant.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _agent_capability(
        "delegation.create",
        "Delegate bounded temporary authority the delegator may itself delegate.",
    ),
    _agent_capability(
        "delegation.revoke",
        "Revoke a bounded temporary delegation in the current tenant.",
    ),
    _integration_capability(
        "integration.provision",
        "Provision an INTEGRATION Principal and its workload identity in the current tenant.",
    ),
    query_capability(
        "integration.read",
        CapabilityExposure.OPERATOR,
        "Read integration status, authority revisions and credential metadata in this tenant.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
    ),
    _integration_capability(
        "integration.manage_authority",
        "Assign or revoke bounded standing authority for an INTEGRATION Principal.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _integration_capability(
        "integration.suspend",
        "Suspend, reactivate, or revoke an INTEGRATION Principal in the current tenant.",
    ),
    query_capability(
        "identity.binding.read",
        CapabilityExposure.OPERATOR,
        "Inspect tenant identity bindings without exposing subjects, tokens or verifiers.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
    ),
    command_capability(
        "identity.bind",
        CapabilityExposure.OPERATOR,
        "Suspend, reactivate, or revoke a tenant identity binding.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "controller_policy_upgrade",
        CapabilityExposure.OPERATOR,
        "Upgrade a tenant Principal's standing authority to an approved immutable "
        "controller policy within the actor's current delegable ceiling.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
        revision=RevisionPolicy.REQUIRED,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
    ),
    command_capability(
        "identity.link_self",
        CapabilityExposure.OPERATOR,
        "Self-service linking of a second proven identity to the caller's existing "
        "tenant Principal; never administrative linking.",
        authority_plane=AuthorityPlane.TENANT_CONTROL,
        revision=RevisionPolicy.NONE,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
        requires_recent_authentication=True,
    ),
)
