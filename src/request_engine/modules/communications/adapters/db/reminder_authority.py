from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.application.errors import (
    ReminderSubjectAuthorityRequired,
)

REMINDER_MANAGE_SCOPE = "reminders.manage"


@dataclass(frozen=True, slots=True)
class ReminderAuthorityEvidence:
    mode: str
    scope_key: str
    representation_id: UUID | None = None
    authority_kind: str | None = None

    def audit_details(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "scope_key": self.scope_key,
            "representation_id": (
                str(self.representation_id) if self.representation_id is not None else None
            ),
            "authority_kind": self.authority_kind,
        }


async def require_reminder_subject_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    subject_party_id: UUID,
    allow_operator_override: bool,
) -> ReminderAuthorityEvidence:
    """Lock exact-scope Party authority inside a ReminderPlan mutation transaction."""

    if allow_operator_override:
        return ReminderAuthorityEvidence(mode="operator", scope_key=REMINDER_MANAGE_SCOPE)

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT representation_id, authority_kind
                    FROM request_engine.lock_current_party_authority(
                        :organization_id,
                        :principal_id,
                        :subject_party_id,
                        :scope_key
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "subject_party_id": subject_party_id,
                    "scope_key": REMINDER_MANAGE_SCOPE,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReminderSubjectAuthorityRequired(subject_party_id, REMINDER_MANAGE_SCOPE)

    return ReminderAuthorityEvidence(
        mode="representation",
        scope_key=REMINDER_MANAGE_SCOPE,
        representation_id=row["representation_id"],
        authority_kind=str(row["authority_kind"]),
    )
