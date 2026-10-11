from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    OfferingRequirementInput,
    ResourceCapabilityState,
)


@dataclass(frozen=True, slots=True)
class OfferingConfiguration:
    offering_id: UUID
    offering_version_id: UUID
    offering_key: str
    version: int
    active: bool
    requirements: tuple[OfferingRequirementInput, ...]
    booking_policy_revision: int
    booking_policy: policy_commands.BookingPolicyInput


class CatalogConfigurationReader(Protocol):
    async def list_resource_capabilities(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[ResourceCapabilityState, ...]: ...

    async def read_offering_configuration(
        self,
        organization_id: UUID,
        offering_version_id: UUID,
        *,
        principal_id: UUID,
    ) -> OfferingConfiguration | None: ...
