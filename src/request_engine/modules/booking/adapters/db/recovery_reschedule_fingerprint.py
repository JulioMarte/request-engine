from datetime import datetime

from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.platform.idempotency.postgres import command_fingerprint


def recovery_fingerprint(
    request: RecoveryRescheduleRequest,
    *,
    start_at: datetime,
    source_observed_at: datetime,
    source_horizon_end: datetime,
) -> str:
    source_commitments = [
        {
            "reservation_id": str(item.reservation_id),
            "revision": item.revision,
            "starts_at": item.starts_at,
            "ends_at": item.ends_at,
        }
        for item in request.expected_source_commitments
    ]
    resources = [
        {
            "requirement_id": str(choice.requirement_id),
            "resource_id": str(choice.resource_id),
        }
        for choice in sorted(
            request.resources,
            key=lambda item: (str(item.requirement_id), str(item.resource_id)),
        )
    ]
    payload: dict[str, object] = {
        "reservation_id": request.reservation_id,
        "expected_revision": request.expected_revision,
        "start_at": start_at,
        "location_id": request.location_id,
        "source_service_queue_id": request.source_service_queue_id,
        "expected_recovery_source_revision": request.expected_recovery_source_revision,
        "source_resource_id": request.source_resource_id,
        "expected_source_resource_availability_revision": (
            request.expected_source_resource_availability_revision
        ),
        "source_location_id": request.source_location_id,
        "expected_source_location_operational_revision": (
            request.expected_source_location_operational_revision
        ),
        "source_observed_at": source_observed_at,
        "source_horizon_end": source_horizon_end,
        "source_commitments": source_commitments,
        "resources": resources,
    }
    return command_fingerprint("booking.reschedule_reservation.recovery.v1", payload)
