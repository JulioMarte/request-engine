from dataclasses import dataclass
from enum import StrEnum

_MAX_REASON_CODE = 80
_MAX_EXTERNAL_CASE_REFERENCE = 400
_MAX_POLICY_KEY = 200


class IdentitySubjectKind(StrEnum):
    STAFF_MEMBERSHIP = "StaffMembership"
    AGENT_PRINCIPAL = "AgentPrincipal"
    INTEGRATION_PRINCIPAL = "IntegrationPrincipal"
    INTEGRATION_CREDENTIAL = "IntegrationCredential"
    TENANT_CONTROLLER = "TenantController"


class IdentityAuditAction(StrEnum):
    INVITE = "invite"
    PROVISION = "provision"
    AUTHORITY_REPLACE = "authority_replace"
    STATUS_TRANSITION = "status_transition"
    CREDENTIAL_ROTATE = "credential_rotate"
    POLICY_UPGRADE = "policy_upgrade"


class IdentityAuditReason(StrEnum):
    STAFF_INVITED = "staff_invited"
    AGENT_PROVISIONED = "agent_provisioned"
    INTEGRATION_PROVISIONED = "integration_provisioned"
    AUTHORITY_REPLACED = "authority_replaced"
    STAFF_ACTIVATED = "staff_activated"
    STAFF_SUSPENDED = "staff_suspended"
    STAFF_REVOKED = "staff_revoked"
    AGENT_ACTIVATED = "agent_activated"
    AGENT_SUSPENDED = "agent_suspended"
    AGENT_REVOKED = "agent_revoked"
    INTEGRATION_ACTIVATED = "integration_activated"
    INTEGRATION_SUSPENDED = "integration_suspended"
    INTEGRATION_REVOKED = "integration_revoked"
    CREDENTIAL_ROTATED = "credential_rotated"
    CONTROLLER_POLICY_UPGRADED = "controller_policy_upgraded"


_STATUS_REASONS: dict[IdentitySubjectKind, dict[str, IdentityAuditReason]] = {
    IdentitySubjectKind.STAFF_MEMBERSHIP: {
        "active": IdentityAuditReason.STAFF_ACTIVATED,
        "suspended": IdentityAuditReason.STAFF_SUSPENDED,
        "revoked": IdentityAuditReason.STAFF_REVOKED,
    },
    IdentitySubjectKind.AGENT_PRINCIPAL: {
        "active": IdentityAuditReason.AGENT_ACTIVATED,
        "suspended": IdentityAuditReason.AGENT_SUSPENDED,
        "revoked": IdentityAuditReason.AGENT_REVOKED,
    },
    IdentitySubjectKind.INTEGRATION_PRINCIPAL: {
        "active": IdentityAuditReason.INTEGRATION_ACTIVATED,
        "suspended": IdentityAuditReason.INTEGRATION_SUSPENDED,
        "revoked": IdentityAuditReason.INTEGRATION_REVOKED,
    },
}


def status_transition_reason(
    subject_kind: IdentitySubjectKind,
    target_status: str,
) -> IdentityAuditReason:
    reasons = _STATUS_REASONS.get(subject_kind)
    if reasons is None or target_status not in reasons:
        raise ValueError(f"no audit reason for {subject_kind.value} transition to {target_status}")
    return reasons[target_status]


@dataclass(frozen=True, slots=True)
class IdentityAuditDetails:
    """Typed, secret-free audit details for one tenant identity command effect."""

    action: IdentityAuditAction
    reason_code: IdentityAuditReason
    subject_kind: IdentitySubjectKind
    revision_before: int
    revision_after: int
    external_case_reference: str | None = None
    source_policy_key: str | None = None
    target_policy_key: str | None = None

    def __post_init__(self) -> None:
        if self.revision_before < 0:
            raise ValueError("revision_before cannot be negative")
        if self.revision_after < self.revision_before:
            raise ValueError("revision_after cannot precede revision_before")
        if len(self.reason_code.value) > _MAX_REASON_CODE:
            raise ValueError("reason_code cannot exceed 80 characters")
        if self.external_case_reference is not None:
            normalized = self.external_case_reference.strip()
            if not normalized or len(normalized) > _MAX_EXTERNAL_CASE_REFERENCE:
                raise ValueError(
                    "external_case_reference must contain between 1 and 400 characters"
                )
        for policy_key in (self.source_policy_key, self.target_policy_key):
            if policy_key is None:
                continue
            normalized_policy = policy_key.strip()
            if not normalized_policy or len(normalized_policy) > _MAX_POLICY_KEY:
                raise ValueError("policy_key must contain between 1 and 200 characters")

    def to_details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "action": self.action.value,
            "reason_code": self.reason_code.value,
            "subject_kind": self.subject_kind.value,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
        }
        if self.external_case_reference is not None:
            details["external_case_reference"] = self.external_case_reference.strip()
        if self.source_policy_key is not None:
            details["source_policy_key"] = self.source_policy_key.strip()
        if self.target_policy_key is not None:
            details["target_policy_key"] = self.target_policy_key.strip()
        return details
