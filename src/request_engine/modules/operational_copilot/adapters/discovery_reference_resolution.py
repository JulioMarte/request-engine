from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.resolution_common import require_one
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    PublishDiscoverySupplyIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import (
    PublishNamedResourceDiscoveryIntent,
)


async def resolve_publish_discovery(
    booking: CopilotBookingReader,
    catalog: CopilotCatalogReader,
    context: CopilotContext,
    intent: PublishNamedResourceDiscoveryIntent,
) -> PublishDiscoverySupplyIntent:
    resource = require_one(
        await booking.find_resources(
            organization_id=context.organization_id,
            reference=intent.resource_reference,
        ),
        "resource",
    )
    offering = require_one(
        await catalog.find_offerings(
            organization_id=context.organization_id,
            reference=intent.offering_reference,
        ),
        "offering",
    )
    clock = await catalog.read_location_clock(
        organization_id=context.organization_id,
        location_id=resource.location_id,
    )
    if clock is None:
        raise CopilotResolutionFailed("resource location operational context is unavailable")
    return PublishDiscoverySupplyIntent(
        offering_id=offering.offering_id,
        location_id=resource.location_id,
        effective_start=clock.observed_at,
        resource_id=resource.resource_id,
        provider_visibility="public",
        effective_start_origin="resolved_now",
    )
