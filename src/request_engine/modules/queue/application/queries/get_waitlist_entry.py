from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import WaitlistEntry


class WaitlistEntryReader(Protocol):
    async def get_waitlist_entry(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        waitlist_entry_id: UUID,
        allow_subject_override: bool,
    ) -> WaitlistEntry | None: ...


async def get_waitlist_entry(
    reader: WaitlistEntryReader,
    *,
    organization_id: UUID,
    principal_id: UUID,
    waitlist_entry_id: UUID,
    allow_subject_override: bool,
) -> WaitlistEntry | None:
    return await reader.get_waitlist_entry(
        organization_id=organization_id,
        principal_id=principal_id,
        waitlist_entry_id=waitlist_entry_id,
        allow_subject_override=allow_subject_override,
    )
