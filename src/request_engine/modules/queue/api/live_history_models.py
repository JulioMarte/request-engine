from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.queue.api.live_models import StaffQueueEntryView
from request_engine.modules.queue.contracts.live_queue import StaffQueueHistoryPage


class StaffQueueHistoryPageView(BaseModel):
    entries: tuple[StaffQueueEntryView, ...]
    next_cursor: UUID | None

    @classmethod
    def from_contract(cls, item: StaffQueueHistoryPage) -> "StaffQueueHistoryPageView":
        return cls(
            entries=tuple(StaffQueueEntryView.from_contract(entry) for entry in item.entries),
            next_cursor=item.next_cursor,
        )
