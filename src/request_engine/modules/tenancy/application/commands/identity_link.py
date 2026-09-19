from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

IDENTITY_LINK_CAPABILITY = "identity.link_self"


@dataclass(frozen=True, slots=True)
class CreateIdentityLinkIntentCommand:
    intent_id: UUID
    actor_binding_id: UUID
    target_authority_id: UUID
    nonce_digest: str
    ttl_seconds: int
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ConfirmIdentityLinkIntentCommand:
    intent_id: UUID
    expected_actor_binding_revision: int
    binding_id: UUID
    provenance_reference: str
    idempotency_key: str
    native_identity_id: UUID | None = None
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityLinkIntentReceipt:
    intent_id: UUID
    expires_at: datetime
    target_authority_id: UUID


@dataclass(frozen=True, slots=True)
class IdentityLinkBindingReceipt:
    binding_id: UUID
    principal_id: UUID
    binding_revision: int


class IdentityLinkCommands(Protocol):
    async def create_identity_link_intent(
        self,
        actor: ActorContext,
        command: CreateIdentityLinkIntentCommand,
    ) -> IdentityLinkIntentReceipt: ...

    async def confirm_identity_link_intent(
        self,
        actor: ActorContext,
        command: ConfirmIdentityLinkIntentCommand,
    ) -> IdentityLinkBindingReceipt: ...
