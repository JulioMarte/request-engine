from dataclasses import asdict, is_dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionRequest,
)
from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotExecutionReceipt,
)
from request_engine.modules.operational_copilot.lowering import CopilotOperation
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)
from request_engine.modules.queue.contracts.intake import SetQueueIntakeControlRequest


class F6RequestBody(BaseModel):
    """Closed transport schema for public F6 mutation/interpretation requests."""

    model_config = ConfigDict(extra="forbid")


class CopilotInterpretBody(F6RequestBody):
    text: str


class CopilotInterpretationView(BaseModel):
    action: str
    operation: dict[str, object]


class CopilotExecutionView(BaseModel):
    owner: str
    action: str
    result_id: UUID
    status: str
    idempotency_key: str

    @classmethod
    def from_receipt(cls, receipt: CopilotExecutionReceipt) -> "CopilotExecutionView":
        return cls(**asdict(receipt))


class CopilotAtRiskCommitmentView(BaseModel):
    reservation_id: UUID
    reservation_revision: int
    planned_starts_at: datetime
    planned_ends_at: datetime


class CopilotAtRiskView(BaseModel):
    action: str
    service_queue_id: UUID
    projection_state: str
    shortfall_seconds: int
    source_fingerprint: str
    at_risk_reservations: list[CopilotAtRiskCommitmentView]


_ACTIONS: dict[type, str] = {
    CreateRecoveryProposalCommand: "propose_recovery",
    ExecuteRecoveryCommand: "execute_recovery",
    SetRecoveryIntakeCommand: "set_recovery_intake",
    ExtendRecoveryDayCommand: "extend_recovery_day",
    SetQueueIntakeControlRequest: "set_operational_intake",
    OperationalAssignmentExtensionRequest: "extend_operational_day",
    PublishDiscoverySupplyCommand: "publish_discovery_supply",
    RevokeDiscoveryPublicationCommand: "revoke_discovery_publication",
    AtRiskReservationsQuery: "show_at_risk_reservations",
}


def interpretation_view(operation: CopilotOperation) -> CopilotInterpretationView:
    action = _ACTIONS.get(type(operation))
    if action is None:
        raise TypeError(f"unregistered copilot operation view: {type(operation).__name__}")
    if not is_dataclass(operation):
        raise TypeError("copilot operation must be a dataclass")
    return CopilotInterpretationView(action=action, operation=asdict(operation))
