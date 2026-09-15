from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext


class PlatformProvisionerReadError(RuntimeError):
    """Bounded platform provisioner read failure."""


class PlatformProvisionerReadForbidden(PlatformProvisionerReadError):
    pass


class PlatformProvisionerNotFound(PlatformProvisionerReadError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformProvisionerSummary:
    principal_id: UUID
    principal_kind: str
    active: bool
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None
    identity_authority_id: UUID | None
    binding_subject_id: str | None
    capabilities: tuple[str, ...]
    provenance_reference: str | None
    granted_at: datetime | None


@dataclass(frozen=True, slots=True)
class ListPlatformProvisionersQuery:
    after: UUID | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class GetPlatformProvisionerQuery:
    principal_id: UUID


class PlatformProvisionerReader(Protocol):
    async def list_provisioners(
        self,
        actor: PlatformActorContext,
        query: ListPlatformProvisionersQuery,
    ) -> tuple[PlatformProvisionerSummary, ...]: ...

    async def get_provisioner(
        self,
        actor: PlatformActorContext,
        query: GetPlatformProvisionerQuery,
    ) -> PlatformProvisionerSummary | None: ...
