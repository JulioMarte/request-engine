from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.application.errors import ReminderSubjectAuthorityRequired
from request_engine.modules.communications.application.subject_policy import ReminderSubjectEvidence


async def require_reminder_subject_policy(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    subject_party_id: UUID,
    scope_key: str,
    allow_operator_override: bool,
) -> ReminderSubjectEvidence:
    if allow_operator_override:
        return ReminderSubjectEvidence(mode="operator", scope_key=scope_key)

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
                    "scope_key": scope_key,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReminderSubjectAuthorityRequired(subject_party_id, scope_key)

    return ReminderSubjectEvidence(
        mode="representation",
        scope_key=scope_key,
        representation_id=cast(UUID, row["representation_id"]),
        representation_kind=cast(str, row["authority_kind"]),
    )
