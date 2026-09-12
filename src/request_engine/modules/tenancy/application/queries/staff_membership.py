from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class StaffAuthorityGrant:
    capability: str
    delegable: bool


@dataclass(frozen=True, slots=True)
class StaffMembershipSummary:
    membership_id: UUID
    principal_id: UUID
    status: str
    membership_revision: int
    authority_revision: int
    principal_active: bool
    authority_anchor_party_id: UUID | None
    standing_grants: tuple[StaffAuthorityGrant, ...]


@dataclass(frozen=True, slots=True)
class ListStaffMembershipsQuery:
    after: UUID | None = None
    limit: int = 50


class StaffMembershipReader(Protocol):
    async def list_memberships(
        self, actor: ActorContext, query: ListStaffMembershipsQuery
    ) -> tuple[StaffMembershipSummary, ...]: ...

    async def read_membership(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffMembershipSummary: ...
