"""Self-only organization discovery; selection never grants operational authority."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.authentication import AuthenticatedSubject


@dataclass(frozen=True, slots=True)
class SelfOrganization:
    organization_id: UUID
    display_name: str
    principal_id: UUID
    membership_id: UUID


class SelfOrganizationReader(Protocol):
    async def list_for_subject(
        self, subject: AuthenticatedSubject, *, after: UUID | None, limit: int
    ) -> tuple[SelfOrganization, ...]: ...
