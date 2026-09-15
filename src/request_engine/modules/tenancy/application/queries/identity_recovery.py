from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext


@dataclass(frozen=True, slots=True)
class IdentityRecoveryCaseView:
    """Bounded operator view; never carries secrets, destinations or hashes."""

    case_id: UUID
    target_native_identity_id: UUID
    status: str
    delivery_status: str
    revision: int
    issuance_generation: int
    approval_expires_at: datetime | None
    proof_expires_at: datetime | None
    created_at: datetime
    approved_at: datetime | None
    issued_at: datetime | None
    consumed_at: datetime | None
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("case revision must be positive")
        if self.issuance_generation < 0:
            raise ValueError("issuance generation cannot be negative")


class IdentityRecoveryReadError(RuntimeError):
    """Bounded identity recovery read failure."""


class IdentityRecoveryReadForbidden(IdentityRecoveryReadError):
    pass


class IdentityRecoveryCaseNotFound(IdentityRecoveryReadError):
    pass


class IdentityRecoveryReadInvalid(IdentityRecoveryReadError):
    pass


@dataclass(frozen=True, slots=True)
class ListIdentityRecoveryCasesQuery:
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class GetIdentityRecoveryCaseQuery:
    case_id: UUID


class IdentityRecoveryReader(Protocol):
    async def list_cases(
        self,
        actor: PlatformActorContext,
        query: ListIdentityRecoveryCasesQuery,
    ) -> list[IdentityRecoveryCaseView]: ...

    async def get_case(
        self,
        actor: PlatformActorContext,
        query: GetIdentityRecoveryCaseQuery,
    ) -> IdentityRecoveryCaseView | None: ...
