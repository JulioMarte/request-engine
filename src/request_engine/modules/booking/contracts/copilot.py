from dataclasses import dataclass
from datetime import time
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotResourceMatch:
    resource_id: UUID
    location_id: UUID
    assignment_id: UUID
    resource_availability_revision: int


class CopilotBookingReader(Protocol):
    async def find_resources(
        self,
        *,
        organization_id: UUID,
        reference: str,
    ) -> tuple[CopilotResourceMatch, ...]: ...

    async def read_assignment_day_end(
        self,
        *,
        organization_id: UUID,
        assignment_id: UUID,
        weekday: int,
    ) -> time | None: ...
