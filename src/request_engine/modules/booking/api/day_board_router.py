from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from request_engine.modules.booking.application.queries.get_day_board import (
    ReservationDayBoardReader,
    validate_day_board_window,
)
from request_engine.modules.booking.contracts.day_board import ReservationDayBoardEntry
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class ReservationDayBoardEntryView(BaseModel):
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    subject_display_name: str
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str
    attendance_responded_at: datetime | None
    attendance_outcome: str
    attendance_outcome_at: datetime | None
    estimated_arrival_at: datetime | None
    arrival_estimate_source_kind: str | None

    @classmethod
    def from_contract(cls, item: ReservationDayBoardEntry) -> "ReservationDayBoardEntryView":
        return cls(**{name: getattr(item, name) for name in cls.model_fields})


def create_day_board_router(
    reader: ReservationDayBoardReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def day_board(
        window_start: Annotated[datetime, Query()],
        window_end: Annotated[datetime, Query()],
        current: Annotated[ActorContext, Depends(actor)],
    ) -> tuple[ReservationDayBoardEntryView, ...]:
        require_capability(current, "appointments.day_board")
        try:
            validate_day_board_window(window_start, window_end)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        rows = await reader.read_window(
            current.organization_id,
            window_start=window_start,
            window_end=window_end,
        )
        return tuple(ReservationDayBoardEntryView.from_contract(item) for item in rows)

    add_capability_route(
        router,
        "/appointments/day-board",
        day_board,
        capability="appointments.day_board",
        methods=["GET"],
        response_model=tuple[ReservationDayBoardEntryView, ...],
    )
    return router
