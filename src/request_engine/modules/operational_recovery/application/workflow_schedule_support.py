from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryActionKind
from request_engine.platform.idempotency.postgres import command_fingerprint


def validate_extend_day(command: ExtendRecoveryDayCommand) -> None:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_source_revision <= 0:
        raise ValueError("expected_source_revision must be positive")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    if not command.reason.strip():
        raise ValueError("reason is required")
    if command.start_at.tzinfo is None or command.start_at.utcoffset() is None:
        raise ValueError("start_at must be timezone-aware")
    if command.end_at.tzinfo is None or command.end_at.utcoffset() is None:
        raise ValueError("end_at must be timezone-aware")
    if command.end_at <= command.start_at:
        raise ValueError("end_at must be after start_at")


def extend_day_payload(command: ExtendRecoveryDayCommand) -> dict[str, object]:
    return {
        "authority_party_id": command.authority_party_id,
        "assignment_id": command.assignment_id,
        "start_at": command.start_at,
        "end_at": command.end_at,
        "expected_resource_availability_revision": (
            command.expected_resource_availability_revision
        ),
        "reason": command.reason,
    }


def extend_day_fingerprint(
    command: ExtendRecoveryDayCommand,
    payload: dict[str, object],
) -> str:
    return command_fingerprint(
        f"operational_recovery.{RecoveryActionKind.EXTEND_DAY.value}.v1",
        {
            "incident_id": command.incident_id,
            "expected_source_revision": command.expected_source_revision,
            **payload,
        },
    )
