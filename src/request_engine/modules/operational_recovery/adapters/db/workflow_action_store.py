import json
from typing import Mapping, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import action_from_row
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionConflict,
    RecoveryActionKind,
    RecoveryActionStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRecoveryActionStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare_action(
        self,
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
        async with tenant_transaction(self._session_factory, organization_id) as session:
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
                            ON CONFLICT (organization_id, principal_id, idempotency_key)
                            DO NOTHING
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "incident_id": incident_id,
                            "action_kind": action_kind.value,
                            "principal_id": principal_id,
                            "idempotency_key": idempotency_key,
                            "command_fingerprint": command_fingerprint,
                            "expected_source_revision": expected_source_revision,
                            "payload": json.dumps(payload, default=str, sort_keys=True),
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                return action_from_row(cast(RowMapping, row)), True
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
                        {
                            "organization_id": organization_id,
                            "principal_id": principal_id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                )
                .mappings()
                .one()
            )
            action = action_from_row(cast(RowMapping, existing))
            if action.command_fingerprint != command_fingerprint:
                raise RecoveryActionConflict("idempotency key was reused with a different command")
            return action, False

    async def transition_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
    ) -> RecoveryAction:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.operational_recovery_actions
                            SET status = :status,
                                owner_steps = CASE WHEN CAST(:owner_steps AS jsonb) IS NULL
                                  THEN owner_steps ELSE CAST(:owner_steps AS jsonb) END,
                                failure_code = :failure_code,
                                started_at = CASE
                                  WHEN :status = 'running' AND started_at IS NULL
                                  THEN clock_timestamp() ELSE started_at END,
                                completed_at = CASE
                                  WHEN :status IN ('succeeded','rejected')
                                  THEN clock_timestamp() ELSE completed_at END
                            WHERE organization_id = :organization_id AND id = :action_id
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "action_id": action_id,
                            "status": status.value,
                            "owner_steps": (
                                None
                                if owner_steps is None
                                else json.dumps(owner_steps, default=str, sort_keys=True)
                            ),
                            "failure_code": failure_code,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return action_from_row(cast(RowMapping, row))
