"""Catalog booking-policy vocabulary validation and cross-module parse proof.

Catalog owns the vocabulary DTO. The oracle for the cross-module claim is
booking's own published parser: whatever catalog serializes must parse
identically in booking's `reservation_lifecycle_policy`.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from request_engine.modules.booking.domain.lifecycle_policy import (
    reservation_lifecycle_policy,
)
from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    ChannelPolicyInput,
)

PolicyInput = policy_commands.BookingPolicyInput


def _full_policy() -> policy_commands.BookingPolicyInput:
    return policy_commands.BookingPolicyInput(
        slot_step_minutes=15,
        attendance=policy_commands.BookingAttendancePolicyInput(
            confirmation_required=True,
            attendance_request_before_minutes=120,
            decline_action="cancel",
            no_show_after_minutes=20,
        ),
        communications=policy_commands.BookingCommunicationsPolicyInput(
            confirmation=True,
            reminders_before_minutes=(1440, 60),
            channel_policy=ChannelPolicyInput(
                channels=("email", "whatsapp"),
                provider_key="provider",
            ),
        ),
        slot_recovery=policy_commands.BookingSlotRecoveryPolicyInput(
            enabled=True,
            minimum_lead_minutes=45,
        ),
    )


def _command(**overrides: object) -> policy_commands.SetOfferingVersionBookingPolicyCommand:
    values: dict[str, object] = {
        "organization_id": uuid4(),
        "principal_id": uuid4(),
        "authority_party_id": uuid4(),
        "offering_version_id": uuid4(),
        "expected_revision": 0,
        "policy": _full_policy(),
        "idempotency_key": "key-1",
    }
    values.update(overrides)
    return policy_commands.SetOfferingVersionBookingPolicyCommand(**values)  # type: ignore[arg-type]


class RecordingHandler:
    def __init__(self) -> None:
        self.commands: list[policy_commands.SetOfferingVersionBookingPolicyCommand] = []

    async def set_offering_version_booking_policy(
        self,
        command: policy_commands.SetOfferingVersionBookingPolicyCommand,
    ) -> policy_commands.OfferingVersionBookingPolicyState:
        self.commands.append(command)
        return policy_commands.OfferingVersionBookingPolicyState(
            offering_version_id=command.offering_version_id,
            booking_policy_revision=command.expected_revision + 1,
            policy=command.policy,
        )


@pytest.mark.asyncio
async def test_valid_policy_reaches_handler() -> None:
    handler = RecordingHandler()
    command = _command()
    await policy_commands.set_offering_version_booking_policy(handler, command)
    assert handler.commands == [command]


@pytest.mark.asyncio
async def test_idempotency_key_is_required() -> None:
    handler = RecordingHandler()
    with pytest.raises(ValueError, match="idempotency_key"):
        await policy_commands.set_offering_version_booking_policy(
            handler, _command(idempotency_key="")
        )
    assert handler.commands == []


@pytest.mark.asyncio
async def test_negative_expected_revision_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected_revision"):
        await policy_commands.set_offering_version_booking_policy(
            RecordingHandler(), _command(expected_revision=-1)
        )


@pytest.mark.parametrize(
    "kind, message",
    [
        ("slot_step_minutes", "slot_step_minutes"),
        ("decline_action", "decline_action"),
        ("no_response_action", "no_response_action"),
        ("no_show_after_minutes", "no_show_after_minutes"),
        ("attendance_request_before_minutes", "attendance_request_before_minutes"),
        ("reminders_before_minutes", "reminders_before_minutes"),
        ("channel_policy_required", "channel_policy"),
        ("minimum_lead_minutes", "minimum_lead_minutes"),
        ("channels_empty", "channels must not be empty"),
        ("channels_unique", "channels must be unique"),
        ("reconcile_seconds", "reconcile_after_seconds"),
    ],
)
def test_invalid_vocabulary_is_rejected(kind: str, message: str) -> None:
    policy = _full_policy()
    if kind == "slot_step_minutes":
        policy = replace(policy, slot_step_minutes=0)
    elif kind == "decline_action":
        policy = replace(policy, attendance=replace(policy.attendance, decline_action="close"))
    elif kind == "no_response_action":
        policy = replace(policy, attendance=replace(policy.attendance, no_response_action="cancel"))
    elif kind == "no_show_after_minutes":
        policy = replace(policy, attendance=replace(policy.attendance, no_show_after_minutes=0))
    elif kind == "attendance_request_before_minutes":
        policy = replace(
            policy,
            attendance=replace(policy.attendance, attendance_request_before_minutes=-5),
        )
    elif kind == "reminders_before_minutes":
        policy = replace(
            policy,
            communications=replace(policy.communications, reminders_before_minutes=(0,)),
        )
    elif kind == "channel_policy_required":
        policy = replace(
            policy,
            communications=replace(policy.communications, confirmation=True, channel_policy=None),
        )
    elif kind == "minimum_lead_minutes":
        policy = replace(
            policy, slot_recovery=replace(policy.slot_recovery, minimum_lead_minutes=0)
        )
    elif kind == "channels_empty":
        policy = _with_channels(policy, ())
    elif kind == "channels_unique":
        policy = _with_channels(policy, ("email", "email"))
    elif kind == "reconcile_seconds":
        policy = _with_reconcile_seconds(policy, 1)
    with pytest.raises(ValueError, match=message):
        policy_commands.validate_booking_policy(policy)


def _with_channels(policy: PolicyInput, channels: tuple[str, ...]) -> PolicyInput:
    assert policy.communications.channel_policy is not None
    return replace(
        policy,
        communications=replace(
            policy.communications,
            channel_policy=replace(policy.communications.channel_policy, channels=channels),
        ),
    )


def _with_reconcile_seconds(policy: PolicyInput, seconds: int) -> PolicyInput:
    assert policy.communications.channel_policy is not None
    return replace(
        policy,
        communications=replace(
            policy.communications,
            channel_policy=replace(
                policy.communications.channel_policy, reconcile_after_seconds=seconds
            ),
        ),
    )


def test_serialized_policy_parses_identically_in_booking() -> None:
    policy_json = policy_commands.booking_policy_json(_full_policy())

    parsed = reservation_lifecycle_policy(policy_json)

    assert parsed.attendance.confirmation_required is True
    assert parsed.attendance.attendance_request_before_minutes == 120
    assert parsed.attendance.decline_action == "cancel"
    assert parsed.attendance.no_response_action == "keep"
    assert parsed.attendance.no_show_after_minutes == 20
    assert parsed.communications.confirmation is True
    assert parsed.communications.reminders_before_minutes == (1440, 60)
    assert parsed.communications.channel_policy == {
        "channels": ["email", "whatsapp"],
        "reconcile_after_seconds": 300,
        "retry_after_seconds": 60,
        "provider_key": "provider",
    }
    assert parsed.slot_recovery.enabled is True
    assert parsed.slot_recovery.minimum_lead_minutes == 45


def test_serialized_default_policy_parses_identically_in_booking() -> None:
    policy_json = policy_commands.booking_policy_json(policy_commands.BookingPolicyInput())
    parsed = reservation_lifecycle_policy(policy_json)
    assert parsed.attendance.decline_action == "keep"
    assert parsed.communications.reminders_before_minutes == ()
    assert parsed.communications.channel_policy == {}
    assert parsed.slot_recovery.enabled is False
