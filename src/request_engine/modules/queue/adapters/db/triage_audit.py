import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append_triage_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    command_name: str,
    entry_id: UUID,
    details: dict[str, object],
    idempotency_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.audit_records (
                organization_id, actor_principal_id, command_name,
                aggregate_kind, aggregate_id, idempotency_record_id, details
            ) VALUES (
                :organization_id, :principal_id, :command_name,
                'QueueEntry', :entry_id, :idempotency_id, CAST(:details AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "principal_id": principal_id,
            "command_name": command_name,
            "entry_id": entry_id,
            "idempotency_id": idempotency_id,
            "details": json.dumps(details, separators=(",", ":")),
        },
    )
