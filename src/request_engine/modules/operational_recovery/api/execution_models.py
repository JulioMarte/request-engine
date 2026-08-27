from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.operational_recovery.api.model_common import RecoveryTargetView
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RecoveryExecutionStatus,
)


class RecoveryExecutionView(BaseModel):
    id: UUID
    proposal_id: UUID
    reservation_id: UUID
    status: RecoveryExecutionStatus
    original_reservation_revision: int
    resulting_reservation_revision: int | None
    target: RecoveryTargetView
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    notification_requested: bool
    communication_task_id: UUID | None

    @classmethod
    def from_contract(cls, item: RecoveryExecution) -> "RecoveryExecutionView":
        return cls(
            id=item.id,
            proposal_id=item.proposal_id,
            reservation_id=item.reservation_id,
            status=item.status,
            original_reservation_revision=item.original_reservation_revision,
            resulting_reservation_revision=item.resulting_reservation_revision,
            target=RecoveryTargetView.from_contract(item.target),
            created_at=item.created_at,
            completed_at=item.completed_at,
            failure_code=item.failure_code,
            notification_requested=item.notification.requested,
            communication_task_id=item.notification.communication_task_id,
        )
