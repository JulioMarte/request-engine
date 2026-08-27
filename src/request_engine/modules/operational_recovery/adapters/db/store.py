import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.operational_recovery.application.ports import (
    RecoveryExecutionRecord,
    RecoveryRepository,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    OperationalNotification,
    RecoveryExecution,
    RecoveryExecutionStatus,
    RecoverySourceCheckpoint,
    RecoveryTarget,
    RescheduleProposal,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRecoveryRepository(RecoveryRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_proposal(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        proposal: RescheduleProposal,
    ) -> RescheduleProposal:
        snapshot = {
            "source_checkpoint": _checkpoint_to_json(proposal.source_checkpoint),
            "affected": [_affected_to_json(item) for item in proposal.affected],
        }
        async with tenant_transaction(self._session_factory, organization_id) as session:
            created_at = cast(
                datetime,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.operational_recovery_proposals (
                                id, organization_id, service_queue_id, resource_id, location_id,
                                created_by_principal_id, observed_at, horizon_end,
                                source_fingerprint, proposal_fingerprint,
                                executable_capacity_seconds, committed_capacity_seconds,
                                shortfall_seconds, snapshot
                            ) VALUES (
                                :id, :organization_id, :service_queue_id, :resource_id,
                                :location_id, :principal_id, :observed_at, :horizon_end,
                                :source_fingerprint, :proposal_fingerprint,
                                :executable_capacity_seconds, :committed_capacity_seconds,
                                :shortfall_seconds, CAST(:snapshot AS jsonb)
                            )
                            RETURNING created_at
                            """
                        ),
                        {
                            "id": proposal.id,
                            "organization_id": organization_id,
                            "service_queue_id": proposal.service_queue_id,
                            "resource_id": proposal.resource_id,
                            "location_id": proposal.location_id,
                            "principal_id": principal_id,
                            "observed_at": proposal.observed_at,
                            "horizon_end": proposal.horizon_end,
                            "source_fingerprint": proposal.source_fingerprint,
                            "proposal_fingerprint": proposal.proposal_fingerprint,
                            "executable_capacity_seconds": proposal.executable_capacity_seconds,
                            "committed_capacity_seconds": proposal.committed_capacity_seconds,
                            "shortfall_seconds": proposal.shortfall_seconds,
                            "snapshot": json.dumps(snapshot, separators=(",", ":")),
                        },
                    )
                ).scalar_one(),
            )
        return _with_created_at(proposal, created_at)

    async def get_proposal(
        self, *, organization_id: UUID, proposal_id: UUID
    ) -> RescheduleProposal | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.operational_recovery_proposals
                            WHERE organization_id = :organization_id
                              AND id = :proposal_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "proposal_id": proposal_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _proposal_from_row(row) if row is not None else None

    async def prepare_execution(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
        reservation_id: UUID,
        notification_requested: bool,
    ) -> RecoveryExecutionRecord:
        affected = _affected(proposal, reservation_id)
        if affected.target is None:
            raise RuntimeError("cannot prepare recovery execution without a target")
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.operational_recovery_executions (
                                organization_id, proposal_id, reservation_id,
                                executed_by_principal_id, idempotency_key,
                                command_fingerprint, source_fingerprint,
                                proposal_fingerprint, original_reservation_revision,
                                target, notification_requested
                            ) VALUES (
                                :organization_id, :proposal_id, :reservation_id,
                                :principal_id, :idempotency_key, :command_fingerprint,
                                :source_fingerprint, :proposal_fingerprint,
                                :original_revision, CAST(:target AS jsonb),
                                :notification_requested
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "proposal_id": proposal.id,
                            "reservation_id": reservation_id,
                            "principal_id": principal_id,
                            "idempotency_key": idempotency_key,
                            "command_fingerprint": command_fingerprint,
                            "source_fingerprint": proposal.source_fingerprint,
                            "proposal_fingerprint": proposal.proposal_fingerprint,
                            "original_revision": affected.expected_revision,
                            "target": json.dumps(
                                _target_to_json(affected.target), separators=(",", ":")
                            ),
                            "notification_requested": notification_requested,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = await _find_execution_conflict(
                    session,
                    organization_id=organization_id,
                    principal_id=principal_id,
                    idempotency_key=idempotency_key,
                    proposal_id=proposal.id,
                    reservation_id=reservation_id,
                )
        return RecoveryExecutionRecord(
            execution=_execution_from_row(row),
            command_fingerprint=cast(str, row["command_fingerprint"]),
        )

    async def succeed_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        resulting_revision: int,
    ) -> RecoveryExecution:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.operational_recovery_executions
                            SET status = 'succeeded',
                                resulting_reservation_revision = :resulting_revision,
                                completed_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND id = :execution_id
                              AND status = 'prepared'
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "execution_id": execution_id,
                            "resulting_revision": resulting_revision,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = await _require_execution(session, organization_id, execution_id)
                if (
                    row["status"] != RecoveryExecutionStatus.SUCCEEDED.value
                    or cast(int | None, row["resulting_reservation_revision"])
                    != resulting_revision
                ):
                    raise RuntimeError("recovery execution cannot transition to succeeded")
        return _execution_from_row(row)

    async def reject_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        failure_code: str,
    ) -> RecoveryExecution:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.operational_recovery_executions
                            SET status = 'rejected',
                                failure_code = :failure_code,
                                completed_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND id = :execution_id
                              AND status = 'prepared'
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "execution_id": execution_id,
                            "failure_code": failure_code,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = await _require_execution(session, organization_id, execution_id)
                if (
                    row["status"] != RecoveryExecutionStatus.REJECTED.value
                    or cast(str | None, row["failure_code"]) != failure_code
                ):
                    raise RuntimeError("recovery execution cannot transition to rejected")
        return _execution_from_row(row)

    async def attach_communication_task(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        communication_task_id: UUID,
    ) -> RecoveryExecution:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.operational_recovery_executions
                            SET communication_task_id = :communication_task_id
                            WHERE organization_id = :organization_id
                              AND id = :execution_id
                              AND status = 'succeeded'
                              AND communication_task_id IS NULL
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "execution_id": execution_id,
                            "communication_task_id": communication_task_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = await _require_execution(session, organization_id, execution_id)
                if cast(UUID | None, row["communication_task_id"]) != communication_task_id:
                    raise RuntimeError(
                        "recovery execution already references another communication task"
                    )
        return _execution_from_row(row)


async def _find_execution_conflict(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    proposal_id: UUID,
    reservation_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.operational_recovery_executions
                    WHERE organization_id = :organization_id
                      AND proposal_id = :proposal_id
                      AND reservation_id = :reservation_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "proposal_id": proposal_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        return row
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.operational_recovery_executions
                    WHERE organization_id = :organization_id
                      AND executed_by_principal_id = :principal_id
                      AND idempotency_key = :idempotency_key
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
        .one_or_none()
    )
    if row is None:
        raise RuntimeError("recovery execution conflict could not be resolved")
    return row


async def _require_execution(
    session: AsyncSession,
    organization_id: UUID,
    execution_id: UUID,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.operational_recovery_executions
                    WHERE organization_id = :organization_id
                      AND id = :execution_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "execution_id": execution_id,
                },
            )
        )
        .mappings()
        .one()
    )


def _with_created_at(proposal: RescheduleProposal, created_at: datetime) -> RescheduleProposal:
    return RescheduleProposal(
        id=proposal.id,
        service_queue_id=proposal.service_queue_id,
        resource_id=proposal.resource_id,
        location_id=proposal.location_id,
        observed_at=proposal.observed_at,
        horizon_end=proposal.horizon_end,
        source_fingerprint=proposal.source_fingerprint,
        source_checkpoint=proposal.source_checkpoint,
        proposal_fingerprint=proposal.proposal_fingerprint,
        executable_capacity_seconds=proposal.executable_capacity_seconds,
        committed_capacity_seconds=proposal.committed_capacity_seconds,
        shortfall_seconds=proposal.shortfall_seconds,
        affected=proposal.affected,
        created_at=created_at,
    )


def _proposal_from_row(row: RowMapping) -> RescheduleProposal:
    raw = cast(dict[str, object], row["snapshot"])
    affected_raw = cast(list[dict[str, object]], raw["affected"])
    checkpoint_raw = cast(dict[str, object], raw["source_checkpoint"])
    return RescheduleProposal(
        id=cast(UUID, row["id"]),
        service_queue_id=cast(UUID, row["service_queue_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        observed_at=cast(datetime, row["observed_at"]),
        horizon_end=cast(datetime, row["horizon_end"]),
        source_fingerprint=cast(str, row["source_fingerprint"]),
        source_checkpoint=_checkpoint_from_json(checkpoint_raw),
        proposal_fingerprint=cast(str, row["proposal_fingerprint"]),
        executable_capacity_seconds=cast(int, row["executable_capacity_seconds"]),
        committed_capacity_seconds=cast(int, row["committed_capacity_seconds"]),
        shortfall_seconds=cast(int, row["shortfall_seconds"]),
        affected=tuple(_affected_from_json(item) for item in affected_raw),
        created_at=cast(datetime, row["created_at"]),
    )


def _execution_from_row(row: RowMapping) -> RecoveryExecution:
    return RecoveryExecution(
        id=cast(UUID, row["id"]),
        proposal_id=cast(UUID, row["proposal_id"]),
        reservation_id=cast(UUID, row["reservation_id"]),
        status=RecoveryExecutionStatus(cast(str, row["status"])),
        original_reservation_revision=cast(int, row["original_reservation_revision"]),
        resulting_reservation_revision=cast(
            int | None, row["resulting_reservation_revision"]
        ),
        target=_target_from_json(cast(dict[str, object], row["target"])),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        failure_code=cast(str | None, row["failure_code"]),
        notification=OperationalNotification(
            requested=cast(bool, row["notification_requested"]),
            communication_task_id=cast(UUID | None, row["communication_task_id"]),
        ),
    )


def _affected(proposal: RescheduleProposal, reservation_id: UUID) -> AffectedReservation:
    return next(item for item in proposal.affected if item.reservation_id == reservation_id)


def _checkpoint_to_json(checkpoint: RecoverySourceCheckpoint) -> dict[str, object]:
    return {
        "projection_policy_revision": checkpoint.projection_policy_revision,
        "resource_availability_revision": checkpoint.resource_availability_revision,
        "location_operational_revision": checkpoint.location_operational_revision,
    }


def _checkpoint_from_json(raw: dict[str, object]) -> RecoverySourceCheckpoint:
    return RecoverySourceCheckpoint(
        projection_policy_revision=cast(int, raw["projection_policy_revision"]),
        resource_availability_revision=cast(int, raw["resource_availability_revision"]),
        location_operational_revision=cast(int, raw["location_operational_revision"]),
    )


def _affected_to_json(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "offering_version_id": str(item.offering_version_id),
        "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision,
        "original_start_at": item.original_start_at.isoformat(),
        "original_end_at": item.original_end_at.isoformat(),
        "target": _target_to_json(item.target) if item.target is not None else None,
    }


def _affected_from_json(raw: dict[str, object]) -> AffectedReservation:
    target = raw.get("target")
    return AffectedReservation(
        reservation_id=UUID(cast(str, raw["reservation_id"])),
        offering_version_id=UUID(cast(str, raw["offering_version_id"])),
        subject_party_id=UUID(cast(str, raw["subject_party_id"])),
        expected_revision=cast(int, raw["expected_revision"]),
        original_start_at=datetime.fromisoformat(cast(str, raw["original_start_at"])),
        original_end_at=datetime.fromisoformat(cast(str, raw["original_end_at"])),
        target=(
            _target_from_json(cast(dict[str, object], target))
            if target is not None
            else None
        ),
    )


def _target_to_json(target: RecoveryTarget) -> dict[str, object]:
    return {
        "start_at": target.start_at.isoformat(),
        "end_at": target.end_at.isoformat(),
        "location_id": str(target.location_id) if target.location_id is not None else None,
        "resources": [_resource_to_json(choice) for choice in target.resources],
        "actionable": target.actionable,
        "blocked_reason": target.blocked_reason,
    }


def _target_from_json(raw: dict[str, object]) -> RecoveryTarget:
    resources = cast(list[dict[str, object]], raw["resources"])
    location = cast(str | None, raw.get("location_id"))
    return RecoveryTarget(
        start_at=datetime.fromisoformat(cast(str, raw["start_at"])),
        end_at=datetime.fromisoformat(cast(str, raw["end_at"])),
        location_id=UUID(location) if location is not None else None,
        resources=tuple(_resource_from_json(item) for item in resources),
        actionable=cast(bool, raw["actionable"]),
        blocked_reason=cast(str | None, raw.get("blocked_reason")),
    )


def _resource_to_json(choice: ResourceChoice) -> dict[str, object]:
    return {
        "requirement_id": str(choice.requirement_id),
        "resource_id": str(choice.resource_id),
        "resource_location_assignment_id": (
            str(choice.resource_location_assignment_id)
            if choice.resource_location_assignment_id is not None
            else None
        ),
        "assignment_revision": choice.assignment_revision,
        "availability_revision": choice.availability_revision,
    }


def _resource_from_json(raw: dict[str, object]) -> ResourceChoice:
    assignment = cast(str | None, raw.get("resource_location_assignment_id"))
    return ResourceChoice(
        requirement_id=UUID(cast(str, raw["requirement_id"])),
        resource_id=UUID(cast(str, raw["resource_id"])),
        resource_location_assignment_id=UUID(assignment) if assignment is not None else None,
        assignment_revision=cast(int | None, raw.get("assignment_revision")),
        availability_revision=cast(int | None, raw.get("availability_revision")),
    )
