from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.integration_governance import IntegrationStatus
from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class IntegrationCredentialSummary:
    credential_id: UUID
    status: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrationSummary:
    principal_id: UUID
    authority_revision: int
    status: IntegrationStatus
    binding_id: UUID | None
    workload_identity_id: UUID | None
    identity_authority_id: UUID | None
    capabilities: tuple[str, ...]
    credentials: tuple[IntegrationCredentialSummary, ...]
    provenance_complete: bool


@dataclass(frozen=True, slots=True)
class ListIntegrationsQuery:
    after: UUID | None = None
    limit: int = 50


class IntegrationGovernanceReader(Protocol):
    async def read_integration(
        self,
        actor: ActorContext,
        principal_id: UUID,
    ) -> IntegrationSummary: ...

    async def list_integrations(
        self,
        actor: ActorContext,
        query: ListIntegrationsQuery,
    ) -> tuple[IntegrationSummary, ...]: ...
