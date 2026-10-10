"""Minimal, redacted administrative history of one tenant staff membership."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

StaffHistoryCommand = Literal[
    "staff.invite", "staff.manage_authority", "staff.manage_membership", "staff.profile.update"
]
StaffHistoryRevisionKind = Literal["membership", "authority", "profile"]


@dataclass(frozen=True, slots=True)
class ListStaffHistoryQuery:
    membership_id: UUID
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class StaffHistoryEntry:
    event_id: UUID
    actor_principal_id: UUID | None
    occurred_at: datetime
    command_name: StaffHistoryCommand
    revision_kind: StaffHistoryRevisionKind
    revision_before: int | None
    revision_after: int | None


@dataclass(frozen=True, slots=True)
class StaffHistoryPage:
    items: tuple[StaffHistoryEntry, ...]
    next_cursor: UUID | None


class StaffHistoryReader(Protocol):
    async def list_history(
        self, actor: ActorContext, query: ListStaffHistoryQuery
    ) -> StaffHistoryPage: ...
