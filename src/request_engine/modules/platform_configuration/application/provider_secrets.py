from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext


@dataclass(frozen=True, slots=True)
class ProviderSecretReference:
    binding_id: UUID
    secret_id: UUID
    purpose: str
    backend: str
    backend_version: int
    status: str
    revision: int


class ProviderSecretResolver(Protocol):
    async def resolve(
        self,
        actor: PlatformActorContext,
        *,
        binding_id: UUID,
        capability_key: str,
    ) -> ProviderSecretReference: ...
