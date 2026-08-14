import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresSlotOfferNotificationIntent:
    """Communications-owned persistence adapter for queue notification intent."""

    async def create_slot_offer_notification(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        recipient_party_id: UUID,
        slot_offer_id: UUID,
        slot_opportunity_id: UUID,
        start_at: datetime,
        end_at: datetime,
        expires_at: datetime,
    ) -> UUID:
        session = _session(transaction)
        render_context = {
            "slot_offer_id": str(slot_offer_id),
            "slot_opportunity_id": str(slot_opportunity_id),
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        task_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.communication_tasks (
                        organization_id,
                        recipient_party_id,
                        purpose,
                        source_kind,
                        source_id,
                        channel_policy,
                        template_key,
                        template_version,
                        render_context,
                        dedupe_key,
                        expires_at
                    ) VALUES (
                        :organization_id,
                        :recipient_party_id,
                        'slot_offer_available',
                        'SlotOffer',
                        :slot_offer_id,
                        '{"strategy":"party_default"}'::jsonb,
                        'slot_offer_available',
                        1,
                        CAST(:render_context AS jsonb),
                        :dedupe_key,
                        :expires_at
                    )
                    ON CONFLICT (organization_id, dedupe_key)
                    WHERE dedupe_key IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "recipient_party_id": recipient_party_id,
                    "slot_offer_id": slot_offer_id,
                    "render_context": json.dumps(
                        render_context,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "dedupe_key": f"slot-offer:{slot_offer_id}:available:v1",
                    "expires_at": expires_at,
                },
            )
        ).scalar_one_or_none()
        if task_id is not None:
            return cast(UUID, task_id)

        existing = (
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM request_engine.communication_tasks
                    WHERE organization_id = :organization_id
                      AND dedupe_key = :dedupe_key
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "dedupe_key": f"slot-offer:{slot_offer_id}:available:v1",
                },
            )
        ).scalar_one()
        return cast(UUID, existing)

    async def cancel_slot_offer_notification(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        slot_offer_id: UUID,
    ) -> None:
        session = _session(transaction)
        await session.execute(
            text(
                """
                UPDATE request_engine.communication_tasks
                SET status = 'cancelled',
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND source_kind = 'SlotOffer'
                  AND source_id = :slot_offer_id
                  AND purpose = 'slot_offer_available'
                  AND status = 'pending'
                """
            ),
            {
                "organization_id": organization_id,
                "slot_offer_id": slot_offer_id,
            },
        )


def _session(transaction: object) -> AsyncSession:
    if not isinstance(transaction, AsyncSession):
        raise TypeError("slot-offer notification transaction must be an AsyncSession")
    return transaction
