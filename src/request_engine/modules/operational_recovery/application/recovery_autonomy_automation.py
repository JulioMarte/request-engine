from typing import Protocol
from uuid import UUID


class RecoveryRescheduleAutonomy(Protocol):
    """Contract 32 section 14: autonomous reschedule within the operator-granted
    envelope. The system may move an affected appointment strictly later, up to
    the granted delay budget, only when the persisted proposal itself contains a
    compatible candidate; it never reassigns subjects and never invents targets.
    Failures converge through the reschedule action's own idempotency identity.
    """

    async def reschedule_within_envelope(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        service_queue_id: UUID,
        proposal_id: UUID,
        source_revision: int,
    ) -> None: ...
