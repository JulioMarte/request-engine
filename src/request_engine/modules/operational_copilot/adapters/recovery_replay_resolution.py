from datetime import datetime
from uuid import UUID

from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendRecoveryDayIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import (
    ExtendNamedResourceTodayIntent,
    StopWalkInsRestOfDayIntent,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
)


async def resolve_recovery_replay(
    recovery: CopilotRecoveryIncidentReader,
    context: CopilotContext,
    intent: ExtendNamedResourceTodayIntent | StopWalkInsRestOfDayIntent,
) -> ExtendRecoveryDayIntent | SetRecoveryIntakeIntent | None:
    action = await recovery.get_action_by_idempotency(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        idempotency_key=context.idempotency_key,
    )
    if action is None:
        return None
    if isinstance(intent, StopWalkInsRestOfDayIntent):
        return _stop_intake_replay(action)
    return _extend_day_replay(action, intent)


def _stop_intake_replay(action: RecoveryAction) -> SetRecoveryIntakeIntent:
    reason = "operational copilot: stop accepting walk-ins for the rest of the day"
    if (
        action.action_kind is not RecoveryActionKind.STOP_INTAKE
        or action.payload.get("accepting") is not False
        or action.payload.get("reason") != reason
    ):
        raise _incompatible_replay()
    return SetRecoveryIntakeIntent(
        incident_id=action.incident_id,
        accepting=False,
        expected_source_revision=action.expected_source_revision,
        expected_intake_revision=_int(action, "expected_intake_revision"),
        reason=reason,
        effective_until=_datetime(action, "effective_until"),
    )


def _extend_day_replay(
    action: RecoveryAction,
    intent: ExtendNamedResourceTodayIntent,
) -> ExtendRecoveryDayIntent:
    reason = f"operational copilot: extend {intent.resource_reference} today"
    end_at = _datetime(action, "end_at")
    target = intent.target_local_time
    if (
        action.action_kind is not RecoveryActionKind.EXTEND_DAY
        or action.payload.get("reason") != reason
        or (end_at.hour, end_at.minute, end_at.second, end_at.microsecond)
        != (target.hour, target.minute, target.second, target.microsecond)
    ):
        raise _incompatible_replay()
    return ExtendRecoveryDayIntent(
        incident_id=action.incident_id,
        assignment_id=_uuid(action, "assignment_id"),
        start_at=_datetime(action, "start_at"),
        end_at=end_at,
        expected_source_revision=action.expected_source_revision,
        expected_location_operational_revision=_int(
            action, "expected_location_operational_revision"
        ),
        expected_resource_availability_revision=_int(
            action, "expected_resource_availability_revision"
        ),
        reason=reason,
    )


def _int(action: RecoveryAction, key: str) -> int:
    value = action.payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _incompatible_replay()
    return value


def _uuid(action: RecoveryAction, key: str) -> UUID:
    value = action.payload.get(key)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _incompatible_replay() from exc


def _datetime(action: RecoveryAction, key: str) -> datetime:
    value = action.payload.get(key)
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _incompatible_replay() from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _incompatible_replay()
    return parsed


def _incompatible_replay() -> CopilotResolutionFailed:
    return CopilotResolutionFailed(
        "idempotency key is already bound to an incompatible recovery operation"
    )
