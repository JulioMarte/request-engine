from datetime import datetime
from zoneinfo import ZoneInfo

from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.resolution_common import require_one
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendOperationalDayIntent,
    SetOperationalIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import ExtendNamedResourceTodayIntent
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort


async def resolve_extend_today(
    booking: CopilotBookingReader,
    catalog: CopilotCatalogReader,
    context: CopilotContext,
    intent: ExtendNamedResourceTodayIntent,
) -> ExtendOperationalDayIntent:
    resource = require_one(
        await booking.find_resources(
            organization_id=context.organization_id,
            reference=intent.resource_reference,
        ),
        "resource",
    )
    clock = await catalog.read_location_clock(
        organization_id=context.organization_id,
        location_id=resource.location_id,
    )
    if clock is None:
        raise CopilotResolutionFailed("resource operational context is not uniquely executable")
    zone = ZoneInfo(clock.timezone)
    local_observed = clock.observed_at.astimezone(zone)
    scheduled_local_end = await booking.read_assignment_day_end(
        organization_id=context.organization_id,
        assignment_id=resource.assignment_id,
        weekday=local_observed.weekday(),
    )
    if scheduled_local_end is None:
        raise CopilotResolutionFailed("resource scheduled day end is unavailable")
    scheduled_end = datetime.combine(local_observed.date(), scheduled_local_end, tzinfo=zone)
    target_end = datetime.combine(local_observed.date(), intent.target_local_time, tzinfo=zone)
    if target_end <= scheduled_end:
        raise CopilotResolutionFailed("requested day extension does not extend the current schedule")
    if target_end <= clock.observed_at:
        raise CopilotResolutionFailed("requested day extension has already elapsed")
    return ExtendOperationalDayIntent(
        assignment_id=resource.assignment_id,
        start_at=scheduled_end,
        end_at=target_end,
        expected_resource_availability_revision=resource.resource_availability_revision,
        reason=f"operational copilot: extend {intent.resource_reference} today",
    )


async def resolve_stop_walk_ins(
    catalog: CopilotCatalogReader,
    queues: CopilotQueueReader,
    intake_reader: QueueIntakeControlPort,
    context: CopilotContext,
) -> SetOperationalIntakeIntent:
    queue = require_one(await queues.list_queues(organization_id=context.organization_id), "queue")
    intake = await intake_reader.get_intake_control(context.organization_id, queue.service_queue_id)
    clock = await catalog.read_location_clock(
        organization_id=context.organization_id,
        location_id=queue.location_id,
    )
    if clock is None or clock.operational_day_end_at is None:
        raise CopilotResolutionFailed("location operational day end is unavailable")
    if clock.operational_day_end_at <= clock.observed_at:
        raise CopilotResolutionFailed("the current operational day has already ended")
    return SetOperationalIntakeIntent(
        service_queue_id=queue.service_queue_id,
        accepting=False,
        expected_intake_revision=intake.revision,
        reason="operational copilot: stop accepting walk-ins for the rest of the day",
        effective_until=clock.operational_day_end_at,
    )
