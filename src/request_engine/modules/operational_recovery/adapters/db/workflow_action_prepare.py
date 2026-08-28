import json
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import action_from_row
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionConflict,
    RecoveryActionKind,
)


async def prepare_action_row(
    session: AsyncSession,
    *,
    organization_id: UUID,
    incident_id: UUID,
    principal_id: UUID,
    action_kind: RecoveryActionKind,
    idempotency_key: str,
    command_fingerprint: str,
    expected_source_revision: int,
    payload: Mapping[str, object],
) -> tuple[RecoveryAction, bool]:
    params = {
        "organization_id": organization_id,
        "incident_id": incident_id,
        "action_kind": action_kind.value,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "command_fingerprint": command_fingerprint,
        "expected_source_revision": expected_source_revision,
        "payload": json.dumps(payload, default=str, sort_keys=True),
    }
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.operational_recovery_actions (
                        organization_id, incident_id, action_kind, principal_id,
                        idempotency_key, command_fingerprint,
                        expected_source_revision, payload
                    ) VALUES (
                        :organization_id, :incident_id, :action_kind, :principal_id,
                        :idempotency_key, :command_fingerprint,
                        :expected_source_revision, CAST(:payload AS jsonb)
                    )
                    ON CONFLICT (organization_id, principal_id, idempotency_key) DO NOTHING
                    RETURNING *
                    """
                ),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        return action_from_row(row), True
    existing = (
        (
            await session.execute(
                text(
                    """
                    SELECT * FROM request_engine.operational_recovery_actions
                    WHERE organization_id = :organization_id
                      AND principal_id = :principal_id
                      AND idempotency_key = :idempotency_key
                    FOR UPDATE
                    """
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    action = action_from_row(existing)
    if action.command_fingerprint != command_fingerprint:
        raise RecoveryActionConflict("idempotency key was reused with a different command")
    return action, False
