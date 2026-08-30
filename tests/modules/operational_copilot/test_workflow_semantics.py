from datetime import UTC, datetime
from uuid import UUID

import pytest

from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendRecoveryDayIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    CopilotPolicyRejected,
    UnsupportedCopilotIntent,
)
from request_engine.modules.operational_copilot.lowering import lower_copilot_intent
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.policy import validate_copilot_intent
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
AUTHORITY = UUID("66666666-6666-6666-6666-666666666666")
INCIDENT = UUID("77777777-7777-7777-7777-777777777777")
ASSIGNMENT = UUID("88888888-8888-8888-8888-888888888888")
CTX = CopilotContext(ORG, PRINCIPAL, "copilot:intake:1")
CTX_AUTHORITY = CopilotContext(ORG, PRINCIPAL, "copilot:extend:1", AUTHORITY)


def test_stop_walk_ins_parses_validates_and_lowers() -> None:
    intent = parse_copilot_intent(
        f"stop walk-ins for incident {INCIDENT} source revision 3 intake revision 5"
    )
    assert intent == SetRecoveryIntakeIntent(INCIDENT, False, 3, 5)
    command = lower_copilot_intent(CTX, validate_copilot_intent(CTX, intent))
    assert isinstance(command, SetRecoveryIntakeCommand)
    assert command.accepting is False
    assert command.organization_id == ORG
    assert command.principal_id == PRINCIPAL
    assert command.idempotency_key == CTX.idempotency_key


def test_reopen_walk_ins_reuses_trusted_identity() -> None:
    intent = parse_copilot_intent(
        f"reopen walk-ins for incident {INCIDENT} source revision 4 intake revision 6"
    )
    assert intent == SetRecoveryIntakeIntent(INCIDENT, True, 4, 6)
    command = lower_copilot_intent(CTX, validate_copilot_intent(CTX, intent))
    assert isinstance(command, SetRecoveryIntakeCommand)
    assert command.accepting is True


def test_extend_day_lowers_with_trusted_authority_party() -> None:
    start = "2026-08-30T17:00:00+00:00"
    end = "2026-08-30T19:00:00+00:00"
    text = (
        f"extend day for incident {INCIDENT} assignment {ASSIGNMENT} "
        f"from {start} to {end} source revision 2 location revision 4 "
        "availability revision 6 reason crowd overflow"
    )
    intent = parse_copilot_intent(text)
    assert intent == ExtendRecoveryDayIntent(
        INCIDENT,
        ASSIGNMENT,
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        2,
        4,
        6,
        "crowd overflow",
    )
    command = lower_copilot_intent(CTX_AUTHORITY, validate_copilot_intent(CTX_AUTHORITY, intent))
    assert isinstance(command, ExtendRecoveryDayCommand)
    assert command.authority_party_id == AUTHORITY
    assert command.reason == "crowd overflow"


def test_extend_day_requires_trusted_authority_context() -> None:
    intent = ExtendRecoveryDayIntent(
        INCIDENT,
        ASSIGNMENT,
        datetime(2026, 8, 30, 17, 0, tzinfo=UTC),
        datetime(2026, 8, 30, 19, 0, tzinfo=UTC),
        2,
        4,
        6,
        "crowd overflow",
    )
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX, intent)


def test_extend_day_rejects_naive_datetimes_and_inverted_interval() -> None:
    start = datetime(2026, 8, 30, 17, 0)
    end = datetime(2026, 8, 30, 19, 0, tzinfo=UTC)
    naive = ExtendRecoveryDayIntent(INCIDENT, ASSIGNMENT, start, end, 2, 4, 6, "reason")
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX_AUTHORITY, naive)
    aware_start = start.replace(tzinfo=UTC)
    inverted = ExtendRecoveryDayIntent(INCIDENT, ASSIGNMENT, end, aware_start, 2, 4, 6, "reason")
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX_AUTHORITY, inverted)


def test_negative_revisions_fail_policy() -> None:
    intent = SetRecoveryIntakeIntent(INCIDENT, False, -1, 5)
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX, intent)


def test_conflicting_walk_in_phrases_fail_closed() -> None:
    text = (
        f"stop walk-ins for incident {INCIDENT} source revision 1 intake revision 1 "
        f"reopen walk-ins for incident {INCIDENT} source revision 2 intake revision 2"
    )
    with pytest.raises(AmbiguousCopilotIntent):
        parse_copilot_intent(text)


def test_names_never_resolve_to_incidents() -> None:
    with pytest.raises(UnsupportedCopilotIntent):
        parse_copilot_intent("stop walk-ins for Dr. A for the rest of the day")
