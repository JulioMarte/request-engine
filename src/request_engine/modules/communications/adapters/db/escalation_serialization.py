"""Subject-level serialization for the escalation step (docs/v3/36 section 4).

The contact fatigue guard is a count-then-act decision keyed on the recipient
party but executed per lineage; without serialization two concurrent
escalations for the same subject on different lineages can both observe a
count below the daily limit and both create a child contact.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def serialize_subject_contacts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    recipient_party_id: UUID,
) -> None:
    """Serialize concurrent escalations for one recipient subject.

    Takes a transaction-scoped advisory lock keyed on
    ``(organization_id, recipient_party_id)`` before the fatigue count, so
    concurrent escalations for the same subject run their count-then-act
    sequentially and the daily outbound-contact guard cannot be exceeded by a
    race across lineages. The lock releases with the caller's transaction.
    """

    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:organization_id || ':' || :recipient_party_id, 0))"
        ),
        {"organization_id": str(organization_id), "recipient_party_id": str(recipient_party_id)},
    )
