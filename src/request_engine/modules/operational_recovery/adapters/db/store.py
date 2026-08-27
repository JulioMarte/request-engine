import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.operational_recovery.application.ports import RecoveryExecutionUnit, RecoveryRepository
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    OperationalNotification,
    RecoveryExecution,
    RecoveryTarget,
    RescheduleProposal,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRecoveryExecutionUnit(RecoveryExecutionUnit):
    def __init__(self, session: AsyncSession, *, organization_id: UUID, proposal_id: UUID, reservation_id: UUID) -> None:
        self._session = session
        self._organization_id = organization_id
        self._proposal_id = proposal_id
        self._reservation_id = reservation_id

    async def existing(self) -> tuple[RecoveryExecution, str] | None:
        row = ((await self._session.execute(text("""
            SELECT * FROM request_engine.operational_recovery_executions
            WHERE organization_id = :organization_id
              AND proposal_id = :proposal_id
              AND reservation_id = :reservation_id
        """), {"organization_id": self._organization_id, "proposal_id": self._proposal_id, "reservation_id": self._reservation_id})).mappings().one_or_none())
        if row is None:
            return None
        return _execution_from_row(row), cast(str, row["command_fingerprint"])

    async def record(
        self,
        *,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
        reservation_id: UUID,
        resulting_revision: int,
        notification_requested: bool,
    ) -> RecoveryExecution:
        affected = next(item for item in proposal.affected if item.reservation_id == reservation_id)
        if affected.target is None:
            raise RuntimeError("cannot record execution without a target")
        row = ((await self._session.execute(text("""
            INSERT INTO request_engine.operational_recovery_executions (
                organization_id, proposal_id, reservation_id, executed_by_principal_id,
                idempotency_key, command_fingerprint, source_fingerprint, proposal_fingerprint,
                original_reservation_revision, resulting_reservation_revision, target,
                notification_requested
            ) VALUES (
                :organization_id, :proposal_id, :reservation_id, :principal_id,
                :idempotency_key, :command_fingerprint, :source_fingerprint, :proposal_fingerprint,
                :original_revision, :resulting_revision, CAST(:target AS jsonb),
                :notification_requested
            ) RETURNING *
        """), {
            "organization_id": self._organization_id,
            "proposal_id": proposal.id,
            "reservation_id": reservation_id,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "command_fingerprint": command_fingerprint,
            "source_fingerprint": proposal.source_fingerprint,
            "proposal_fingerprint": proposal.proposal_fingerprint,
            "original_revision": affected.expected_revision,
            "resulting_revision": resulting_revision,
            "target": json.dumps(_target_to_json(affected.target), separators=(",", ":")),
            "notification_requested": notification_requested,
        })).mappings().one())
        return _execution_from_row(row)


class PostgresRecoveryRepository(RecoveryRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_proposal(self, *, organization_id: UUID, principal_id: UUID, proposal: RescheduleProposal) -> RescheduleProposal:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            created_at = cast(datetime, (await session.execute(text("""
                INSERT INTO request_engine.operational_recovery_proposals (
                    id, organization_id, service_queue_id, resource_id, location_id,
                    created_by_principal_id, observed_at, horizon_end, source_fingerprint,
                    proposal_fingerprint, executable_capacity_seconds, committed_capacity_seconds,
                    shortfall_seconds, snapshot
                ) VALUES (
                    :id, :organization_id, :service_queue_id, :resource_id, :location_id,
                    :principal_id, :observed_at, :horizon_end, :source_fingerprint,
                    :proposal_fingerprint, :executable_capacity_seconds, :committed_capacity_seconds,
                    :shortfall_seconds, CAST(:snapshot AS jsonb)
                ) RETURNING created_at
            """), {
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
                "snapshot": json.dumps({"affected": [_affected_to_json(item) for item in proposal.affected]}, separators=(",", ":")),
            })).scalar_one())
        return RescheduleProposal(
            id=proposal.id,
            service_queue_id=proposal.service_queue_id,
            resource_id=proposal.resource_id,
            location_id=proposal.location_id,
            observed_at=proposal.observed_at,
            horizon_end=proposal.horizon_end,
            source_fingerprint=proposal.source_fingerprint,
            proposal_fingerprint=proposal.proposal_fingerprint,
            executable_capacity_seconds=proposal.executable_capacity_seconds,
            committed_capacity_seconds=proposal.committed_capacity_seconds,
            shortfall_seconds=proposal.shortfall_seconds,
            affected=proposal.affected,
            created_at=created_at,
        )

    async def get_proposal(self, *, organization_id: UUID, proposal_id: UUID) -> RescheduleProposal | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = ((await session.execute(text("""
                SELECT * FROM request_engine.operational_recovery_proposals
                WHERE organization_id = :organization_id AND id = :proposal_id
            """), {"organization_id": organization_id, "proposal_id": proposal_id})).mappings().one_or_none())
        return _proposal_from_row(row) if row is not None else None

    @asynccontextmanager
    async def execution_unit(self, *, organization_id: UUID, proposal_id: UUID, reservation_id: UUID):
        async with tenant_transaction(self._session_factory, organization_id) as session:
            lock_key = f"operational-recovery:{organization_id}:{proposal_id}:{reservation_id}"
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": lock_key},
            )
            yield PostgresRecoveryExecutionUnit(
                session,
                organization_id=organization_id,
                proposal_id=proposal_id,
                reservation_id=reservation_id,
            )

    async def attach_communication_task(self, *, organization_id: UUID, execution_id: UUID, communication_task_id: UUID) -> RecoveryExecution:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = ((await session.execute(text("""
                UPDATE request_engine.operational_recovery_executions
                SET communication_task_id = :communication_task_id
                WHERE organization_id = :organization_id
                  AND id = :execution_id
                  AND communication_task_id IS NULL
                RETURNING *
            """), {"organization_id": organization_id, "execution_id": execution_id, "communication_task_id": communication_task_id})).mappings().one_or_none())
            if row is None:
                row = ((await session.execute(text("""
                    SELECT * FROM request_engine.operational_recovery_executions
                    WHERE organization_id = :organization_id AND id = :execution_id
                """), {"organization_id": organization_id, "execution_id": execution_id})).mappings().one())
                if cast(UUID | None, row["communication_task_id"]) != communication_task_id:
                    raise RuntimeError("recovery execution already references another communication task")
        return _execution_from_row(row)


def _proposal_from_row(row) -> RescheduleProposal:
    raw = cast(dict[str, object], row["snapshot"])
    affected_raw = cast(list[dict[str, object]], raw.get("affected", []))
    return RescheduleProposal(
        id=cast(UUID, row["id"]),
        service_queue_id=cast(UUID, row["service_queue_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        observed_at=cast(datetime, row["observed_at"]),
        horizon_end=cast(datetime, row["horizon_end"]),
        source_fingerprint=cast(str, row["source_fingerprint"]),
        proposal_fingerprint=cast(str, row["proposal_fingerprint"]),
        executable_capacity_seconds=cast(int, row["executable_capacity_seconds"]),
        committed_capacity_seconds=cast(int, row["committed_capacity_seconds"]),
        shortfall_seconds=cast(int, row["shortfall_seconds"]),
        affected=tuple(_affected_from_json(item) for item in affected_raw),
        created_at=cast(datetime, row["created_at"]),
    )


def _execution_from_row(row) -> RecoveryExecution:
    return RecoveryExecution(
        id=cast(UUID, row["id"]),
        proposal_id=cast(UUID, row["proposal_id"]),
        reservation_id=cast(UUID, row["reservation_id"]),
        original_reservation_revision=cast(int, row["original_reservation_revision"]),
        resulting_reservation_revision=cast(int, row["resulting_reservation_revision"]),
        target=_target_from_json(cast(dict[str, object], row["target"])),
        executed_at=cast(datetime, row["executed_at"]),
        notification=OperationalNotification(
            requested=cast(bool, row["notification_requested"]),
            communication_task_id=cast(UUID | None, row["communication_task_id"]),
        ),
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
        target=_target_from_json(cast(dict[str, object], target)) if target is not None else None,
    )


def _target_to_json(target: RecoveryTarget) -> dict[str, object]:
    return {
        "start_at": target.start_at.isoformat(),
        "end_at": target.end_at.isoformat(),
        "location_id": str(target.location_id) if target.location_id is not None else None,
        "resources": [
            {
                "requirement_id": str(choice.requirement_id),
                "resource_id": str(choice.resource_id),
                "resource_location_assignment_id": str(choice.resource_location_assignment_id) if choice.resource_location_assignment_id is not None else None,
                "assignment_revision": choice.assignment_revision,
                "availability_revision": choice.availability_revision,
            }
            for choice in target.resources
        ],
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
        resources=tuple(
            ResourceChoice(
                requirement_id=UUID(cast(str, item["requirement_id"])),
                resource_id=UUID(cast(str, item["resource_id"])),
                resource_location_assignment_id=UUID(cast(str, item["resource_location_assignment_id"])) if item.get("resource_location_assignment_id") is not None else None,
                assignment_revision=cast(int | None, item.get("assignment_revision")),
                availability_revision=cast(int | None, item.get("availability_revision")),
            )
            for item in resources
        ),
        actionable=cast(bool, raw["actionable"]),
        blocked_reason=cast(str | None, raw.get("blocked_reason")),
    )
