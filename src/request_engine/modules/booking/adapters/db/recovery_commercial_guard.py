from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.recovery import RecoveryTargetUnavailable
from request_engine.modules.booking.domain.contextual_supply import ResolvedBookingTerms


@dataclass(frozen=True, slots=True)
class RecoveryCommercialCommitment:
    amount: Decimal
    currency: str
    planned_duration_minutes: int


async def require_preserved_commercial_commitment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    resolved: ResolvedBookingTerms,
) -> None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT amount, currency, planned_duration_minutes
                    FROM request_engine.reservation_commercial_commitments
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RecoveryTargetUnavailable(
            "contextual source Reservation is missing its commercial commitment"
        )
    committed = RecoveryCommercialCommitment(
        amount=cast(Decimal, row["amount"]),
        currency=cast(str, row["currency"]),
        planned_duration_minutes=cast(int, row["planned_duration_minutes"]),
    )
    if (
        committed.amount != resolved.amount
        or committed.currency != resolved.currency
        or committed.planned_duration_minutes != resolved.planned_duration_minutes
    ):
        raise RecoveryTargetUnavailable(
            "recovery target would change committed commercial semantics"
        )
