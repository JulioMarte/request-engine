from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PlatformOwnerLifecycleError(RuntimeError):
    pass


class PlatformOwnerForbidden(PlatformOwnerLifecycleError):
    pass


class PlatformOwnerConflict(PlatformOwnerLifecycleError):
    pass


class PlatformOwnerInvalid(PlatformOwnerLifecycleError):
    pass


class PlatformOwnerNotFound(PlatformOwnerLifecycleError):
    pass


class PlatformOwnerRevisionConflict(PlatformOwnerLifecycleError):
    pass


class PlatformOwnerInvitationInvalid(PlatformOwnerLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformOwnerInvitationIssued:
    invitation_id: UUID
    status: str
    expires_at: datetime
    revision: int
    invitation_token: str | None


@dataclass(frozen=True, slots=True)
class PlatformOwnerInvitationState:
    invitation_id: UUID
    status: str
    native_identity_id: UUID | None
    expires_at: datetime
    policy_key: str
    revision: int


@dataclass(frozen=True, slots=True)
class PlatformOwnerIdentityEnrolled:
    native_identity_id: UUID


@dataclass(frozen=True, slots=True)
class PlatformOwnerActivated:
    principal_id: UUID
    binding_id: UUID
    native_identity_id: UUID
    policy_key: str


class PlatformOwnerLifecycleAction(StrEnum):
    SUSPEND = "suspend"
    REACTIVATE = "reactivate"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True)
class PlatformOwnerSummary:
    principal_id: UUID
    active: bool
    authority_revision: int
    binding_id: UUID
    binding_status: str
    native_identity_id: UUID
    policy_version: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlatformOwnerLifecycleResult:
    fact_id: UUID
    principal_id: UUID
    action: PlatformOwnerLifecycleAction
    authority_revision: int
    binding_id: UUID
    binding_status: str
