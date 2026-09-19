from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class IdentityLinkIntentSnapshot:
    """Tenant-scoped persisted intent used to derive trusted link authority."""

    intent_id: UUID
    actor_principal_id: UUID
    target_authority_id: UUID
    target_authority_kind: str
    actor_binding_revision: int
    status: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.actor_binding_revision < 1:
            raise ValueError("actor binding revision must be positive")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


class IdentityLinkIntentReader(Protocol):
    async def read_intent(
        self,
        actor: ActorContext,
        *,
        intent_id: UUID,
    ) -> IdentityLinkIntentSnapshot | None: ...
