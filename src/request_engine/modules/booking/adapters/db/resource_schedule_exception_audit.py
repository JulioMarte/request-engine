from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.security.operational_authority import OperationalAuthority


async def append_resource_exception_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    exception_id: UUID,
    resource_id: UUID,
    exception_kind: str,
    idempotency_id: UUID,
    authority: OperationalAuthority,
    previous_revision: int,
    new_revision: int,
) -> None:
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name="booking.set_resource_schedule_exception",
        aggregate_kind="ResourceScheduleException",
        aggregate_id=exception_id,
        idempotency_id=idempotency_id,
        details={
            "authority": authority.audit_details(),
            "resource_id": str(resource_id),
            "exception_kind": exception_kind,
            "previous_resource_availability_revision": previous_revision,
            "new_resource_availability_revision": new_revision,
        },
    )
