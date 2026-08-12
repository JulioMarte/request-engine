import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append_outbox(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    payload: dict[str, object],
    schema_version: int = 1,
) -> None:
    """Append one after-commit integration fact inside the authoritative transaction."""

    await session.execute(
        text(
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id,
                event_type,
                schema_version,
                aggregate_kind,
                aggregate_id,
                payload
            ) VALUES (
                :organization_id,
                :event_type,
                :schema_version,
                :aggregate_kind,
                :aggregate_id,
                CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "event_type": event_type,
            "schema_version": schema_version,
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "payload": json.dumps(payload, default=str, separators=(",", ":")),
        },
    )
