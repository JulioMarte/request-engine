import base64
import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from request_engine.modules.booking.application.queries.get_appointment_calendar import (
    MAX_CALENDAR_LIMIT,
    AppointmentCalendarQuery,
    AppointmentCalendarReader,
    CalendarPosition,
    validate_calendar_window,
)
from request_engine.modules.booking.contracts.appointment_calendar import (
    AppointmentCalendarEntry,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class CalendarResourceView(BaseModel):
    resource_id: UUID
    display_name: str
    claim_active: bool


class AppointmentCalendarEntryView(BaseModel):
    reservation_id: UUID
    offering_version_id: UUID
    offering_display_name: str
    subject_party_id: UUID
    subject_display_name: str
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str
    attendance_outcome: str
    checked_in_at: datetime | None
    no_show_at: datetime | None
    visit_arrived_at: datetime | None
    served_queue_entry_id: UUID | None
    served_at: datetime | None
    resources: tuple[CalendarResourceView, ...]

    @classmethod
    def from_contract(cls, item: AppointmentCalendarEntry) -> "AppointmentCalendarEntryView":
        values = {name: getattr(item, name) for name in cls.model_fields if name != "resources"}
        return cls(
            **values,
            resources=tuple(
                CalendarResourceView(
                    resource_id=claim.resource_id,
                    display_name=claim.display_name,
                    claim_active=claim.claim_active,
                )
                for claim in item.resources
            ),
        )


class AppointmentCalendarPageView(BaseModel):
    items: tuple[AppointmentCalendarEntryView, ...]
    next_cursor: str | None


class _CalendarCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter_key: str
    start_at: AwareDatetime
    reservation_id: UUID


def _filter_key(
    organization_id: UUID,
    window_start: datetime,
    window_end: datetime,
    location_id: UUID | None,
    resource_id: UUID | None,
) -> str:
    material = (
        str(organization_id),
        window_start.isoformat(),
        window_end.isoformat(),
        str(location_id),
        str(resource_id),
    )
    return hashlib.sha256(json.dumps(material).encode()).hexdigest()


def _decode_cursor(cursor: str, filter_key: str) -> CalendarPosition:
    try:
        value = _CalendarCursorParams.model_validate_json(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="cursor is invalid") from None
    if value.filter_key != filter_key:
        raise HTTPException(status_code=422, detail="cursor does not match these filters")
    return CalendarPosition(start_at=value.start_at, reservation_id=value.reservation_id)


def _encode_cursor(filter_key: str, last: AppointmentCalendarEntry) -> str:
    value = _CalendarCursorParams(
        filter_key=filter_key, start_at=last.start_at, reservation_id=last.reservation_id
    )
    return base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()


def create_appointment_calendar_router(
    reader: AppointmentCalendarReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def calendar(
        window_start: Annotated[datetime, Query()],
        window_end: Annotated[datetime, Query()],
        current: Annotated[ActorContext, Depends(actor)],
        location_id: Annotated[UUID | None, Query()] = None,
        resource_id: Annotated[
            UUID | None,
            Query(description="Only appointments whose current claim set uses this Resource"),
        ] = None,
        after: Annotated[
            str | None,
            Query(max_length=512, description="Pass next_cursor from the previous page"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_CALENDAR_LIMIT)] = 100,
    ) -> AppointmentCalendarPageView:
        """Appointments overlapping a window of at most 42 days, with their Resources.

        Rows are ordered by start then reservation id. ``resources`` is the
        Reservation's current CapacityClaim set (doctor, room, ...); after a
        cancellation or no-show it keeps the last planned Resources with
        ``claim_active=false``.
        """

        require_capability(current, "appointments.day_board")
        try:
            validate_calendar_window(window_start, window_end)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
        key = _filter_key(
            current.organization_id, window_start, window_end, location_id, resource_id
        )
        page = await reader.read_calendar(
            AppointmentCalendarQuery(
                organization_id=current.organization_id,
                window_start=window_start,
                window_end=window_end,
                location_id=location_id,
                resource_id=resource_id,
                after=_decode_cursor(after, key) if after is not None else None,
                limit=limit,
            )
        )
        return AppointmentCalendarPageView(
            items=tuple(AppointmentCalendarEntryView.from_contract(item) for item in page.items),
            next_cursor=_encode_cursor(key, page.items[-1])
            if page.has_more and page.items
            else None,
        )

    add_capability_route(
        router,
        "/appointments/calendar",
        calendar,
        capability="appointments.day_board",
        methods=["GET"],
        operation_id="appointments_calendar",
        response_model=AppointmentCalendarPageView,
    )
    return router
