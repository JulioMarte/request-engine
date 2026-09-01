import pytest

from request_engine.modules.communications.domain.errors import DeliveryConfigurationError
from request_engine.modules.communications.domain.escalation_policy import (
    DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY,
    DEFAULT_MAX_ESCALATIONS_PER_TASK,
    parse_escalation_guards,
)


def test_escalation_guards_default_to_closed_policy_bounds() -> None:
    guards = parse_escalation_guards({"channels": ["whatsapp", "sms"]})

    assert guards.max_escalations_per_task == DEFAULT_MAX_ESCALATIONS_PER_TASK
    assert guards.max_contacts_per_subject_per_day == DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY


def test_escalation_guards_accept_tenant_bounds_within_range() -> None:
    guards = parse_escalation_guards(
        {"max_escalations_per_task": 1, "max_contacts_per_subject_per_day": 3}
    )

    assert guards.max_escalations_per_task == 1
    assert guards.max_contacts_per_subject_per_day == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_escalations_per_task", 6),
        ("max_escalations_per_task", -1),
        ("max_contacts_per_subject_per_day", 0),
        ("max_contacts_per_subject_per_day", 51),
        ("max_escalations_per_task", True),
        ("max_contacts_per_subject_per_day", "3"),
    ],
)
def test_escalation_guards_reject_out_of_bounds_values(field: str, value: object) -> None:
    with pytest.raises(DeliveryConfigurationError):
        parse_escalation_guards({field: value})
