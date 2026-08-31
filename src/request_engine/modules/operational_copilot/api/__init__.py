from fastapi import FastAPI

from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentSchedulePort,
)
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.discovery.contracts.copilot import CopilotDiscoveryPublicationReader
from request_engine.modules.operational_copilot.api.copilot_router import create_copilot_router
from request_engine.modules.operational_copilot.api.executor_composition import build_mutation_executors
from request_engine.modules.operational_copilot.api.recovery import build_live_capacity_at_risk_reader
from request_engine.modules.operational_copilot.api.reference_composition import build_reference_resolver
from request_engine.modules.operational_copilot.api.tool_lookup_router import create_tool_lookup_router
from request_engine.modules.operational_copilot.api.tool_operational_write_router import (
    create_tool_operational_write_router,
)
from request_engine.modules.operational_copilot.api.tool_recovery_proposal_router import (
    create_tool_recovery_proposal_router,
)
from request_engine.modules.operational_copilot.api.tool_state_router import create_tool_state_router
from request_engine.modules.operational_copilot.api.tool_write_router import create_tool_write_router
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.application.ports import (
    AtRiskReservationReader,
    AuthorityPartyReader,
    DiscoveryPublicationExecutor,
    RecoveryCommandExecutor,
    RecoveryExtendDayExecutor,
    RecoveryIntakeExecutor,
    RecoveryProposalReader,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort
from request_engine.platform.security.http import ActorResolver

__all__ = ["build_live_capacity_at_risk_reader", "install_http"]


def install_http(
    app: FastAPI,
    *,
    actor_resolver: ActorResolver,
    at_risk_reader: AtRiskReservationReader,
    proposal_reader: RecoveryProposalReader | None = None,
    authority_reader: AuthorityPartyReader | None = None,
    recovery_executor: RecoveryCommandExecutor | None = None,
    intake_executor: RecoveryIntakeExecutor | None = None,
    extend_day_executor: RecoveryExtendDayExecutor | None = None,
    operational_schedule: OperationalAssignmentSchedulePort | None = None,
    discovery_executor: DiscoveryPublicationExecutor | None = None,
    discovery_reader: CopilotDiscoveryPublicationReader | None = None,
    booking_reader: CopilotBookingReader | None = None,
    catalog_reader: CopilotCatalogReader | None = None,
    queue_reader: CopilotQueueReader | None = None,
    queue_intake_reader: QueueIntakeControlPort | None = None,
    recovery_incident_reader: CopilotRecoveryIncidentReader | None = None,
) -> None:
    executors = build_mutation_executors(
        recovery=recovery_executor,
        recovery_intake=intake_executor,
        recovery_extend_day=extend_day_executor,
        operational_intake=queue_intake_reader,
        operational_schedule=operational_schedule,
        discovery=discovery_executor,
    )
    resolver = build_reference_resolver(
        booking_reader, catalog_reader, queue_reader, queue_intake_reader
    )
    copilot = OperationalCopilot(
        at_risk_reader, proposal_reader, authority_reader, executors, resolver
    )
    app.include_router(create_copilot_router(copilot=copilot, actor_resolver=actor_resolver))
    app.include_router(create_tool_write_router(copilot=copilot, actor_resolver=actor_resolver))
    app.include_router(
        create_tool_operational_write_router(copilot=copilot, actor_resolver=actor_resolver)
    )
    if proposal_reader is not None:
        app.include_router(
            create_tool_recovery_proposal_router(
                actor_resolver=actor_resolver,
                proposal_reader=proposal_reader,
            )
        )
    if booking_reader is not None and catalog_reader is not None and queue_reader is not None:
        app.include_router(
            create_tool_lookup_router(
                actor_resolver=actor_resolver,
                booking_reader=booking_reader,
                catalog_reader=catalog_reader,
                queue_reader=queue_reader,
            )
        )
    if (
        queue_intake_reader is not None
        and recovery_incident_reader is not None
        and discovery_reader is not None
    ):
        app.include_router(
            create_tool_state_router(
                actor_resolver=actor_resolver,
                at_risk_reader=at_risk_reader,
                intake_reader=queue_intake_reader,
                incident_reader=recovery_incident_reader,
                discovery_reader=discovery_reader,
            )
        )
