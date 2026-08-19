import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    command_name: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    details: dict[str, object],
    idempotency_id: UUID,
) -> None:
    """Append one material command audit record inside the caller transaction."""

    await session.execute(
        text(
            """
            INSERT INTO request_engine.audit_records (
                organization_id,
                actor_principal_id,
                command_name,
                aggregate_kind,
                aggregate_id,
                idempotency_record_id,
                correlation_data,
                details
            ) VALUES (
                :organization_id,
                :principal_id,
                :command_name,
                :aggregate_kind,
                :aggregate_id,
                :idempotency_id,
                jsonb_strip_nulls(jsonb_build_object(
                    'correlation_id', NULLIF(
                        current_setting('request_engine.correlation_id', true), ''
                    ),
                    'principal_kind', NULLIF(
                        current_setting('request_engine.principal_kind', true), ''
                    ),
                    'authentication_method', NULLIF(
                        current_setting('request_engine.authentication_method', true), ''
                    ),
                    'credential_id', NULLIF(
                        current_setting('request_engine.credential_id', true), ''
                    )
                )),
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "principal_id": principal_id,
            "command_name": command_name,
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "idempotency_id": idempotency_id,
            "details": json.dumps(details, default=str, separators=(",", ":")),
        },
    )
