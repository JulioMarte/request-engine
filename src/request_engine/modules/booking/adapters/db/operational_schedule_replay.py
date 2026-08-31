from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionReplay,
)
from request_engine.platform.idempotency.replay import get_completed_idempotency_result

_CAPABILITY = "booking.set_resource_location_schedule_exception"


async def load_extension_replay(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
) -> OperationalAssignmentExtensionReplay | None:
    result = await get_completed_idempotency_result(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        capability=_CAPABILITY,
        idempotency_key=idempotency_key,
    )
    if result is None:
        return None
    details = (
        await session.execute(
            text(
                """
                SELECT a.details
                FROM request_engine.audit_records a
                JOIN request_engine.idempotency_records i
                  ON i.organization_id = a.organization_id
                 AND i.id = a.idempotency_record_id
                WHERE i.organization_id = :organization_id
                  AND i.principal_id = :principal_id
                  AND i.capability = :capability
                  AND i.idempotency_key = :idempotency_key
                  AND a.command_name = :capability
                ORDER BY a.created_at DESC
                LIMIT 1
                """
            ),
            {
                "organization_id": organization_id,
                "principal_id": principal_id,
                "capability": _CAPABILITY,
                "idempotency_key": idempotency_key,
            },
        )
    ).scalar_one_or_none()
    raw_exception = result.get("exception")
    if not isinstance(raw_exception, dict) or not isinstance(details, dict):
        raise RuntimeError("completed Booking extension is missing replay provenance")
    exception = cast(dict[str, object], raw_exception)
    audit_details = cast(dict[str, object], details)
    if exception.get("exception_kind") != "available" or exception.get("active") is not True:
        return None
    reason = exception.get("reason")
    expected_revision = audit_details.get("previous_resource_availability_revision")
    if not isinstance(reason, str) or not isinstance(expected_revision, int):
        raise RuntimeError("completed Booking extension has invalid replay provenance")
    return OperationalAssignmentExtensionReplay(
        assignment_id=UUID(str(exception["assignment_id"])),
        start_at=datetime.fromisoformat(str(exception["start_at"])),
        end_at=datetime.fromisoformat(str(exception["end_at"])),
        expected_resource_availability_revision=expected_revision,
        reason=reason,
    )
