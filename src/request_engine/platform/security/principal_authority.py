from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class PrincipalAuthorityMaterializationError(RuntimeError):
    """Persisted Principal authority cannot be safely interpreted by this runtime."""


@dataclass(frozen=True, slots=True)
class PrincipalAuthoritySnapshot:
    """One MVCC-consistent snapshot of a tenant Principal and its standing authority."""

    principal_id: UUID
    principal_kind: str
    authority_revision: int
    capabilities: frozenset[str]
    delegable_capabilities: frozenset[str]


class PrincipalAuthorityReader(Protocol):
    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None: ...
