from dataclasses import dataclass
from uuid import UUID

REMINDERS_MANAGE_SCOPE = "reminders.manage"
REMINDERS_SUBJECT_OVERRIDE = "reminders.subject_override"


@dataclass(frozen=True, slots=True)
class ReminderSubjectEvidence:
    mode: str
    scope_key: str
    representation_id: UUID | None = None
    representation_kind: str | None = None

    def audit_details(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "scope_key": self.scope_key,
            "representation_id": (
                str(self.representation_id) if self.representation_id is not None else None
            ),
            "representation_kind": self.representation_kind,
        }
