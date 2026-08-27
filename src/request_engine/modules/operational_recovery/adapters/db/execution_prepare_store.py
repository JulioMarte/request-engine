import json
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.execution_codec import (
    execution_from_row,
)
from request_engine.modules.operational_recovery.adapters.db.execution_conflict_store import (
    find_execution_conflict,
)
from request_engine.modules.operational_recovery.adapters.db.target_codec import target_to_json
from request_engine.modules.operational_recovery.application.ports import RecoveryExecutionRecord
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_INSERT = """
    INSERT INTO request_engine.operational_recovery_executions (
        organization_id, proposal_id, reservation_id, executed_by_principal_id,
        idempotency_key, command_fingerprint, source_fingerprint, proposal_fingerprint,
        original_reservation_revision, target, notification_requested
    ) VALUES (
        :organization_id, :proposal_id, :reservation_id, :principal_id,
        :idempotency_key, :command_fingerprint, :source_fingerprint,
        :proposal_fingerprint, :original_revision, CAST(:target AS jsonb),
        :notification_requested
    ) ON CONFLICT DO NOTHING RETURNING *
"""


async def prepare_execution(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    command_fingerprint: str,
    proposal: RescheduleProposal,
    reservation_id: UUID,
    notification_requested: bool,
) -> RecoveryExecutionRecord:
    affected = next(item for item in proposal.affected if item.reservation_id == reservation_id)
    if affected.target is None:
        raise RuntimeError("cannot prepare recovery execution without a target")
    params = {
        "organization_id": organization_id,
        "proposal_id": proposal.id,
        "reservation_id": reservation_id,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "command_fingerprint": command_fingerprint,
        "source_fingerprint": proposal.source_fingerprint,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "original_revision": affected.expected_revision,
        "target": json.dumps(target_to_json(affected.target), separators=(",", ":")),
        "notification_requested": notification_requested,
    }
    async with tenant_transaction(factory, organization_id) as session:
        row = (await session.execute(text(_INSERT), params)).mappings().one_or_none()
        created = row is not None
        if row is None:
            row = await find_execution_conflict(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                idempotency_key=idempotency_key,
                proposal_id=proposal.id,
                reservation_id=reservation_id,
            )
    return RecoveryExecutionRecord(
        execution=execution_from_row(row),
        command_fingerprint=cast(str, row["command_fingerprint"]),
        created=created,
    )
