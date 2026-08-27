import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
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
    RecoveryExecution,
    RecoveryTarget,
    RescheduleProposal,
)


@dataclass(frozen=True, slots=True)
class CreateRecoveryProposalCommand:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
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
        self, command: CreateRecoveryProposalCommand
    ) -> RescheduleProposal:
        if command.search_days <= 0 or command.search_days > 30:
            raise ValueError("search_days must be between 1 and 30")
        assessment = await self._capacity.assess_recovery_capacity(
            organization_id=command.organization_id,
            service_queue_id=command.service_queue_id,
        )
        if assessment.shortfall_seconds <= 0:
            raise RecoveryShortfallNotMaterial()

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
                )
            )

        if not affected:
            raise RecoveryShortfallNotMaterial()
        proposal_fingerprint = _proposal_fingerprint(
            source_fingerprint=assessment.source_fingerprint,
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
            proposal=proposal,
        )

    async def get_proposal(
        self, *, organization_id: UUID, proposal_id: UUID
    ) -> RescheduleProposal:
        proposal = await self._repository.get_proposal(
            organization_id=organization_id, proposal_id=proposal_id
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
        if (
            command.expected_source_fingerprint != proposal.source_fingerprint
            or command.expected_proposal_fingerprint != proposal.proposal_fingerprint
        ):
            raise StaleRecoveryProposal()
        affected = next(
            (item for item in proposal.affected if item.reservation_id == command.reservation_id),
            None,
        )
        if affected is None:
            raise RecoveryReservationNotAffected(command.reservation_id)
        if affected.target is None or not affected.target.actionable:
            reason = affected.target.blocked_reason if affected.target is not None else None
            raise RecoveryTargetUnavailable(command.reservation_id, reason)

        fingerprint = _execution_fingerprint(command, affected.target)
        async with self._repository.execution_unit(
            organization_id=command.organization_id,
            proposal_id=command.proposal_id,
            reservation_id=command.reservation_id,
        ) as unit:
            existing = await unit.existing()
            if existing is not None:
                execution, stored_fingerprint = existing
                if stored_fingerprint != fingerprint:
                    raise RecoveryIdempotencyConflict()
            else:
                current_capacity = await self._capacity.assess_recovery_capacity(
                    organization_id=command.organization_id,
                    service_queue_id=proposal.service_queue_id,
                )
                if current_capacity.source_fingerprint != proposal.source_fingerprint:
                    raise StaleRecoveryProposal()
                current_reservation = await self._booking.get_reservation(
                    organization_id=command.organization_id,
                    reservation_id=command.reservation_id,
                )
                if (
                    current_reservation is None
                    or current_reservation.revision != affected.expected_revision
                ):
                    raise StaleRecoveryProposal()
                try:
                    result = await self._booking.reschedule_for_recovery(
                        RecoveryRescheduleRequest(
                            organization_id=command.organization_id,
                            principal_id=command.principal_id,
                            reservation_id=command.reservation_id,
                            expected_revision=affected.expected_revision,
                            start_at=affected.target.start_at,
                            location_id=affected.target.location_id,
                            resources=affected.target.resources,
                            idempotency_key=f"recovery:{command.idempotency_key}:booking",
                            allow_subject_override=command.allow_subject_override,
                        )
                    )
                except RecoveryBookingConflict as exc:
                    raise StaleRecoveryProposal() from exc
                except BookingRecoveryTargetUnavailable as exc:
                    raise RecoveryTargetUnavailable(command.reservation_id, str(exc)) from exc
                execution = await unit.record(
                    principal_id=command.principal_id,
                    idempotency_key=command.idempotency_key,
                    command_fingerprint=fingerprint,
                    proposal=proposal,
                    reservation_id=command.reservation_id,
                    resulting_revision=result.revision,
                    notification_requested=command.notify,
                )

        if command.notify and execution.notification.communication_task_id is None:
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
                        "new_start_at": affected.target.start_at.isoformat(),
                        "new_end_at": affected.target.end_at.isoformat(),
                    },
                )
            )
            execution = await self._repository.attach_communication_task(
                organization_id=command.organization_id,
                execution_id=execution.id,
                communication_task_id=task.id,
            )
        return execution


def _choose_target(
    slots: tuple[AppointmentSlot, ...], *, original_start, original_end
) -> RecoveryTarget | None:
    for slot in slots:
        if slot.start_at == original_start and slot.end_at == original_end:
            continue
        contextual = any(
            choice.resource_location_assignment_id is not None for choice in slot.resources
        )
        return RecoveryTarget(
            start_at=slot.start_at,
            end_at=slot.end_at,
            location_id=slot.location_id,
            resources=slot.resources,
            actionable=not contextual,
            blocked_reason="contextual_reschedule_not_supported" if contextual else None,
        )
    return None


def _proposal_fingerprint(
    *,
    source_fingerprint: str,
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
            "proposal_id": str(command.proposal_id),
            "reservation_id": str(command.reservation_id),
            "expected_source_fingerprint": command.expected_source_fingerprint,
            "expected_proposal_fingerprint": command.expected_proposal_fingerprint,
            "notify": command.notify,
            "target": _target_payload(target),
        }
    )


def _affected_payload(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "offering_version_id": str(item.offering_version_id),
        "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision,
        "original_start_at": item.original_start_at.isoformat(),
        "original_end_at": item.original_end_at.isoformat(),
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
