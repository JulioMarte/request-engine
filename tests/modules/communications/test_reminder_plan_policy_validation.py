from __future__ import annotations

import asyncio
from datetime import time
from uuid import uuid4

import pytest

from request_engine.modules.communications.api.errors import resolve_communications_error
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.modules.communications.application.errors import DeliveryConfigurationError
from request_engine.modules.communications.contracts.reminders import ReminderPlan

pytestmark = [pytest.mark.unit]

USABLE_POLICY: dict[str, object] = {
    "channels": ["email"],
    "provider_key": "provider-a",
}


class _Delegated(Exception):
    pass


class RecordingHandler:
    def __init__(self) -> None:
        self.commands: list[CreateReminderPlanCommand] = []

    async def create_reminder_plan(self, command: CreateReminderPlanCommand) -> ReminderPlan:
        self.commands.append(command)
        raise _Delegated


def _command(channel_policy: dict[str, object]) -> CreateReminderPlanCommand:
    return CreateReminderPlanCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        subject_party_id=uuid4(),
        purpose="appointment reminder",
        timezone="America/Sao_Paulo",
        daily_times=(time(9, 0),),
        channel_policy=channel_policy,
        template_key="appointment_reminder",
        template_version=1,
        idempotency_key=f"plan:{uuid4().hex}",
    )


def test_empty_channel_policy_is_rejected_before_persistence() -> None:
    handler = RecordingHandler()
    with pytest.raises(DeliveryConfigurationError, match="channels must be a non-empty list"):
        asyncio.run(create_reminder_plan(handler, _command({})))
    assert handler.commands == []


def test_unsupported_channel_is_rejected_before_persistence() -> None:
    handler = RecordingHandler()
    with pytest.raises(DeliveryConfigurationError, match="unsupported channel"):
        asyncio.run(
            create_reminder_plan(handler, _command({**USABLE_POLICY, "channels": ["pager"]}))
        )
    assert handler.commands == []


def test_parseable_channel_policy_is_delegated_to_handler() -> None:
    handler = RecordingHandler()
    with pytest.raises(_Delegated):
        asyncio.run(create_reminder_plan(handler, _command(USABLE_POLICY)))
    assert len(handler.commands) == 1
    assert handler.commands[0].channel_policy == USABLE_POLICY


def test_delivery_configuration_error_maps_to_422() -> None:
    status_code, body = resolve_communications_error(
        DeliveryConfigurationError("channel_policy.channels must be a non-empty list")
    )
    assert status_code == 422
    assert body.code == "invalid_channel_policy"
    assert body.resolution.value == "fix_request"
