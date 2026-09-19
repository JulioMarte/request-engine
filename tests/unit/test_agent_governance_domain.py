import pytest

from request_engine.modules.tenancy.domain.agent_governance import (
    AGENT_ASSIGNABLE_AUTHORITY_PLANES,
    AGENT_PROFILE_TRANSITIONS,
    AgentOperatingMode,
    AgentProfileStatus,
    require_agent_profile_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentProfileStatus.PENDING, AgentProfileStatus.ACTIVE),
        (AgentProfileStatus.PENDING, AgentProfileStatus.REVOKED),
        (AgentProfileStatus.ACTIVE, AgentProfileStatus.SUSPENDED),
        (AgentProfileStatus.ACTIVE, AgentProfileStatus.REVOKED),
        (AgentProfileStatus.SUSPENDED, AgentProfileStatus.ACTIVE),
        (AgentProfileStatus.SUSPENDED, AgentProfileStatus.REVOKED),
    ],
)
def test_legal_agent_profile_transitions_are_accepted(
    current: AgentProfileStatus,
    target: AgentProfileStatus,
) -> None:
    require_agent_profile_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentProfileStatus.PENDING, AgentProfileStatus.SUSPENDED),
        (AgentProfileStatus.PENDING, AgentProfileStatus.PENDING),
        (AgentProfileStatus.ACTIVE, AgentProfileStatus.PENDING),
        (AgentProfileStatus.ACTIVE, AgentProfileStatus.ACTIVE),
        (AgentProfileStatus.SUSPENDED, AgentProfileStatus.PENDING),
        (AgentProfileStatus.SUSPENDED, AgentProfileStatus.SUSPENDED),
        (AgentProfileStatus.REVOKED, AgentProfileStatus.ACTIVE),
        (AgentProfileStatus.REVOKED, AgentProfileStatus.SUSPENDED),
        (AgentProfileStatus.REVOKED, AgentProfileStatus.PENDING),
        (AgentProfileStatus.REVOKED, AgentProfileStatus.REVOKED),
    ],
)
def test_illegal_agent_profile_transitions_are_rejected(
    current: AgentProfileStatus,
    target: AgentProfileStatus,
) -> None:
    with pytest.raises(ValueError, match="cannot transition"):
        require_agent_profile_transition(current, target)


def test_revoked_agent_profile_is_terminal() -> None:
    assert AGENT_PROFILE_TRANSITIONS[AgentProfileStatus.REVOKED] == frozenset()


def test_agent_operating_mode_values() -> None:
    assert AgentOperatingMode.AUTONOMOUS.value == "autonomous"
    assert AgentOperatingMode.ASSISTED.value == "assisted"


def test_agents_may_only_hold_operational_authority() -> None:
    assert frozenset({"operational"}) == AGENT_ASSIGNABLE_AUTHORITY_PLANES
