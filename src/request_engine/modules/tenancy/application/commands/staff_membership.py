from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext


class StaffMembershipTargetStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class InviteNativeStaffCommand:
    identity_authority_id: UUID
    native_identity_id: UUID
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class InviteNativeStaffResult:
    membership_id: UUID
    principal_id: UUID
    binding_id: UUID


@dataclass(frozen=True, slots=True)
class ReplaceStaffAuthorityCommand:
    membership_id: UUID
    expected_authority_revision: int
    desired_capabilities: tuple[str, ...]
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TransitionStaffMembershipCommand:
    membership_id: UUID
    expected_revision: int
    target_status: StaffMembershipTargetStatus
    provenance_reference: str
    idempotency_key: str


class StaffMembershipCommands(Protocol):
    async def invite_native_staff(
        self,
        actor: ActorContext,
        command: InviteNativeStaffCommand,
    ) -> InviteNativeStaffResult: ...

    async def replace_staff_authority(
        self,
        actor: ActorContext,
        command: ReplaceStaffAuthorityCommand,
    ) -> int: ...

    async def transition_staff_membership(
        self,
        actor: ActorContext,
        command: TransitionStaffMembershipCommand,
    ) -> int: ...
