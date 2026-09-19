from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
    StaffMembershipReader,
    StaffMembershipSummary,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability


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


class StaffMembershipPageView(BaseModel):
    items: list[StaffMembershipView]
    next_cursor: UUID | None


class StaffMembershipListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


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
    )


def add_staff_membership_reads(
    router: APIRouter,
    *,
    reader: StaffMembershipReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def list_memberships(
        params: Annotated[StaffMembershipListParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffMembershipPageView:
        require_capability(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        rows = await reader.list_memberships(
            actor, ListStaffMembershipsQuery(params.after, params.limit)
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
