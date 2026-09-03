from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.authority import AuthorityKind


@dataclass(frozen=True, slots=True)
class BootstrapOperationalAuthorityCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class BootstrapOperationalAuthorityState:
    authority_party_id: UUID
    principal_id: UUID
    authority_kind: AuthorityKind
    scope_keys: tuple[str, ...]


class BootstrapOperationalAuthorityHandler(Protocol):
    async def bootstrap_operational_authority(
        self,
        command: BootstrapOperationalAuthorityCommand,
    ) -> BootstrapOperationalAuthorityState: ...


async def bootstrap_operational_authority(
    handler: BootstrapOperationalAuthorityHandler,
    command: BootstrapOperationalAuthorityCommand,
) -> BootstrapOperationalAuthorityState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.bootstrap_operational_authority(command)
