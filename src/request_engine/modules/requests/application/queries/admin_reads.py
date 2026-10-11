from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.application.commands.manage_definition import (
    RequestDefinitionState,
)


@dataclass(frozen=True, slots=True)
class RequestInboxItem:
    request_id: UUID
    definition_version_id: UUID
    definition_id: UUID
    request_key: str
    definition_version: int
    requester_party_id: UUID | None
    recipient_party_id: UUID | None
    status: str
    revision: int
    created_at: datetime


class RequestAdministrationReader(Protocol):
    async def list_definitions(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        after_id: UUID | None,
    ) -> tuple[RequestDefinitionState, ...]: ...

    async def get_definition(
        self,
        organization_id: UUID,
        definition_id: UUID,
        version: int | None,
        *,
        principal_id: UUID,
    ) -> RequestDefinitionState | None: ...

    async def list_inbox(
        self,
        organization_id: UUID,
        *,
        principal_id: UUID,
        limit: int,
        status: str | None,
        after_created_at: datetime | None,
        after_id: UUID | None,
    ) -> tuple[RequestInboxItem, ...]: ...
