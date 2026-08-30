from datetime import datetime
from typing import TypeVar, cast
from zoneinfo import ZoneInfo

from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CopilotIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    SetRecoveryIntakeIntent,
    ShowAtRiskReservationsIntent,
)
from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    CopilotResolutionFailed,
)
from request_engine.modules.operational_copilot.references import (
    CopilotParsedIntent,
    ExtendNamedResourceTodayIntent,
    PublishNamedResourceDiscoveryIntent,
    ShowCurrentAtRiskReservationsIntent,
    StopWalkInsRestOfDayIntent,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort

T = TypeVar("T")


class OwnerBackedCopilotReferenceResolver:
    def __init__(
        self,
        catalog: CopilotCatalogReader,
        queues: CopilotQueueReader,
        recovery: CopilotRecoveryIncidentReader,
        intake: QueueIntakeControlPort,
    ) -> None:
        self._catalog = catalog
        self._queues = queues
        self._recovery = recovery
        self._intake = intake

    async def resolve(
        self,
        context: CopilotContext,
        intent: CopilotParsedIntent,
    ) -> CopilotIntent:
        if isinstance(intent, ExtendNamedResourceTodayIntent):
            return await self._extend_today(context, intent)
        if isinstance(intent, StopWalkInsRestOfDayIntent):
            return await self._stop_walk_ins(context)
        if isinstance(intent, PublishNamedResourceDiscoveryIntent):
            return await self._publish_discovery(context, intent)
        if isinstance(intent, ShowCurrentAtRiskReservationsIntent):
            queue = _one(await self._queues.list_queues(organization_id=context.organization_id), "queue")
            return ShowAtRiskReservationsIntent(queue.service_queue_id)
        return cast(CopilotIntent, intent)

    async def _extend_today(
        self,
        context: CopilotContext,
        intent: ExtendNamedResourceTodayIntent,
    ) -> ExtendRecoveryDayIntent:
        resource = _one(
            await self._catalog.find_resources(
                organization_id=context.organization_id,
                reference=intent.resource_reference,
            ),
            "resource",
        )
        incident = _one(
            await self._recovery.find_open_incidents_for_resource(
                organization_id=context.organization_id,
                resource_id=resource.resource_id,
            ),
            "open recovery incident",
        )
        if incident.location_id != resource.location_id or resource.scheduled_end_at is None:
            raise CopilotResolutionFailed("resource operational context is not uniquely executable")
        zone = ZoneInfo(resource.timezone)
        target_end = datetime.combine(
            resource.observed_at.astimezone(zone).date(),
            intent.target_local_time,
            tzinfo=zone,
        )
        return ExtendRecoveryDayIntent(
            incident_id=incident.id,
            assignment_id=resource.assignment_id,
            start_at=resource.scheduled_end_at,
            end_at=target_end,
            expected_source_revision=incident.source_revision,
            expected_location_operational_revision=resource.location_operational_revision,
            expected_resource_availability_revision=resource.resource_availability_revision,
            reason=f"operational copilot: extend {intent.resource_reference} today",
        )

    async def _stop_walk_ins(self, context: CopilotContext) -> SetRecoveryIntakeIntent:
        queue = _one(await self._queues.list_queues(organization_id=context.organization_id), "queue")
        incident = await self._recovery.get_open_incident_for_queue(
            organization_id=context.organization_id,
            service_queue_id=queue.service_queue_id,
        )
        if incident is None:
            raise CopilotResolutionFailed("no open recovery incident exists for the current queue")
        intake = await self._intake.get_intake_control(
            context.organization_id,
            queue.service_queue_id,
        )
        clock = await self._catalog.read_location_clock(
            organization_id=context.organization_id,
            location_id=queue.location_id,
        )
        if clock is None or clock.operational_day_end_at is None:
            raise CopilotResolutionFailed("location operational day end is unavailable")
        if clock.operational_day_end_at <= clock.observed_at:
            raise CopilotResolutionFailed("the current operational day has already ended")
        return SetRecoveryIntakeIntent(
            incident_id=incident.id,
            accepting=False,
            expected_source_revision=incident.source_revision,
            expected_intake_revision=intake.revision,
            reason="operational copilot: stop accepting walk-ins for the rest of the day",
            effective_until=clock.operational_day_end_at,
        )

    async def _publish_discovery(
        self,
        context: CopilotContext,
        intent: PublishNamedResourceDiscoveryIntent,
    ) -> PublishDiscoverySupplyIntent:
        resource = _one(
            await self._catalog.find_resources(
                organization_id=context.organization_id,
                reference=intent.resource_reference,
            ),
            "resource",
        )
        offering = _one(
            await self._catalog.find_offerings(
                organization_id=context.organization_id,
                reference=intent.offering_reference,
            ),
            "offering",
        )
        return PublishDiscoverySupplyIntent(
            offering_id=offering.offering_id,
            location_id=resource.location_id,
            effective_start=resource.observed_at,
            resource_id=resource.resource_id,
            provider_visibility="public",
        )


def _one(values: tuple[T, ...], label: str) -> T:
    if not values:
        raise CopilotResolutionFailed(f"no tenant-scoped {label} matched")
    if len(values) != 1:
        raise AmbiguousCopilotIntent(f"multiple tenant-scoped {label} values matched")
    return values[0]
