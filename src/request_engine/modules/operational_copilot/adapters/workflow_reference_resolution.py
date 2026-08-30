from datetime import datetime
from zoneinfo import ZoneInfo

from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.resolution_common import require_one
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendRecoveryDayIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.references import ExtendNamedResourceTodayIntent
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort


async def resolve_extend_today(
    catalog: CopilotCatalogReader,
    recovery: CopilotRecoveryIncidentReader,
    context: CopilotContext,
    intent: ExtendNamedResourceTodayIntent,
) -> ExtendRecoveryDayIntent:
    resource = require_one(
        await catalog.find_resources(
            organization_id=context.organization_id,
            reference=intent.resource_reference,
        ),
        "resource",
    )
    incident = require_one(
        await recovery.find_open_incidents_for_resource(
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


async def resolve_stop_walk_ins(
    catalog: CopilotCatalogReader,
    queues: CopilotQueueReader,
    recovery: CopilotRecoveryIncidentReader,
    intake_reader: QueueIntakeControlPort,
    context: CopilotContext,
) -> SetRecoveryIntakeIntent:
    queue = require_one(await queues.list_queues(organization_id=context.organization_id), "queue")
    incident = await recovery.get_open_incident_for_queue(
        organization_id=context.organization_id,
        service_queue_id=queue.service_queue_id,
    )
    if incident is None:
        raise CopilotResolutionFailed("no open recovery incident exists for the current queue")
    intake = await intake_reader.get_intake_control(context.organization_id, queue.service_queue_id)
    clock = await catalog.read_location_clock(
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
