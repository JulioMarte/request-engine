from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.communications.contracts.tasks import CommunicationTask


@dataclass(frozen=True, slots=True)
class CreateCommunicationTaskCommand:
    organization_id: UUID
    principal_id: UUID
    recipient_party_id: UUID
    purpose: str
    template_key: str
    template_version: int
    channel_policy: dict[str, object]
    render_context: dict[str, object]
    idempotency_key: str
    contact_point_id: UUID | None = None
    source_kind: str | None = None
    source_id: UUID | None = None
    dedupe_key: str | None = None
    not_before: datetime | None = None
    expires_at: datetime | None = None


class CreateCommunicationTaskHandler(Protocol):
    async def create_communication_task(
        self,
        command: CreateCommunicationTaskCommand,
    ) -> CommunicationTask: ...


async def create_communication_task(
    handler: CreateCommunicationTaskHandler,
    command: CreateCommunicationTaskCommand,
) -> CommunicationTask:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.purpose:
        raise ValueError("purpose is required")
    if not command.template_key:
        raise ValueError("template_key is required")
    if command.template_version <= 0:
        raise ValueError("template_version must be positive")
    return await handler.create_communication_task(command)
