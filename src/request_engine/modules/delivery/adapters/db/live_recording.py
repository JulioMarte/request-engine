from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.outbox.postgres import append_outbox


async def record_live_fact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_id: UUID,
    command_name: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict[str, object],
) -> None:
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name=command_name,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        idempotency_id=idempotency_id,
        details=payload,
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type=event_type,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        payload=payload,
    )
