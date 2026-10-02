"""Atomic closed-purpose address delivery; no unverified Party is manufactured."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.scheduling.store import schedule_action

STAFF_INVITATION_DISPATCH = "dispatch_staff_invitation"
STAFF_INVITATION_MAX_ATTEMPTS = 8


class PostgresStaffInvitationDeliveryRecorder:
    async def status(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        generation: int,
    ) -> str | None:
        return cast(
            str | None,
            (
                await _transaction(transaction).execute(
                    text("""
                        SELECT status FROM request_engine.staff_invitation_deliveries
                        WHERE organization_id = :organization_id
                          AND invitation_id = :invitation_id AND generation = :generation
                    """),
                    {
                        "organization_id": organization_id,
                        "invitation_id": invitation_id,
                        "generation": generation,
                    },
                )
            ).scalar_one_or_none(),
        )

    async def record(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
        generation: int,
        destination_address: str,
        secret_reference: str,
        secret_digest: str,
        expires_at: datetime,
    ) -> UUID:
        session = _transaction(transaction)
        values = {
            "organization_id": organization_id,
            "invitation_id": invitation_id,
            "generation": generation,
            "destination_address": destination_address,
            "secret_reference": secret_reference,
            "secret_digest": secret_digest,
            "expires_at": expires_at,
        }
        row = (
            (
                await session.execute(
                    text("""
                    INSERT INTO request_engine.staff_invitation_deliveries (
                        organization_id, invitation_id, generation, destination_address,
                        secret_reference, secret_digest, expires_at
                    ) VALUES (
                        :organization_id, :invitation_id, :generation, :destination_address,
                        :secret_reference, :secret_digest, :expires_at
                    ) ON CONFLICT (organization_id, invitation_id, generation) DO NOTHING
                    RETURNING id, created_at
                """),
                    values,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            row = (
                (
                    await session.execute(
                        text("""
                        SELECT id, created_at, destination_address, secret_reference,
                               secret_digest, expires_at
                        FROM request_engine.staff_invitation_deliveries
                        WHERE organization_id = :organization_id
                          AND invitation_id = :invitation_id AND generation = :generation
                        FOR UPDATE
                    """),
                        values,
                    )
                )
                .mappings()
                .one()
            )
            fields = ("destination_address", "secret_reference", "secret_digest", "expires_at")
            if any(row[field] != values[field] for field in fields):
                raise ValueError("staff invitation delivery intent conflicts with generation")
        delivery_id = cast(UUID, row["id"])
        await schedule_action(
            session,
            organization_id=organization_id,
            owner_module="communications",
            action_type=STAFF_INVITATION_DISPATCH,
            action_version=1,
            subject_kind="StaffInvitationDelivery",
            subject_id=delivery_id,
            dedupe_key=f"staff-invitation-delivery:{delivery_id}:v1",
            execute_at=cast(datetime, row["created_at"]),
            payload={"delivery_id": str(delivery_id)},
            max_attempts=STAFF_INVITATION_MAX_ATTEMPTS,
        )
        return delivery_id

    async def cancel(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
    ) -> None:
        # Delivery row is the shared cancellation/prepare serialization root.
        # Do not lock ScheduledAction here: workers lock action before delivery.
        await _transaction(transaction).execute(
            text("""
                UPDATE request_engine.staff_invitation_deliveries
                SET status = 'cancelled', updated_at = clock_timestamp()
                WHERE organization_id = :organization_id AND invitation_id = :invitation_id
                  AND status IN ('pending', 'attempting', 'unknown')
            """),
            {"organization_id": organization_id, "invitation_id": invitation_id},
        )


def _transaction(transaction: object) -> AsyncSession:
    if not isinstance(transaction, AsyncSession) or not transaction.in_transaction():
        raise TypeError("staff invitation delivery requires an active AsyncSession transaction")
    return transaction
