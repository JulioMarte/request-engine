import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
    RecoveryCommitmentCheckpoint as BookingCommitmentCheckpoint,
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable as BookingRecoveryTargetUnavailable,
)
from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationRequest,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryIdempotencyConflict,
    RecoveryProposalNotFound,
    RecoveryReservationNotAffected,
    RecoveryShortfallNotMaterial,
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryCommitmentCheckpoint,
    RecoveryExecution,
    RecoveryExecutionStatus,
    RecoverySourceCheckpoint,
    RecoveryTarget,
    RescheduleProposal,
)

_STALE_FAILURE = "STALE_RECOVERY_PROPOSAL"
_TARGET_FAILURE = "RECOVERY_TARGET_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CreateRecoveryProposalCommand:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    idempotency_key: str
    search_days: int = 7


@dataclass(frozen=True, slots=True)
class ExecuteRecoveryCommand:
    organization_id: UUID
    principal_id: UUID
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str
    expected_proposal_fingerprint: str
    idempotency_key: str
    allow_subject_override: bool
    notify: bool = True


class OperationalRecoveryService:
    def __init__(
        self,
        *,
        repository: RecoveryRepository,
        capacity: RecoveryCapacitySource,
        booking: RecoveryBookingPort,
        communications: RecoveryCommunicationPort,
    ) -> None:
        self._repository = repository
        self._capacity = capacity
        self._booking = booking
        self._communications = communications

    async def create_proposal(
        self,
        command: CreateRecoveryProposalCommand,
    ) -> RescheduleProposal:
        if not command.idempotency_key:
            raise ValueError("idempotency_key is required")
        if command.search_days <= 0 or command.search_days > 30:
            raise ValueError("search_days must be between 1 and 30")

        command_fingerprint = _proposal_command_fingerprint(command)
        replay = await self._repository.find_proposal_replay(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_key=command.idempotency_key,
            command_fingerprint=command_fingerprint,
        )
        if replay is not None:
            return replay

        assessment = await self._capacity.assess_recovery_capacity(
            organization_id=command.organization_id,
            service_queue_id=command.service_queue_id,
        )
        if assessment.shortfall_seconds <= 0:
            raise RecoveryShortfallNotMaterial()
        if not assessment.affected_commitments:
            raise RuntimeError(
                "positive recovery shortfall has no directly unsatisfied Reservations"
            )

        affected: list[AffectedReservation] = []
        for commitment in assessment.affected_commitments:
            slots = await self._booking.find_recovery_slots(
                organization_id=command.organization_id,
                offering_version_id=commitment.offering_version_id,
                window_start=max(assessment.observed_at, commitment.planned_starts_at),
                window_end=assessment.horizon_end + timedelta(days=command.search_days),
                location_id=assessment.location_id,
                limit=25,
            )
            target = _choose_target(
                slots,
                original_start=commitment.planned_starts_at,
                original_end=commitment.planned_ends_at,
                source_contextual=commitment.contextual_commitment,
            )
            affected.append(
                AffectedReservation(
                    reservation_id=commitment.reservation_id,
                    offering_version_id=commitment.offering_version_id,
                    subject_party_id=commitment.subject_party_id,
                    expected_revision=commitment.reservation_revision,
                    original_start_at=commitment.planned_starts_at,
                    original_end_at=commitment.planned_ends_at,
                    target=target,
                    contextual_commitment=commitment.contextual_commitment,
                )
            )

        source_checkpoint = RecoverySourceCheckpoint(
            projection_policy_revision=assessment.checkpoint.projection_policy_revision,
            resource_availability_revision=(
                assessment.checkpoint.resource_availability_revision
            ),
            location_operational_revision=(
                assessment.checkpoint.location_operational_revision
            ),
            commitments=tuple(
                RecoveryCommitmentCheckpoint(
                    reservation_id=item.reservation_id,
                    revision=item.revision,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                )
                for item in assessment.checkpoint.commitments
            ),
        )
        proposal_fingerprint = _proposal_fingerprint(
            source_fingerprint=assessment.source_fingerprint,
            source_checkpoint=source_checkpoint,
            service_queue_id=assessment.service_queue_id,
            resource_id=assessment.resource_id,
            location_id=assessment.location_id,
            executable_capacity_seconds=assessment.executable_capacity_seconds,
            committed_capacity_seconds=assessment.committed_capacity_seconds,
            shortfall_seconds=assessment.shortfall_seconds,
            affected=tuple(affected),
        )
        proposal = RescheduleProposal(
            id=uuid4(),
            service_queue_id=assessment.service_queue_id,
            resource_id=assessment.resource_id,
            location_id=assessment.location_id,
            observed_at=assessment.observed_at,
            horizon_end=assessment.horizon_end,
            source_fingerprint=assessment.source_fingerprint,
            source_checkpoint=source_checkpoint,
            proposal_fingerprint=proposal_fingerprint,
            executable_capacity_seconds=assessment.executable_capacity_seconds,
            committed_capacity_seconds=assessment.committed_capacity_seconds,
            shortfall_seconds=assessment.shortfall_seconds,
            affected=tuple(affected),
            created_at=assessment.observed_at,
        )
        return await self._repository.create_proposal(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_key=command.idempotency_key,
            command_fingerprint=command_fingerprint,
            proposal=proposal,
        )

    async def get_proposal(
        self,
        *,
        organization_id: UUID,
        proposal_id: UUID,
    ) -> RescheduleProposal:
        proposal = await self._repository.get_proposal(
            organization_id=organization_id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            raise RecoveryProposalNotFound(proposal_id)
        return proposal

    async def execute(self, command: ExecuteRecoveryCommand) -> RecoveryExecution:
        if not command.idempotency_key:
            raise ValueError("idempotency_key is required")
        proposal = await self.get_proposal(
            organization_id=command.organization_id,
            proposal_id=command.proposal_id,
        )
        _require_expected_proposal(command, proposal)
        affected = _affected_reservation(proposal, command.reservation_id)
        target = affected.target
        if target is None or not target.actionable:
            reason = target.blocked_reason if target is not None else None
            raise RecoveryTargetUnavailable(command.reservation_id, reason)

        fingerprint = _execution_fingerprint(command, target)
        record = await self._repository.prepare_execution(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_key=command.idempotency_key,
            command_fingerprint=fingerprint,
            proposal=proposal,
            reservation_id=command.reservation_id,
            notification_requested=command.notify,
        )
        execution = record.execution
        if (
            execution.proposal_id != command.proposal_id
            or execution.reservation_id != command.reservation_id
            or record.command_fingerprint != fingerprint
        ):
            raise RecoveryIdempotencyConflict()
        if execution.status is RecoveryExecutionStatus.REJECTED:
            _raise_rejected(execution, command.reservation_id)

        if execution.status is RecoveryExecutionStatus.PREPARED:
            if record.created:
                await self._validate_new_execution_source(
                    command=command,
                    proposal=proposal,
                    execution=execution,
                )
            try:
                result = await self._booking.reschedule_for_recovery(
                    RecoveryRescheduleRequest(
                        organization_id=command.organization_id,
                        principal_id=command.principal_id,
                        reservation_id=command.reservation_id,
                        expected_revision=affected.expected_revision,
                        start_at=target.start_at,
                        location_id=target.location_id,
                        resources=target.resources,
                        source_resource_id=proposal.resource_id,
                        expected_source_resource_availability_revision=(
                            proposal.source_checkpoint.resource_availability_revision
                        ),
                        source_location_id=proposal.location_id,
                        expected_source_location_operational_revision=(
                            proposal.source_checkpoint.location_operational_revision
                        ),
                        source_observed_at=proposal.observed_at,
                        source_horizon_end=proposal.horizon_end,
                        expected_source_commitments=tuple(
                            BookingCommitmentCheckpoint(
                                reservation_id=item.reservation_id,
                                revision=item.revision,
                                starts_at=item.starts_at,
                                ends_at=item.ends_at,
                            )
                            for item in proposal.source_checkpoint.commitments
                        ),
                        idempotency_key=f"recovery:{execution.id}:booking:v1",
                        allow_subject_override=command.allow_subject_override,
                    )
                )
            except RecoveryBookingConflict as exc:
                await self._reject(
                    command.organization_id,
                    execution.id,
                    _STALE_FAILURE,
                )
                raise StaleRecoveryProposal() from exc
            except BookingRecoveryTargetUnavailable as exc:
                await self._reject(
                    command.organization_id,
                    execution.id,
                    _TARGET_FAILURE,
                )
                raise RecoveryTargetUnavailable(
                    command.reservation_id,
                    str(exc),
                ) from exc
            execution = await self._repository.succeed_execution(
                organization_id=command.organization_id,
                execution_id=execution.id,
                resulting_revision=result.revision,
            )

        if command.notify and execution.notification.communication_task_id is None:
            execution = await self._ensure_notification(
                command=command,
                affected=affected,
                execution=execution,
            )
        return execution

    async def _validate_new_execution_source(
        self,
        *,
        command: ExecuteRecoveryCommand,
        proposal: RescheduleProposal,
        execution: RecoveryExecution,
    ) -> None:
        current = await self._capacity.assess_recovery_capacity(
            organization_id=command.organization_id,
            service_queue_id=proposal.service_queue_id,
        )
        if current.source_fingerprint == proposal.source_fingerprint:
            return
        await self._reject(
            command.organization_id,
            execution.id,
            _STALE_FAILURE,
        )
        raise StaleRecoveryProposal()

    async def _ensure_notification(
        self,
        *,
        command: ExecuteRecoveryCommand,
        affected: AffectedReservation,
        execution: RecoveryExecution,
    ) -> RecoveryExecution:
        if execution.status is not RecoveryExecutionStatus.SUCCEEDED:
            raise RuntimeError("notification requires a succeeded recovery execution")
        target = affected.target
        if target is None:
            raise RuntimeError("succeeded recovery execution is missing its target")
        task = await self._communications.create_recovery_notification(
            RecoveryCommunicationRequest(
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                recipient_party_id=affected.subject_party_id,
                execution_id=execution.id,
                idempotency_key=f"recovery:{execution.id}:notification:v1",
                dedupe_key=f"operational-recovery:{execution.id}:rescheduled:v1",
                render_context={
                    "reservation_id": str(command.reservation_id),
                    "old_start_at": affected.original_start_at.isoformat(),
                    "old_end_at": affected.original_end_at.isoformat(),
                    "new_start_at": target.start_at.isoformat(),
                    "new_end_at": target.end_at.isoformat(),
                },
            )
        )
        return await self._repository.attach_communication_task(
            organization_id=command.organization_id,
            execution_id=execution.id,
            communication_task_id=task.id,
        )

    async def _reject(
        self,
        organization_id: UUID,
        execution_id: UUID,
        failure_code: str,
    ) -> None:
        await self._repository.reject_execution(
            organization_id=organization_id,
            execution_id=execution_id,
            failure_code=failure_code,
        )


def _require_expected_proposal(
    command: ExecuteRecoveryCommand,
    proposal: RescheduleProposal,
) -> None:
    if (
        command.expected_source_fingerprint != proposal.source_fingerprint
        or command.expected_proposal_fingerprint != proposal.proposal_fingerprint
    ):
        raise StaleRecoveryProposal()


def _affected_reservation(
    proposal: RescheduleProposal,
    reservation_id: UUID,
) -> AffectedReservation:
    affected = next(
        (item for item in proposal.affected if item.reservation_id == reservation_id),
        None,
    )
    if affected is None:
        raise RecoveryReservationNotAffected(reservation_id)
    return affected


def _raise_rejected(execution: RecoveryExecution, reservation_id: UUID) -> None:
    if execution.failure_code == _STALE_FAILURE:
        raise StaleRecoveryProposal()
    if execution.failure_code == _TARGET_FAILURE:
        raise RecoveryTargetUnavailable(reservation_id)
    raise RuntimeError(f"unknown recovery rejection code: {execution.failure_code}")


def _choose_target(
    slots: tuple[AppointmentSlot, ...],
    *,
    original_start: datetime,
    original_end: datetime,
    source_contextual: bool,
) -> RecoveryTarget | None:
    blocked: RecoveryTarget | None = None
    for slot in slots:
        if slot.start_at == original_start and slot.end_at == original_end:
            continue
        target_contextual = any(
            choice.resource_location_assignment_id is not None for choice in slot.resources
        )
        if source_contextual:
            if blocked is None:
                blocked = _target_from_slot(
                    slot,
                    actionable=False,
                    blocked_reason="contextual_source_reschedule_not_supported",
                )
            continue
        if not target_contextual:
            return _target_from_slot(slot, actionable=True, blocked_reason=None)
        if blocked is None:
            blocked = _target_from_slot(
                slot,
                actionable=False,
                blocked_reason="contextual_target_reschedule_not_supported",
            )
    return blocked


def _target_from_slot(
    slot: AppointmentSlot,
    *,
    actionable: bool,
    blocked_reason: str | None,
) -> RecoveryTarget:
    return RecoveryTarget(
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=slot.resources,
        actionable=actionable,
        blocked_reason=blocked_reason,
    )


def _proposal_command_fingerprint(command: CreateRecoveryProposalCommand) -> str:
    return _hash(
        {
            "service_queue_id": str(command.service_queue_id),
            "search_days": command.search_days,
        }
    )


def _proposal_fingerprint(
    *,
    source_fingerprint: str,
    source_checkpoint: RecoverySourceCheckpoint,
    service_queue_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    executable_capacity_seconds: int,
    committed_capacity_seconds: int,
    shortfall_seconds: int,
    affected: tuple[AffectedReservation, ...],
) -> str:
    payload = {
        "source_fingerprint": source_fingerprint,
        "source_checkpoint": _checkpoint_payload(source_checkpoint),
        "service_queue_id": str(service_queue_id),
        "resource_id": str(resource_id),
        "location_id": str(location_id),
        "executable_capacity_seconds": executable_capacity_seconds,
        "committed_capacity_seconds": committed_capacity_seconds,
        "shortfall_seconds": shortfall_seconds,
        "affected": [_affected_payload(item) for item in affected],
    }
    return _hash(payload)


def _execution_fingerprint(command: ExecuteRecoveryCommand, target: RecoveryTarget) -> str:
    return _hash(
        {
            "organization_id": str(command.organization_id),
            "principal_id": str(command.principal_id),
            "proposal_id": str(command.proposal_id),
            "reservation_id": str(command.reservation_id),
            "expected_source_fingerprint": command.expected_source_fingerprint,
            "expected_proposal_fingerprint": command.expected_proposal_fingerprint,
            "idempotency_key": command.idempotency_key,
            "allow_subject_override": command.allow_subject_override,
            "notify": command.notify,
            "target": _target_payload(target),
        }
    )


def _checkpoint_payload(checkpoint: RecoverySourceCheckpoint) -> dict[str, object]:
    return {
        "projection_policy_revision": checkpoint.projection_policy_revision,
        "resource_availability_revision": checkpoint.resource_availability_revision,
        "location_operational_revision": checkpoint.location_operational_revision,
        "commitments": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.revision,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
            }
            for item in checkpoint.commitments
        ],
    }


def _affected_payload(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "offering_version_id": str(item.offering_version_id),
        "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision,
        "original_start_at": item.original_start_at.isoformat(),
        "original_end_at": item.original_end_at.isoformat(),
        "contextual_commitment": item.contextual_commitment,
        "target": _target_payload(item.target) if item.target is not None else None,
    }


def _target_payload(target: RecoveryTarget) -> dict[str, object]:
    return {
        "start_at": target.start_at.isoformat(),
        "end_at": target.end_at.isoformat(),
        "location_id": str(target.location_id) if target.location_id is not None else None,
        "resources": [_resource_payload(item) for item in target.resources],
        "actionable": target.actionable,
        "blocked_reason": target.blocked_reason,
    }


def _resource_payload(choice: ResourceChoice) -> dict[str, object]:
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


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
