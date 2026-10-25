"""Platform-issued owner account invitations and their public self-enrollment (ADR 0021)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.account_entitlement import (
    MAX_ORGANIZATIONS_PER_INVITATION,
    AccountInvitationDelivery,
    normalize_account_email,
)
from request_engine.platform.secrets.delivery import DeliveryOutcome
from request_engine.platform.security.platform_context import PlatformActorContext


class AccountInvitationError(RuntimeError):
    pass


class AccountInvitationForbidden(AccountInvitationError):
    pass


class AccountInvitationInvalid(AccountInvitationError):
    """Unknown, expired, revoked or already used code, or invalid input."""


class AccountInvitationConflict(AccountInvitationError):
    pass


class AccountInvitationNotFound(AccountInvitationError):
    pass


class AccountInvitationRevisionConflict(AccountInvitationError):
    pass


class AccountInvitationDeliveryUnavailable(AccountInvitationError):
    """Email delivery is not composed; nothing was created."""


class AccountLoginUnavailable(AccountInvitationError):
    pass


class AccountPasswordInvalid(AccountInvitationError):
    pass


class AccountEnrollmentUnavailable(AccountInvitationError):
    pass


@dataclass(frozen=True, slots=True)
class CreateAccountInvitationCommand:
    delivery: AccountInvitationDelivery
    email: str | None
    max_organizations: int
    expires_in_hours: int
    provenance_reference: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if (self.delivery is AccountInvitationDelivery.EMAIL) != (self.email is not None):
            raise ValueError("email is required for email delivery and forbidden otherwise")
        if self.email is not None:
            object.__setattr__(self, "email", normalize_account_email(self.email))
        if not 1 <= self.max_organizations <= MAX_ORGANIZATIONS_PER_INVITATION:
            raise ValueError("max_organizations must be between 1 and 10")
        if not 1 <= self.expires_in_hours <= 168:
            raise ValueError("expires_in_hours must be between 1 and 168")
        if not 1 <= len(self.provenance_reference.strip()) <= 500:
            raise ValueError("provenance_reference must contain 1 to 500 characters")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency_key must contain 1 to 200 characters")


@dataclass(frozen=True, slots=True)
class AccountInvitationIssued:
    invitation_id: UUID
    created: bool
    status: str
    revision: int
    delivery_status: str | None
    expires_at: datetime
    raw_token: str | None


@dataclass(frozen=True, slots=True)
class RevokeAccountInvitationCommand:
    invitation_id: UUID
    expected_revision: int
    reason_code: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be at least 1")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency_key must contain 1 to 200 characters")


@dataclass(frozen=True, slots=True)
class AccountInvitationRevoked:
    invitation_id: UUID
    status: str
    revision: int


@dataclass(frozen=True, slots=True)
class AccountInvitationSummary:
    invitation_id: UUID
    delivery: str
    email: str | None
    max_organizations: int
    status: str
    expired: bool
    revision: int
    delivery_status: str | None
    invited_by_principal_id: UUID
    native_identity_id: UUID | None
    entitlement_id: UUID | None
    organizations_created: int | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class EnrollAccountInvitationCommand:
    raw_token: str
    login_handle: str
    password: str

    def __post_init__(self) -> None:
        if not 20 <= len(self.raw_token) <= 200:
            raise ValueError("invitation token is invalid")


@dataclass(frozen=True, slots=True)
class AccountInvitationEnrollment:
    invitation_id: UUID
    native_identity_id: UUID
    login_handle: str
    entitlement_id: UUID
    max_organizations: int


class AccountInvitationMailer(Protocol):
    """Closed-purpose outbound port; the caller holds no database lock while sending."""

    async def send(
        self, *, secret: str, destination_reference: str, idempotency_key: str
    ) -> DeliveryOutcome: ...


class AccountInvitationEnrollmentCommands(Protocol):
    async def enroll(
        self, command: EnrollAccountInvitationCommand
    ) -> AccountInvitationEnrollment: ...


class PlatformAccountInvitationCommands(Protocol):
    async def create(
        self, actor: PlatformActorContext, command: CreateAccountInvitationCommand
    ) -> AccountInvitationIssued: ...

    async def revoke(
        self, actor: PlatformActorContext, command: RevokeAccountInvitationCommand
    ) -> AccountInvitationRevoked: ...

    async def list(
        self,
        actor: PlatformActorContext,
        *,
        invitation_id: UUID | None,
        after: UUID | None,
        limit: int,
    ) -> tuple[AccountInvitationSummary, ...]: ...
