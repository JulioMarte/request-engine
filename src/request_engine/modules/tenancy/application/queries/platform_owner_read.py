"""Safe administrative owner projections, distinct from one-time invitation delivery."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class PlatformOwnerReadError(RuntimeError):
    pass


class PlatformOwnerReadForbidden(PlatformOwnerReadError):
    pass


class PlatformOwnerReadNotFound(PlatformOwnerReadError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformOwnerReadQuery:
    resource_id: UUID | None = None
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class PlatformOwnerSummary:
    principal_id: UUID
    active: bool
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlatformOwnerInvitationSummary:
    invitation_id: UUID
    status: str
    revision: int
    native_identity_id: UUID | None
    created_at: datetime
    expires_at: datetime
    enrolled_at: datetime | None
    consumed_at: datetime | None
    revoked_at: datetime | None
    expired: bool
