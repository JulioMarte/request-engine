from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

IDENTITY_BINDING_CAPABILITY = "identity.bind"


class IdentityBindingTargetStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class TransitionIdentityBindingCommand:
    binding_id: UUID
    expected_revision: int
    target_status: IdentityBindingTargetStatus
    provenance_reference: str
    idempotency_key: str


class IdentityBindingCommands(Protocol):
    async def transition_identity_binding(
        self,
        actor: ActorContext,
        command: TransitionIdentityBindingCommand,
    ) -> int: ...
