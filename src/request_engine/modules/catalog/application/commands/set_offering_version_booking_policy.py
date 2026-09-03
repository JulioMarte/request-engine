from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    ChannelPolicyInput,
)

DeclineAction = Literal["keep", "cancel"]
NoResponseAction = Literal["keep"]


@dataclass(frozen=True, slots=True)
class BookingAttendancePolicyInput:
    confirmation_required: bool = False
    attendance_request_before_minutes: int | None = None
    decline_action: DeclineAction = "keep"
    no_response_action: NoResponseAction = "keep"
    no_show_after_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class BookingCommunicationsPolicyInput:
    confirmation: bool = False
    reminders_before_minutes: tuple[int, ...] = ()
    channel_policy: ChannelPolicyInput | None = None


@dataclass(frozen=True, slots=True)
class BookingSlotRecoveryPolicyInput:
    enabled: bool = False
    minimum_lead_minutes: int = 30


@dataclass(frozen=True, slots=True)
class BookingPolicyInput:
    slot_step_minutes: int = 30
    attendance: BookingAttendancePolicyInput = field(default_factory=BookingAttendancePolicyInput)
    communications: BookingCommunicationsPolicyInput = field(
        default_factory=BookingCommunicationsPolicyInput
    )
    slot_recovery: BookingSlotRecoveryPolicyInput = field(
        default_factory=BookingSlotRecoveryPolicyInput
    )


@dataclass(frozen=True, slots=True)
class SetOfferingVersionBookingPolicyCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_version_id: UUID
    expected_revision: int
    policy: BookingPolicyInput
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfferingVersionBookingPolicyState:
    offering_version_id: UUID
    booking_policy_revision: int
    policy: BookingPolicyInput


class SetOfferingVersionBookingPolicyHandler(Protocol):
    async def set_offering_version_booking_policy(
        self, command: SetOfferingVersionBookingPolicyCommand
    ) -> OfferingVersionBookingPolicyState: ...


async def set_offering_version_booking_policy(
    handler: SetOfferingVersionBookingPolicyHandler,
    command: SetOfferingVersionBookingPolicyCommand,
) -> OfferingVersionBookingPolicyState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision < 0:
        raise ValueError("expected_revision must be zero (bootstrap policy) or positive")
    validate_booking_policy(command.policy)
    return await handler.set_offering_version_booking_policy(command)


def validate_booking_policy(policy: BookingPolicyInput) -> None:
    if policy.slot_step_minutes <= 0:
        raise ValueError("slot_step_minutes must be positive")
    attendance = policy.attendance
    if attendance.attendance_request_before_minutes is not None and (
        attendance.attendance_request_before_minutes <= 0
    ):
        raise ValueError("attendance.attendance_request_before_minutes must be positive")
    if attendance.decline_action not in ("keep", "cancel"):
        raise ValueError("attendance.decline_action must be keep or cancel")
    if attendance.no_response_action != "keep":
        raise ValueError("attendance.no_response_action supports only keep in V3 baseline")
    if attendance.no_show_after_minutes is not None and attendance.no_show_after_minutes <= 0:
        raise ValueError("attendance.no_show_after_minutes must be positive")
    communications = policy.communications
    if any(value <= 0 for value in communications.reminders_before_minutes):
        raise ValueError("communications.reminders_before_minutes must contain positive integers")
    if policy.slot_recovery.minimum_lead_minutes <= 0:
        raise ValueError("slot_recovery.minimum_lead_minutes must be positive")
    communications_enabled = (
        communications.confirmation
        or bool(communications.reminders_before_minutes)
        or attendance.confirmation_required
    )
    if communications_enabled and communications.channel_policy is None:
        raise ValueError(
            "communications.channel_policy is required when booking communications are enabled"
        )
    channel_policy = communications.channel_policy
    if channel_policy is None:
        return
    if not channel_policy.channels:
        raise ValueError("communications.channel_policy.channels must not be empty")
    if len(set(channel_policy.channels)) != len(channel_policy.channels):
        raise ValueError("communications.channel_policy.channels must be unique")
    if channel_policy.provider_key is not None and not channel_policy.provider_key.strip():
        raise ValueError("communications.channel_policy.provider_key must not be blank")
    for field_name, value in (
        ("reconcile_after_seconds", channel_policy.reconcile_after_seconds),
        ("retry_after_seconds", channel_policy.retry_after_seconds),
    ):
        if value < 30 or value > 86400:
            raise ValueError(
                f"communications.channel_policy.{field_name} must be between 30 and 86400"
            )


def booking_policy_json(policy: BookingPolicyInput) -> dict[str, object]:
    channel_policy: dict[str, object] = {}
    channels = policy.communications.channel_policy
    if channels is not None:
        channel_policy = {
            "channels": list(channels.channels),
            "reconcile_after_seconds": channels.reconcile_after_seconds,
            "retry_after_seconds": channels.retry_after_seconds,
        }
        if channels.provider_key is not None:
            channel_policy["provider_key"] = channels.provider_key.strip()
    return {
        "slot_step_minutes": policy.slot_step_minutes,
        "attendance": {
            "confirmation_required": policy.attendance.confirmation_required,
            "attendance_request_before_minutes": (
                policy.attendance.attendance_request_before_minutes
            ),
            "decline_action": policy.attendance.decline_action,
            "no_response_action": policy.attendance.no_response_action,
            "no_show_after_minutes": policy.attendance.no_show_after_minutes,
        },
        "communications": {
            "confirmation": policy.communications.confirmation,
            "reminders_before_minutes": list(policy.communications.reminders_before_minutes),
            "channel_policy": channel_policy,
        },
        "slot_recovery": {
            "enabled": policy.slot_recovery.enabled,
            "minimum_lead_minutes": policy.slot_recovery.minimum_lead_minutes,
        },
    }
