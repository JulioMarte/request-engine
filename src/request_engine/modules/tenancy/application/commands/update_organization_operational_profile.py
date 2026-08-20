from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OrganizationOperationalProfile:
    organization_id: UUID
    legal_name: str | None
    default_timezone: str | None
    default_locale: str | None
    default_currency: str | None
    operational_status: str


@dataclass(frozen=True, slots=True)
class UpdateOrganizationOperationalProfileCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    legal_name: str | None
    default_timezone: str | None
    default_locale: str | None
    default_currency: str | None
    operational_status: str
    idempotency_key: str


class UpdateOrganizationOperationalProfileHandler(Protocol):
    async def update_organization_operational_profile(
        self,
        command: UpdateOrganizationOperationalProfileCommand,
    ) -> OrganizationOperationalProfile: ...


async def update_organization_operational_profile(
    handler: UpdateOrganizationOperationalProfileHandler,
    command: UpdateOrganizationOperationalProfileCommand,
) -> OrganizationOperationalProfile:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.update_organization_operational_profile(command)
