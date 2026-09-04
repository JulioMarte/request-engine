"""Validation of the optional weekly_availability bootstrap input."""

from dataclasses import replace
from datetime import date, time
from uuid import uuid4

import pytest

from request_engine.modules.booking.application.commands.create_resource import (
    CreateResourceCommand,
    ResourceBootstrapState,
    create_resource,
    validate_availability_window,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
)


def _command(windows: tuple[ResourceLocationAvailabilityWindow, ...]) -> CreateResourceCommand:
    return CreateResourceCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        authority_party_id=uuid4(),
        location_id=uuid4(),
        resource_key="resource",
        display_name="Resource",
        capacity_model="exclusive",
        capacity_units=1,
        capability_ids=(),
        weekly_availability=windows,
        idempotency_key="key-1",
    )


class RecordingHandler:
    def __init__(self) -> None:
        self.commands: list[CreateResourceCommand] = []

    async def create_resource(self, command: CreateResourceCommand) -> ResourceBootstrapState:
        self.commands.append(command)
        return ResourceBootstrapState(
            resource_id=uuid4(),
            resource_key=command.resource_key,
            display_name=command.display_name,
            capacity_model=command.capacity_model,
            capacity_units=command.capacity_units,
            availability_revision=1,
            capability_ids=command.capability_ids,
        )


def _valid_window() -> ResourceLocationAvailabilityWindow:
    return ResourceLocationAvailabilityWindow(
        weekday=0, local_start=time(9, 0), local_end=time(17, 0)
    )


@pytest.mark.asyncio
async def test_valid_weekly_availability_reaches_handler() -> None:
    handler = RecordingHandler()
    command = _command((_valid_window(),))
    await create_resource(handler, command)
    assert handler.commands == [command]


@pytest.mark.asyncio
async def test_empty_weekly_availability_remains_valid() -> None:
    handler = RecordingHandler()
    await create_resource(handler, _command(()))
    assert len(handler.commands) == 1


@pytest.mark.parametrize("weekday", [-1, 7])
def test_weekday_must_be_within_week(weekday: int) -> None:
    with pytest.raises(ValueError, match="weekday"):
        validate_availability_window(replace(_valid_window(), weekday=weekday))


def test_window_start_must_precede_end() -> None:
    with pytest.raises(ValueError, match="local_start"):
        validate_availability_window(
            replace(
                _valid_window(),
                local_start=time(17, 0),
                local_end=time(9, 0),
            )
        )


def test_valid_until_cannot_precede_valid_from() -> None:
    with pytest.raises(ValueError, match="valid_until"):
        validate_availability_window(
            replace(
                _valid_window(),
                valid_from=date(2030, 6, 2),
                valid_until=date(2030, 6, 1),
            )
        )
