"""Escalation guard parsing from ``channel_policy`` (docs/v3/36 section 4).

Guards are closed defaults owned by Request Engine: no trigger DSL, no
tenant-configurable trigger vocabulary. Tenants may only bound the ladder
(``max_escalations_per_task``) and daily contact fatigue
(``max_contacts_per_subject_per_day``); everything else is fixed policy.
"""

from dataclasses import dataclass

from request_engine.modules.communications.domain.errors import DeliveryConfigurationError

DEFAULT_MAX_ESCALATIONS_PER_TASK = 2
DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY = 5


@dataclass(frozen=True, slots=True)
class EscalationGuards:
    max_escalations_per_task: int
    max_contacts_per_subject_per_day: int


def parse_escalation_guards(value: dict[str, object]) -> EscalationGuards:
    return EscalationGuards(
        max_escalations_per_task=_bounded_int(
            value.get("max_escalations_per_task", DEFAULT_MAX_ESCALATIONS_PER_TASK),
            field="channel_policy.max_escalations_per_task",
            low=0,
            high=5,
        ),
        max_contacts_per_subject_per_day=_bounded_int(
            value.get(
                "max_contacts_per_subject_per_day",
                DEFAULT_MAX_CONTACTS_PER_SUBJECT_PER_DAY,
            ),
            field="channel_policy.max_contacts_per_subject_per_day",
            low=1,
            high=50,
        ),
    )


def _bounded_int(value: object, *, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or value > high:
        raise DeliveryConfigurationError(f"{field} must be between {low} and {high}")
    return value
