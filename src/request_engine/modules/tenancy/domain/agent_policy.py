from dataclasses import dataclass
from uuid import UUID

from request_engine.platform.security.capabilities import capability_is_known
from request_engine.platform.security.operation_risk import OperationRiskClass


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    agent_principal_id: UUID
    allowed_capabilities: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    risk_ceiling: OperationRiskClass
    max_mutations_per_minute: int
    policy_revision: int
    provenance_reference: str


def validate_agent_policy_risk_ceiling(value: OperationRiskClass) -> OperationRiskClass:
    if value is OperationRiskClass.AUTHORITY_CHANGE:
        raise ValueError("risk_ceiling must not be authority_change")
    return value


def validate_agent_policy_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("agent policy capabilities must not contain duplicates")
    for capability in capabilities:
        if not capability or capability != capability.strip() or len(capability) > 200:
            raise ValueError(f"invalid agent policy capability key: {capability!r}")
        if not capability_is_known(capability):
            raise ValueError(f"unknown or non-canonical capability: {capability}")
    return capabilities


def validate_agent_policy_rule_set(
    *,
    risk_ceiling: OperationRiskClass,
    max_mutations_per_minute: int,
    allowed_capabilities: tuple[str, ...],
    denied_capabilities: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], OperationRiskClass]:
    ceiling = validate_agent_policy_risk_ceiling(risk_ceiling)
    if isinstance(max_mutations_per_minute, bool) or max_mutations_per_minute < 1:
        raise ValueError("max_mutations_per_minute must be a positive integer")
    allowed = validate_agent_policy_capabilities(allowed_capabilities)
    denied = validate_agent_policy_capabilities(denied_capabilities)
    overlap = set(allowed) & set(denied)
    if overlap:
        raise ValueError(
            f"allowed_capabilities and denied_capabilities must not overlap: {sorted(overlap)}"
        )
    return allowed, denied, ceiling


def build_agent_policy(
    *,
    agent_principal_id: UUID,
    allowed_capabilities: tuple[str, ...],
    denied_capabilities: tuple[str, ...],
    risk_ceiling: OperationRiskClass,
    max_mutations_per_minute: int,
    policy_revision: int,
    provenance_reference: str,
) -> AgentPolicy:
    allowed, denied, ceiling = validate_agent_policy_rule_set(
        risk_ceiling=risk_ceiling,
        max_mutations_per_minute=max_mutations_per_minute,
        allowed_capabilities=allowed_capabilities,
        denied_capabilities=denied_capabilities,
    )
    if isinstance(policy_revision, bool) or policy_revision < 1:
        raise ValueError("policy_revision must be a positive integer")
    return AgentPolicy(
        agent_principal_id=agent_principal_id,
        allowed_capabilities=allowed,
        denied_capabilities=denied,
        risk_ceiling=ceiling,
        max_mutations_per_minute=max_mutations_per_minute,
        policy_revision=policy_revision,
        provenance_reference=provenance_reference,
    )
