"""Canonical read-only administrative membership history."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.errors import StaffMembershipForbidden
from request_engine.modules.tenancy.application.queries.staff_history import (
    ListStaffHistoryQuery,
    StaffHistoryCommand,
    StaffHistoryReader,
    StaffHistoryRevisionKind,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


class StaffHistoryEntryView(BaseModel):
    event_id: UUID
    actor_principal_id: UUID | None
    occurred_at: datetime
    command_name: StaffHistoryCommand
    revision_kind: StaffHistoryRevisionKind
    revision_before: int | None
    revision_after: int | None


class StaffHistoryPageView(BaseModel):
    items: list[StaffHistoryEntryView]
    next_cursor: UUID | None


class StaffHistoryListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


def add_staff_history_reads(
    router: APIRouter,
    *,
    reader: StaffHistoryReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def list_history(
        membership_id: UUID,
        params: Annotated[StaffHistoryListParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffHistoryPageView:
        require_capability(actor, "staff.read")
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff history requires a HUMAN actor")
        response.headers["Cache-Control"] = "no-store"
        page = await reader.list_history(
            actor, ListStaffHistoryQuery(membership_id, params.after, params.limit)
        )
        return StaffHistoryPageView(
            items=[
                StaffHistoryEntryView(
                    event_id=item.event_id,
                    actor_principal_id=item.actor_principal_id,
                    occurred_at=item.occurred_at,
                    command_name=item.command_name,
                    revision_kind=item.revision_kind,
                    revision_before=item.revision_before,
                    revision_after=item.revision_after,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )

    add_capability_route(
        router,
        "/members/{membership_id}/history",
        list_history,
        methods=["GET"],
        operation_id="staff_history_list",
        capability="staff.read",
        owner="tenancy",
        response_model=StaffHistoryPageView,
        summary="List redacted administrative history of a staff member",
        description=(
            "Current HUMAN staff.read authority is revalidated. "
            "No audit payload or contact data is returned."
        ),
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 422)},
    )
