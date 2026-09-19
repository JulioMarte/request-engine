"""Provider-neutral platform secret-store contract.

This boundary is intentionally smaller than a configuration system. PostgreSQL
owns non-secret configuration/revisions; a PlatformSecretStore owns reversible
secret material. Human/admin APIs may write, rotate or revoke secrets but must
never replay plaintext after the write. Runtime consumers resolve values through
this technical boundary only.

Backends derive their own paths from opaque secret IDs. Callers never provide a
backend path, which prevents path traversal and cross-purpose secret access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class PlatformSecretStoreError(RuntimeError):
    """Base class for platform secret-store failures."""


class PlatformSecretStoreUnavailable(PlatformSecretStoreError):
    """The backend could not be reached or is temporarily unavailable."""


class PlatformSecretConflict(PlatformSecretStoreError):
    """The expected secret version did not match the authoritative backend."""


class PlatformSecretNotFound(PlatformSecretStoreError):
    """The requested opaque secret ID has no active backend value."""


@dataclass(frozen=True, slots=True)
class PlatformSecretMetadata:
    secret_id: UUID
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("secret version must be positive")


class PlatformSecretStore(Protocol):
    async def write(
        self,
        *,
        secret_id: UUID,
        value: str,
        expected_version: int | None,
    ) -> PlatformSecretMetadata:
        """Create or rotate one secret.

        expected_version=None means create-if-absent. Rotation requires the
        exact currently observed version. Implementations must fail closed on a
        stale version rather than silently overwriting.
        """
        ...

    async def resolve(self, *, secret_id: UUID) -> str:
        """Return plaintext only to a trusted runtime consumer."""
        ...

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        """Return metadata without plaintext."""
        ...

    async def revoke(self, *, secret_id: UUID) -> None:
        """Destroy/revoke the secret identified by this opaque ID."""
        ...
