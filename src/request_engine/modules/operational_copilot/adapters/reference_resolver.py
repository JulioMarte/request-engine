from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentSchedulePort,
)
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.discovery_reference_resolution import (
    resolve_publish_discovery,
)
from request_engine.modules.operational_copilot.adapters.proactive_replay_resolution import (
    resolve_proactive_replay,
)
from request_engine.modules.operational_copilot.adapters.resolution_common import require_one
from request_engine.modules.operational_copilot.adapters.workflow_reference_resolution import (
    resolve_extend_today,
    resolve_stop_walk_ins,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CopilotIntent,
    ShowAtRiskReservationsIntent,
)
from request_engine.modules.operational_copilot.references import (
    CopilotParsedIntent,
    ExtendNamedResourceTodayIntent,
    PublishNamedResourceDiscoveryIntent,
    ShowCurrentAtRiskReservationsIntent,
    StopWalkInsRestOfDayIntent,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort


class OwnerBackedCopilotReferenceResolver:
    def __init__(
        self,
        booking: CopilotBookingReader,
        catalog: CopilotCatalogReader,
        queues: CopilotQueueReader,
        intake: QueueIntakeControlPort,
        schedule: OperationalAssignmentSchedulePort | None = None,
    ) -> None:
        self._booking = booking
        self._catalog = catalog
        self._queues = queues
        self._intake = intake
        self._schedule = schedule

    async def resolve(
        self,
        context: CopilotContext,
        intent: CopilotParsedIntent,
    ) -> CopilotIntent:
        if isinstance(intent, ExtendNamedResourceTodayIntent):
            replay = await resolve_proactive_replay(self._schedule, self._intake, context, intent)
            if replay is not None:
                return replay
            return await resolve_extend_today(self._booking, self._catalog, context, intent)
        if isinstance(intent, StopWalkInsRestOfDayIntent):
            replay = await resolve_proactive_replay(self._schedule, self._intake, context, intent)
            if replay is not None:
                return replay
            return await resolve_stop_walk_ins(
                self._catalog,
                self._queues,
                self._intake,
                context,
            )
        if isinstance(intent, PublishNamedResourceDiscoveryIntent):
            return await resolve_publish_discovery(self._booking, self._catalog, context, intent)
        if isinstance(intent, ShowCurrentAtRiskReservationsIntent):
            queue = require_one(
                await self._queues.list_queues(organization_id=context.organization_id),
                "queue",
            )
            return ShowAtRiskReservationsIntent(queue.service_queue_id)
        return intent
