from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from request_engine.modules.booking.api.day_board_models import DayBoardEntryView
from request_engine.modules.booking.application.queries.get_day_board import (
    DayBoardReader,
    GetDayBoardQuery,
    get_day_board,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

_MAX_WINDOW = timedelta(hours=48)


def create_day_board_router(*, reader: DayBoardReader, actor_resolver: ActorResolver) -> APIRouter:
    router = APIRouter(prefix="/v1/front-desk", tags=["front-desk"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def day_board(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        window_start: Annotated[datetime, Query()],
        window_end: Annotated[datetime, Query()],
        location_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ) -> tuple[DayBoardEntryView, ...]:
        require_capability(actor, "front_desk.day_board.read")
        validate_day_board_window(window_start, window_end)
        entries = await get_day_board(
            reader,
            GetDayBoardQuery(
                organization_id=actor.organization_id,
                window_start=window_start,
                window_end=window_end,
                location_id=location_id,
                limit=limit,
            ),
        )
        return tuple(DayBoardEntryView.from_contract(entry) for entry in entries)

    add_capability_route(
        router,
        "/day-board",
        day_board,
        capability="front_desk.day_board.read",
        methods=["GET"],
        response_model=tuple[DayBoardEntryView, ...],
    )
    return router


def validate_day_board_window(window_start: datetime, window_end: datetime) -> None:
    detail: str | None = None
    if window_start.utcoffset() is None or window_end.utcoffset() is None:
        detail = "day board timestamps must include a timezone offset"
    elif window_end <= window_start:
        detail = "window_end must be after window_start"
    elif window_end - window_start > _MAX_WINDOW:
        detail = "day board window cannot exceed 48 hours"
    if detail is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
