"""Front-desk staffing Query: who can start service at a Location now.

It mirrors the execution preconditions of ``service_session.start`` (an active
Resource with an active ResourceLocationAssignment in force at the Location at
the database instant) so a person who may start service can pick a valid
Resource. It grants nothing: the start command re-locks and re-validates the
Resource and assignment.
"""

from typing import Protocol
from uuid import UUID

from request_engine.modules.delivery.contracts.serving_resources import LocationServingResources


class ServingResourceReader(Protocol):
    async def read_serving_resources(
        self, organization_id: UUID, location_id: UUID
    ) -> LocationServingResources | None:
        """``None`` when the Location is not visible to the caller's Organization."""
        ...
