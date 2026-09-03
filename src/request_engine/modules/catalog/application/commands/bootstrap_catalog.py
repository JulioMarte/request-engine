from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateResourceCapabilityCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    capability_key: str
    display_name: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourceCapabilityState:
    capability_id: UUID
    capability_key: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OfferingRequirementInput:
    capability_id: UUID
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class ChannelPolicyInput:
    channels: tuple[Literal["email", "phone", "sms", "voice", "whatsapp"], ...]
    provider_key: str | None = None
    reconcile_after_seconds: int = 300
    retry_after_seconds: int = 60


@dataclass(frozen=True, slots=True)
class ReservationPolicyInput:
    confirmation: bool = False
    reminders_before_minutes: tuple[int, ...] = ()
    channel_policy: ChannelPolicyInput | None = None
    attendance_confirmation_required: bool = False
    attendance_request_before_minutes: int | None = None
    decline_action: Literal["keep", "cancel"] = "keep"
    no_show_after_minutes: int | None = None
    slot_recovery_enabled: bool = False
    slot_recovery_minimum_lead_minutes: int = 30


@dataclass(frozen=True, slots=True)
class CreateOfferingCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_key: str
    display_name: str
    description: str | None
    duration_minutes: int
    bookable: bool
    requestable: bool
    slot_step_minutes: int
    requirements: tuple[OfferingRequirementInput, ...]
    reservation_policy: ReservationPolicyInput
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfferingBootstrapState:
    offering_id: UUID
    offering_version_id: UUID
    offering_key: str
    version: int
    requirement_ids: tuple[UUID, ...]


class CatalogBootstrapHandler(Protocol):
    async def create_resource_capability(
        self, command: CreateResourceCapabilityCommand
    ) -> ResourceCapabilityState: ...

    async def create_offering(self, command: CreateOfferingCommand) -> OfferingBootstrapState: ...


async def create_resource_capability(
    handler: CatalogBootstrapHandler,
    command: CreateResourceCapabilityCommand,
) -> ResourceCapabilityState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.capability_key.strip() or not command.display_name.strip():
        raise ValueError("capability_key and display_name are required")
    return await handler.create_resource_capability(command)


async def create_offering(
    handler: CatalogBootstrapHandler,
    command: CreateOfferingCommand,
) -> OfferingBootstrapState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.offering_key.strip() or not command.display_name.strip():
        raise ValueError("offering_key and display_name are required")
    if command.duration_minutes <= 0 or command.slot_step_minutes <= 0:
        raise ValueError("duration_minutes and slot_step_minutes must be positive")
    if len({item.capability_id for item in command.requirements}) != len(command.requirements):
        raise ValueError("requirements must not repeat capability_id")
    if any(item.quantity <= 0 for item in command.requirements):
        raise ValueError("requirement quantity must be positive")
    _validate_reservation_policy(command.reservation_policy)
    return await handler.create_offering(command)


def _validate_reservation_policy(policy: ReservationPolicyInput) -> None:
    if any(value <= 0 for value in policy.reminders_before_minutes):
        raise ValueError("reminders_before_minutes must contain positive integers")
    if policy.attendance_request_before_minutes is not None and policy.attendance_request_before_minutes <= 0:
        raise ValueError("attendance_request_before_minutes must be positive")
    if policy.no_show_after_minutes is not None and policy.no_show_after_minutes <= 0:
        raise ValueError("no_show_after_minutes must be positive")
    if policy.slot_recovery_minimum_lead_minutes <= 0:
        raise ValueError("slot_recovery_minimum_lead_minutes must be positive")
    channel_policy = policy.channel_policy
    communications_enabled = policy.confirmation or bool(policy.reminders_before_minutes) or policy.attendance_confirmation_required
    if communications_enabled and channel_policy is None:
        raise ValueError("channel_policy is required when reservation communications are enabled")
    if channel_policy is None:
        return
    if not channel_policy.channels:
        raise ValueError("channel_policy.channels must not be empty")
    if len(set(channel_policy.channels)) != len(channel_policy.channels):
        raise ValueError("channel_policy.channels must be unique")
    if channel_policy.provider_key is not None and not channel_policy.provider_key.strip():
        raise ValueError("channel_policy.provider_key must not be blank")
    for field, value in (
        ("reconcile_after_seconds", channel_policy.reconcile_after_seconds),
        ("retry_after_seconds", channel_policy.retry_after_seconds),
    ):
        if value < 30 or value > 86400:
            raise ValueError(f"channel_policy.{field} must be between 30 and 86400")
