from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
)
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
    PlanStaffAuthorityQuery,
    StaffAuthorityPlan,
    StaffMembershipReader,
    StaffMembershipStatus,
    StaffMembershipSummary,
    StaffOverview,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired, require_capability


class StaffGrantView(BaseModel):
    capability: str
    delegable: bool


class StaffMembershipView(BaseModel):
    membership_id: UUID
    principal_id: UUID
    status: str
    membership_revision: int
    authority_revision: int
    principal_active: bool
    authority_anchor_party_id: UUID | None
    standing_grants: list[StaffGrantView]
    display_name: str | None = None
    profile_revision: int = 0


class StaffMembershipPageView(BaseModel):
    items: list[StaffMembershipView]
    next_cursor: UUID | None


class StaffOverviewView(BaseModel):
    total: int
    active: int
    invited: int
    suspended: int
    revoked: int
    effective_capabilities: list[str]
    delegable_ceiling: list[str]


class StaffAuthorityPlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_authority_revision: int = Field(ge=1)
    desired_capabilities: list[str] = Field(max_length=128)


class StaffAuthorityPlanView(BaseModel):
    membership_id: UUID
    authority_revision: int
    current: list[str]
    desired: list[str]
    added: list[str]
    removed: list[str]
    assignable: bool
    blocked_capabilities: list[str]
    can_apply: bool
    blockers: list[str]


class StaffMembershipListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)
    status: StaffMembershipStatus | None = None
    search: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None


def _view(member: StaffMembershipSummary) -> StaffMembershipView:
    return StaffMembershipView(
        membership_id=member.membership_id,
        principal_id=member.principal_id,
        status=member.status,
        membership_revision=member.membership_revision,
        authority_revision=member.authority_revision,
        principal_active=member.principal_active,
        authority_anchor_party_id=member.authority_anchor_party_id,
        standing_grants=[
            StaffGrantView(capability=grant.capability, delegable=grant.delegable)
            for grant in member.standing_grants
        ],
        display_name=member.display_name,
        profile_revision=member.profile_revision,
    )


def _overview_view(overview: StaffOverview) -> StaffOverviewView:
    return StaffOverviewView(
        total=overview.total,
        active=overview.active,
        invited=overview.invited,
        suspended=overview.suspended,
        revoked=overview.revoked,
        effective_capabilities=list(overview.effective_capabilities),
        delegable_ceiling=list(overview.delegable_ceiling),
    )


def _plan_view(plan: StaffAuthorityPlan) -> StaffAuthorityPlanView:
    return StaffAuthorityPlanView(
        membership_id=plan.membership_id,
        authority_revision=plan.authority_revision,
        current=list(plan.current),
        desired=list(plan.desired),
        added=list(plan.added),
        removed=list(plan.removed),
        assignable=plan.assignable,
        blocked_capabilities=list(plan.blocked_capabilities),
        can_apply=plan.can_apply,
        blockers=list(plan.blockers),
    )


def add_staff_membership_reads(
    router: APIRouter,
    *,
    reader: StaffMembershipReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def read_overview(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffOverviewView:
        require_capability(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        return _overview_view(await reader.read_overview(actor))

    async def list_memberships(
        params: Annotated[StaffMembershipListParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffMembershipPageView:
        require_capability(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        rows = await reader.list_memberships(
            actor,
            ListStaffMembershipsQuery(params.after, params.limit, params.status, params.search),
        )
        return StaffMembershipPageView(
            items=[_view(row) for row in rows],
            next_cursor=rows[-1].membership_id if len(rows) == params.limit else None,
        )

    async def read_membership(
        membership_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffMembershipView:
        require_capability(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        return _view(await reader.read_membership(actor, membership_id))

    async def plan_authority(
        membership_id: UUID,
        body: StaffAuthorityPlanBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffAuthorityPlanView:
        if not (actor.allows("staff.plan_authority") or actor.allows("staff.manage_authority")):
            raise CapabilityRequired("staff.plan_authority")
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff authority planning requires a HUMAN actor")
        response.headers["Cache-Control"] = "no-store"
        try:
            plan = await reader.plan_authority(
                actor,
                PlanStaffAuthorityQuery(
                    membership_id=membership_id,
                    expected_authority_revision=body.expected_authority_revision,
                    desired_capabilities=tuple(body.desired_capabilities),
                ),
            )
        except ValueError as exc:
            raise StaffMembershipInputInvalid(str(exc)) from None
        return _plan_view(plan)

    add_capability_route(
        router,
        "/overview",
        read_overview,
        methods=["GET"],
        capability="staff.read",
        operation_id="staff_overview_get",
        response_model=StaffOverviewView,
    )

    add_capability_route(
        router,
        "/members",
        list_memberships,
        methods=["GET"],
        capability="staff.read",
        operation_id="staff_list",
        response_model=StaffMembershipPageView,
    )
    add_capability_route(
        router,
        "/members/{membership_id}",
        read_membership,
        methods=["GET"],
        capability="staff.read",
        operation_id="staff_get",
        response_model=StaffMembershipView,
    )
    add_capability_route(
        router,
        "/members/{membership_id}/authority:plan",
        plan_authority,
        methods=["POST"],
        capability="staff.plan_authority",
        operation_id="staff_authority_plan",
        response_model=StaffAuthorityPlanView,
    )
