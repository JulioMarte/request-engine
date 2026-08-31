from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
)
from request_engine.modules.booking.application.errors import ReservationNotFound
from request_engine.modules.booking.contracts.arrival_estimates import ArrivalEstimateSource


async def lock_reservation(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, status, subject_party_id, revision,
                           upper(during) AS end_at
                    FROM request_engine.reservations
                    WHERE organization_id = :organization_id AND id = :reservation_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReservationNotFound(reservation_id)
    return row


async def supersede_and_insert(
    session: AsyncSession,
    command: RecordArrivalEstimateCommand,
    source_kind: ArrivalEstimateSource,
) -> RowMapping:
    await session.execute(
        text(
            """
            UPDATE request_engine.reservation_arrival_estimates
            SET superseded_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND reservation_id = :reservation_id
              AND superseded_at IS NULL
            """
        ),
        {
            "organization_id": command.organization_id,
            "reservation_id": command.reservation_id,
        },
    )
    return (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.reservation_arrival_estimates
                        (organization_id, reservation_id, estimated_arrival_at, source_kind,
                         asserted_by_principal_id)
                    VALUES
                        (:organization_id, :reservation_id, :estimated_arrival_at, :source_kind,
                         :principal_id)
                    RETURNING id, asserted_at
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "reservation_id": command.reservation_id,
                    "estimated_arrival_at": command.estimated_arrival_at,
                    "source_kind": source_kind.value,
                    "principal_id": command.principal_id,
                },
            )
        )
        .mappings()
        .one()
    )


async def advance_reservation_revision(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.reservations
                    SET revision = revision + 1, updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id AND id = :reservation_id
                    RETURNING revision
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        ).scalar_one(),
    )


def estimate_audit_details(
    command: RecordArrivalEstimateCommand,
    estimate_id: UUID,
    source_kind: ArrivalEstimateSource,
) -> dict[str, object]:
    return {
        "estimate_id": str(estimate_id),
        "source_kind": source_kind.value,
        "expected_revision": command.expected_revision,
    }


def estimate_outbox_payload(
    command: RecordArrivalEstimateCommand,
    estimate_id: UUID,
    source_kind: ArrivalEstimateSource,
) -> dict[str, object]:
    return {
        "reservation_id": str(command.reservation_id),
        "estimate_id": str(estimate_id),
        "estimated_arrival_at": command.estimated_arrival_at.isoformat(),
        "source_kind": source_kind.value,
    }
