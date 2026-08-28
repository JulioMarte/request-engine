from typing import cast

from request_engine.modules.booking.adapters.db.recovery_reschedule_events import (
    append_recovery_reschedule_events,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_fingerprint import (
    recovery_fingerprint,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_mutation import (
    replace_reservation_commitment,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_prepare import (
    prepare_recovery,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    read_reservation,
    reservation_from_json,
    reservation_to_json,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.booking.domain.availability import require_aware_utc
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)


async def execute_recovery_reschedule(
    factory: SessionFactory,
    request: RecoveryRescheduleRequest,
) -> Reservation:
    start_at = require_aware_utc(request.start_at, "start_at")
    observed_at = require_aware_utc(request.source_observed_at, "source_observed_at")
    horizon_end = require_aware_utc(request.source_horizon_end, "source_horizon_end")
    if horizon_end <= observed_at:
        raise ValueError("source_horizon_end must be after source_observed_at")
    fingerprint = recovery_fingerprint(
        request,
        start_at=start_at,
        source_observed_at=observed_at,
        source_horizon_end=horizon_end,
    )
    async with tenant_transaction(factory, request.organization_id) as session:
        idempotency_id, replay = await acquire_idempotency(
            session,
            organization_id=request.organization_id,
            principal_id=request.principal_id,
            capability="booking.reschedule_reservation",
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            payload = cast(dict[str, object], replay["reservation"])
            return reservation_from_json(payload)
        prepared = await prepare_recovery(
            session,
            request=request,
            start_at=start_at,
            source_observed_at=observed_at,
            source_horizon_end=horizon_end,
        )
        await replace_reservation_commitment(
            session,
            request=request,
            inputs=prepared.mutation,
        )
        await append_recovery_reschedule_events(
            session,
            request=request,
            reservation_row=prepared.reservation_row,
            subject_party_id=prepared.subject_party_id,
            authority_details=prepared.authority_details,
            idempotency_id=idempotency_id,
            start_at=start_at,
            end_at=prepared.mutation.end_at,
            source_observed_at=observed_at,
            source_horizon_end=horizon_end,
        )
        reservation = await read_reservation(
            session,
            request.organization_id,
            request.reservation_id,
        )
        await complete_idempotency(
            session,
            idempotency_id,
            {"reservation": reservation_to_json(reservation)},
        )
        return reservation
