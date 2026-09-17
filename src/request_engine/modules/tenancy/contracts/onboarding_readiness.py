from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdentityReadinessFacts:
    active_controller: bool
    authenticatable_controller: bool


@dataclass(frozen=True, slots=True)
class TenantControlReadinessFacts:
    current_policy_ready: bool
    recorded_policy_key: str | None


@dataclass(frozen=True, slots=True)
class StaffAdministrationReadinessFacts:
    available: bool


@dataclass(frozen=True, slots=True)
class RecoveryReadinessFacts:
    known: bool
    ready: bool | None


@dataclass(frozen=True, slots=True)
class OnboardingIdentityFacts:
    identity: IdentityReadinessFacts
    tenant_control: TenantControlReadinessFacts
    staff_administration: StaffAdministrationReadinessFacts
    recovery: RecoveryReadinessFacts
    observed_at: datetime
    controller_authority_revision: int | None
    policy_revision: int | None


class BusinessPartyReader(Protocol):
    """Publish the tenancy-owned business-Party readiness fact."""

    async def has_active_organization_party(self, *, organization_id: UUID) -> bool: ...


class OnboardingIdentityFactsReader(Protocol):
    """Publish tenant-scoped identity/control readiness facts without PII."""

    async def read_identity_facts(
        self,
        *,
        organization_id: UUID,
    ) -> OnboardingIdentityFacts: ...
