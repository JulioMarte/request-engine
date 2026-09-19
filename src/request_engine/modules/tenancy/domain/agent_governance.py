from enum import StrEnum


class AgentProfileStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AgentOperatingMode(StrEnum):
    AUTONOMOUS = "autonomous"
    ASSISTED = "assisted"


AGENT_PROFILE_TRANSITIONS: dict[AgentProfileStatus, frozenset[AgentProfileStatus]] = {
    AgentProfileStatus.PENDING: frozenset({AgentProfileStatus.ACTIVE, AgentProfileStatus.REVOKED}),
    AgentProfileStatus.ACTIVE: frozenset(
        {AgentProfileStatus.SUSPENDED, AgentProfileStatus.REVOKED}
    ),
    AgentProfileStatus.SUSPENDED: frozenset(
        {AgentProfileStatus.ACTIVE, AgentProfileStatus.REVOKED}
    ),
    AgentProfileStatus.REVOKED: frozenset(),
}


def require_agent_profile_transition(
    current: AgentProfileStatus,
    target: AgentProfileStatus,
) -> None:
    if target not in AGENT_PROFILE_TRANSITIONS[current]:
        raise ValueError(f"agent profile cannot transition from {current.value} to {target.value}")


AGENT_ASSIGNABLE_AUTHORITY_PLANES: frozenset[str] = frozenset({"operational"})
