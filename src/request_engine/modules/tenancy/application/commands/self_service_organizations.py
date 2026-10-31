"""Entitled native humans create organizations they control (ADR 0021).

Pre-tenant command: it runs on authenticated subject evidence, never on an
ActorContext, and the account entitlement is resolved and locked in PostgreSQL.
"""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NATIVE_INITIAL_CONTROLLER_POLICY,
)
from request_engine.modules.tenancy.domain.account_entitlement import (
    DEFAULT_CURRENCY,
    DEFAULT_LOCALE,
    DEFAULT_TIMEZONE,
    validate_currency,
    validate_display_name,
    validate_locale,
    validate_organization_key,
    validate_timezone,
)
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject


class SelfServiceOrganizationError(RuntimeError):
    pass


class SelfServiceOrganizationForbidden(SelfServiceOrganizationError):
    """No active entitlement, no normal native session or a non-HUMAN subject."""


class SelfServiceOrganizationLimitReached(SelfServiceOrganizationError):
    pass


class SelfServiceOrganizationKeyUnavailable(SelfServiceOrganizationError):
    pass


class SelfServiceOrganizationIdempotencyConflict(SelfServiceOrganizationError):
    pass


class SelfServiceOrganizationInvalid(SelfServiceOrganizationError):
    pass


@dataclass(frozen=True, slots=True)
class CreateSelfServiceOrganizationCommand:
    display_name: str
    idempotency_key: str
    organization_key: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    locale: str = DEFAULT_LOCALE
    currency: str = DEFAULT_CURRENCY
    initial_controller_policy: str = field(default=NATIVE_INITIAL_CONTROLLER_POLICY, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "display_name", validate_display_name(self.display_name))
        if self.organization_key is not None:
            validate_organization_key(self.organization_key)
        validate_timezone(self.timezone)
        validate_locale(self.locale)
        validate_currency(self.currency)
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency_key must contain 1 to 200 characters")


@dataclass(frozen=True, slots=True)
class SelfServiceOrganizationCreated:
    organization_id: UUID
    organization_party_id: UUID
    controller_principal_id: UUID
    controller_binding_id: UUID
    membership_id: UUID | None
    organization_key: str
    display_name: str
    default_timezone: str
    default_locale: str
    default_currency: str
    initial_controller_policy: str
    created: bool
    max_organizations: int
    organizations_created: int
    entitlement_id: UUID


@dataclass(frozen=True, slots=True)
class AccountEntitlementView:
    entitlement_id: UUID
    status: str
    max_organizations: int
    organizations_created: int
    revision: int

    @property
    def remaining(self) -> int:
        if self.status != "active":
            return 0
        return max(0, self.max_organizations - self.organizations_created)


class SelfServiceAccountCommands(Protocol):
    async def read_entitlement(
        self, authenticated: AuthenticatedHttpSubject
    ) -> AccountEntitlementView | None: ...

    async def create_organization(
        self,
        authenticated: AuthenticatedHttpSubject,
        command: CreateSelfServiceOrganizationCommand,
        *,
        correlation_id: UUID | None = None,
    ) -> SelfServiceOrganizationCreated: ...
