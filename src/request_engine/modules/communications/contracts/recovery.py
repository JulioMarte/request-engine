from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.tasks import CommunicationTask


class RecoveryCommunicationPurpose(StrEnum):
    IMPACT = "operational_recovery_impact"
    RESCHEDULED = "operational_recovery_rescheduled"


@dataclass(frozen=True, slots=True)
class RecoveryCommunicationRequest:
    organization_id: UUID
    principal_id: UUID
    recipient_party_id: UUID
    purpose: RecoveryCommunicationPurpose
    execution_id: UUID
    idempotency_key: str
    dedupe_key: str
    render_context: dict[str, object]
    not_before: datetime | None = None


class RecoveryCommunicationPort(Protocol):
    async def create_recovery_notification(
        self, request: RecoveryCommunicationRequest
    ) -> CommunicationTask: ...
