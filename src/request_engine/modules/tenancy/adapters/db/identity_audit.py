from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.commands.identity_audit import (
    IdentityAuditDetails,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.security.context import ActorContext


async def append_identity_audit(
    session: AsyncSession,
    *,
    actor: ActorContext,
    command_name: str,
    aggregate_id: UUID,
    idempotency_id: UUID,
    details: IdentityAuditDetails,
) -> None:
    """Append one typed tenant-identity audit row; aggregate and subject stay aligned."""

    await append_audit(
        session,
        organization_id=actor.organization_id,
        principal_id=actor.principal_id,
        command_name=command_name,
        aggregate_kind=details.subject_kind.value,
        aggregate_id=aggregate_id,
        idempotency_id=idempotency_id,
        details=details.to_details(),
    )
