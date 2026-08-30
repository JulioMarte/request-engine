from dataclasses import asdict, is_dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery
from request_engine.modules.operational_copilot.lowering import CopilotOperation
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)


class CopilotInterpretBody(BaseModel):
    text: str
    authority_party_id: UUID | None = None


class CopilotInterpretationView(BaseModel):
    action: str
    operation: dict[str, object]


class CopilotAtRiskCommitmentView(BaseModel):
    reservation_id: UUID
    reservation_revision: int
    planned_starts_at: datetime
    planned_ends_at: datetime
    contextual_commitment: bool


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
    PublishDiscoverySupplyCommand: "publish_discovery_supply",
    RevokeDiscoveryPublicationCommand: "revoke_discovery_publication",
    AtRiskReservationsQuery: "show_at_risk_reservations",
}


def interpretation_view(operation: CopilotOperation) -> CopilotInterpretationView:
    action = _ACTIONS.get(type(operation))
    if action is None:
        raise TypeError(f"unsupported copilot operation: {type(operation).__name__}")
    return CopilotInterpretationView(
        action=action,
        operation=_operation_payload(operation),
    )


def _operation_payload(operation: CopilotOperation) -> dict[str, object]:
    if not is_dataclass(operation):
        raise TypeError(f"unsupported copilot operation: {type(operation).__name__}")
    return {key: _normalize(value) for key, value in asdict(operation).items()}


def _normalize(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
