from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext

NATIVE_IDENTITY_READ_CAPABILITY = "platform.identity.read"


class NativeIdentityReadError(RuntimeError):
    """Bounded private native-identity read failure."""


class NativeIdentityReadForbidden(NativeIdentityReadError):
    pass


class NativeIdentityReadNotFound(NativeIdentityReadError):
    pass


class NativeIdentityReadInvalid(NativeIdentityReadError):
    pass


@dataclass(frozen=True, slots=True)
class NativeIdentityView:
    """Private native-identity projection; never carries a login handle or verifier."""

    native_identity_id: UUID
    identity_authority_id: UUID
    status: str
    revision: int
    created_at: datetime
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class ListNativeIdentitiesQuery:
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class GetNativeIdentityQuery:
    native_identity_id: UUID


class NativeIdentityReader(Protocol):
    async def list_identities(
        self,
        actor: PlatformActorContext,
        query: ListNativeIdentitiesQuery,
    ) -> tuple[NativeIdentityView, ...]: ...

    async def read_identity(
        self,
        actor: PlatformActorContext,
        query: GetNativeIdentityQuery,
    ) -> NativeIdentityView: ...
