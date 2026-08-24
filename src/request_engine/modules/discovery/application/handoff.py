from typing import Protocol

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.discovery.application.queries.search_supply import DiscoveryCandidate


class DiscoveryHandoffIssuer(Protocol):
    async def issue_handoff(
        self,
        candidate: DiscoveryCandidate,
        slot: AppointmentSlot,
    ) -> str | None: ...
