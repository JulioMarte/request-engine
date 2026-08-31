from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.adapters.reference_resolver import (
    OwnerBackedCopilotReferenceResolver,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort


def build_reference_resolver(
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
