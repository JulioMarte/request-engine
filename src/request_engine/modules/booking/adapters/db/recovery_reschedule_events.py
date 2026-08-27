from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.outbox.postgres import append_outbox


async def append_recovery_reschedule_events(session: AsyncSession, *, request: RecoveryRescheduleRequest, reservation_row: RowMapping, subject_party_id: UUID, authority_details: dict[str, object], idempotency_id: UUID, start_at: datetime, end_at: datetime, source_observed_at: datetime, source_horizon_end: datetime) -> None:
    old_location_id = cast(UUID | None, reservation_row["location_id"])
    old_start_at = cast(datetime, reservation_row["start_at"])
    old_end_at = cast(datetime, reservation_row["end_at"])
    await append_audit(session, organization_id=request.organization_id, principal_id=request.principal_id, command_name="booking.reschedule_reservation", aggregate_kind="Reservation", aggregate_id=request.reservation_id, idempotency_id=idempotency_id, details={
        "subject_party_id": str(subject_party_id), "subject_authority": authority_details, "expected_revision": request.expected_revision, "recovery_guarded": True,
        "source_resource_id": str(request.source_resource_id), "source_resource_availability_revision": request.expected_source_resource_availability_revision,
        "source_location_id": str(request.source_location_id), "source_location_operational_revision": request.expected_source_location_operational_revision,
        "source_observed_at": source_observed_at.isoformat(), "source_horizon_end": source_horizon_end.isoformat(),
        "old_location_id": str(old_location_id) if old_location_id else None, "new_location_id": str(request.location_id) if request.location_id else None,
        "old_start_at": old_start_at.isoformat(), "old_end_at": old_end_at.isoformat(), "new_start_at": start_at.isoformat(), "new_end_at": end_at.isoformat(),
    })
    await append_outbox(session, organization_id=request.organization_id, event_type="reservation.rescheduled.v1", aggregate_kind="Reservation", aggregate_id=request.reservation_id, payload={
        "reservation_id": str(request.reservation_id), "old_location_id": str(old_location_id) if old_location_id else None,
        "old_start_at": old_start_at.isoformat(), "old_end_at": old_end_at.isoformat(), "start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "recovery_guarded": True,
    })
