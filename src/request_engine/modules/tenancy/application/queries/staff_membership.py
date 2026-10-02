from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

StaffMembershipStatus = Literal["invited", "active", "suspended", "revoked"]


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
    display_name: str | None = None
    profile_revision: int = 0


@dataclass(frozen=True, slots=True)
class StaffOverview:
    total: int
    active: int
    invited: int
    suspended: int
    revoked: int
    effective_capabilities: tuple[str, ...] = ()
    delegable_ceiling: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanStaffAuthorityQuery:
    membership_id: UUID
    expected_authority_revision: int
    desired_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StaffAuthorityPlan:
    membership_id: UUID
    authority_revision: int
    current: tuple[str, ...]
    desired: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    assignable: bool
    blocked_capabilities: tuple[str, ...]
    can_apply: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListStaffMembershipsQuery:
    after: UUID | None = None
    limit: int = 50
    status: StaffMembershipStatus | None = None
    search: str | None = None

    def __post_init__(self) -> None:
        if self.status is not None and self.status not in (
            "invited",
            "active",
            "suspended",
            "revoked",
        ):
            raise ValueError("unsupported staff membership status")
        if self.search is not None and not 1 <= len(self.search.strip()) <= 100:
            raise ValueError("search must contain between 1 and 100 characters")


class StaffMembershipReader(Protocol):
    async def read_overview(self, actor: ActorContext) -> StaffOverview: ...

    async def list_memberships(
        self, actor: ActorContext, query: ListStaffMembershipsQuery
    ) -> tuple[StaffMembershipSummary, ...]: ...

    async def read_membership(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffMembershipSummary: ...

    async def plan_authority(
        self, actor: ActorContext, query: PlanStaffAuthorityQuery
    ) -> StaffAuthorityPlan: ...
