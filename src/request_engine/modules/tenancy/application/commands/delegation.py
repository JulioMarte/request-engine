from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class CreateDelegationCommand:
    delegate_principal_id: UUID
    purpose: str
    allowed_capabilities: tuple[str, ...]
    not_before: datetime
    expires_at: datetime
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateDelegationResult:
    delegation_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class RevokeDelegationCommand:
    delegation_id: UUID
    expected_revision: int
    provenance_reference: str
    idempotency_key: str


class DelegationCommands(Protocol):
    async def create_delegation(
        self,
        actor: ActorContext,
        command: CreateDelegationCommand,
    ) -> CreateDelegationResult: ...

    async def revoke_delegation(
        self,
        actor: ActorContext,
        command: RevokeDelegationCommand,
    ) -> int: ...
