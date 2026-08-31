from fastapi import FastAPI

from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.discovery_publication_executors import (
    DiscoveryPublishCopilotExecutor,
    DiscoveryRevokeCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.reference_resolver import (
    OwnerBackedCopilotReferenceResolver,
)
from request_engine.modules.operational_copilot.adapters.recovery_command_executors import (
    RecoveryExecutionCopilotExecutor,
    RecoveryProposalCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.recovery_extend_day_executor import (
    RecoveryExtendDayCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.recovery_intake_executor import (
    RecoveryIntakeCopilotExecutor,
)
from request_engine.modules.operational_copilot.api.copilot_router import create_copilot_router
from request_engine.modules.operational_copilot.api.recovery import (
    build_live_capacity_at_risk_reader,
)
from request_engine.modules.operational_copilot.api.tool_write_router import (
    create_tool_write_router,
)
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
    discovery_executor: DiscoveryPublicationExecutor | None = None,
    booking_reader: CopilotBookingReader | None = None,
    catalog_reader: CopilotCatalogReader | None = None,
    queue_reader: CopilotQueueReader | None = None,
    queue_intake_reader: QueueIntakeControlPort | None = None,
    recovery_incident_reader: CopilotRecoveryIncidentReader | None = None,
) -> None:
    executors = (
        RecoveryProposalCopilotExecutor(recovery_executor) if recovery_executor else None,
        RecoveryExecutionCopilotExecutor(recovery_executor) if recovery_executor else None,
        RecoveryIntakeCopilotExecutor(intake_executor) if intake_executor else None,
        RecoveryExtendDayCopilotExecutor(extend_day_executor) if extend_day_executor else None,
        DiscoveryPublishCopilotExecutor(discovery_executor) if discovery_executor else None,
        DiscoveryRevokeCopilotExecutor(discovery_executor) if discovery_executor else None,
    )
    resolver = _build_reference_resolver(
        booking_reader,
        catalog_reader,
        queue_reader,
        recovery_incident_reader,
        queue_intake_reader,
    )
    copilot = OperationalCopilot(
        at_risk_reader,
        proposal_reader,
        authority_reader,
        tuple(executor for executor in executors if executor is not None),
        resolver,
    )
    app.include_router(create_copilot_router(copilot=copilot, actor_resolver=actor_resolver))
    app.include_router(create_tool_write_router(copilot=copilot, actor_resolver=actor_resolver))


def _build_reference_resolver(
    booking: CopilotBookingReader | None,
    catalog: CopilotCatalogReader | None,
    queues: CopilotQueueReader | None,
    recovery: CopilotRecoveryIncidentReader | None,
    intake: QueueIntakeControlPort | None,
) -> OwnerBackedCopilotReferenceResolver | None:
    values = (booking, catalog, queues, recovery, intake)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("copilot reference resolution requires all owner readers")
    assert booking is not None
    assert catalog is not None
    assert queues is not None
    assert recovery is not None
    assert intake is not None
    return OwnerBackedCopilotReferenceResolver(booking, catalog, queues, recovery, intake)
