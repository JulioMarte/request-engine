from datetime import UTC, datetime, time
from typing import cast
from uuid import UUID

import pytest

from request_engine.modules.operational_copilot.adapters.recovery_replay_resolution import (
    resolve_recovery_replay,
)
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
    RecoveryActionStatus,
)

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
INCIDENT = UUID("33333333-3333-3333-3333-333333333333")
ASSIGNMENT = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
CTX = CopilotContext(ORG, PRINCIPAL, "same-key")


class _Reader:
    def __init__(self, action: RecoveryAction | None) -> None:
        self.action = action

    async def get_action_by_idempotency(self, **_: object) -> RecoveryAction | None:
        return self.action


def _reader(action: RecoveryAction) -> CopilotRecoveryIncidentReader:
    return cast(CopilotRecoveryIncidentReader, _Reader(action))


def _action(kind: RecoveryActionKind, payload: dict[str, object]) -> RecoveryAction:
    return RecoveryAction(
        id=UUID("55555555-5555-5555-5555-555555555555"),
        organization_id=ORG,
        incident_id=INCIDENT,
        action_kind=kind,
        status=RecoveryActionStatus.SUCCEEDED,
        principal_id=PRINCIPAL,
        idempotency_key=CTX.idempotency_key,
        command_fingerprint="fingerprint",
        expected_source_revision=7,
        payload=payload,
        owner_steps={},
        failure_code=None,
        created_at=NOW,
        started_at=NOW,
        completed_at=NOW,
    )


@pytest.mark.asyncio
async def test_rest_of_day_replay_reuses_original_guarded_state() -> None:
    action = _action(
        RecoveryActionKind.STOP_INTAKE,
        {
            "expected_intake_revision": 3,
            "accepting": False,
            "reason": "operational copilot: stop accepting walk-ins for the rest of the day",
            "effective_until": "2026-08-30 23:30:00+00:00",
        },
    )
    resolved = await resolve_recovery_replay(_reader(action), CTX, StopWalkInsRestOfDayIntent())
    assert resolved == SetRecoveryIntakeIntent(
        INCIDENT,
        False,
        7,
        3,
        "operational copilot: stop accepting walk-ins for the rest of the day",
        datetime(2026, 8, 30, 23, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_named_extend_replay_reuses_original_owner_payload() -> None:
    action = _action(
        RecoveryActionKind.EXTEND_DAY,
        {
            "assignment_id": str(ASSIGNMENT),
            "start_at": "2026-08-30 18:00:00+00:00",
            "end_at": "2026-08-30 19:00:00+00:00",
            "expected_location_operational_revision": 5,
            "expected_resource_availability_revision": 9,
            "reason": "operational copilot: extend Dr. A today",
        },
    )
    resolved = await resolve_recovery_replay(
        _reader(action), CTX, ExtendNamedResourceTodayIntent("Dr. A", time(19, 0))
    )
    assert resolved == ExtendRecoveryDayIntent(
        INCIDENT,
        ASSIGNMENT,
        datetime(2026, 8, 30, 18, 0, tzinfo=UTC),
        datetime(2026, 8, 30, 19, 0, tzinfo=UTC),
        7,
        5,
        9,
        "operational copilot: extend Dr. A today",
    )


@pytest.mark.asyncio
async def test_replay_refuses_same_key_bound_to_different_semantics() -> None:
    action = _action(
        RecoveryActionKind.STOP_INTAKE,
        {"accepting": False, "reason": "different command"},
    )
    with pytest.raises(CopilotResolutionFailed):
        await resolve_recovery_replay(_reader(action), CTX, StopWalkInsRestOfDayIntent())
