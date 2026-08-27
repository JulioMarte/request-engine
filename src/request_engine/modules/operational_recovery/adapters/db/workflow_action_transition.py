import json
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import action_from_row
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
)


async def transition_action_row(
    session: AsyncSession,
    *,
    organization_id: UUID,
    action_id: UUID,
    status: RecoveryActionStatus,
    owner_steps: Mapping[str, object] | None,
    failure_code: str | None,
) -> RecoveryAction:
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
