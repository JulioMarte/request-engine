"""Business home and the live "Today" front desk, projected from the runtime API.

Every read and action is an existing owner operation resolved from the runtime
OpenAPI catalog by operationId. Unavailable or denied reads are shown as such;
nothing is inferred, counted or defaulted on the owner's behalf. Actions reuse
the shared executor (form intent -> Idempotency-Key) and follow
post/redirect/get so a refresh never repeats a command.

The console never decides whether the signed-in person may act for a patient:
reservation-backed actions carry the identifiers and revisions the owner read
returned, and the owner API applies Party scope or its subject-override
capability exactly as it does for any other caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.execution import (
    ExecutionOutcome,
    execute_operation,
    form_error,
)
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.session import AdminSession
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

CHIEF_OF_STAFF_PURPOSE_PREFIX = "Chief of staff"
_MAX_QUEUES = 6
_READINESS_LABELS = {
    "business_party": "Business identity",
    "locations": "Locations",
    "appointments": "Appointments",
    "walk_in_queue": "Walk-in queue",
    "communications": "Messages",
    "identity": "Sign-in",
    "tenant_control": "Owner control",
    "staff_administration": "Team administration",
    "recovery": "Recovery",
}
# Owner-facing next steps. The onboarding API's resolution hints are written for
# integrations; the console says what the person should do in their own terms.
_READINESS_GUIDANCE = {
    "business_party": "Your business record is incomplete. Ask your platform administrator.",
    "locations": "Add the place where you see customers, with its opening hours.",
    "appointments": (
        "Add a service with its price, and a person or room with weekly hours, "
        "so customers can book."
    ),
    "walk_in_queue": "Create a waiting line for customers who arrive without an appointment.",
    "communications": "Choose how confirmations and reminders reach your customers.",
    "identity": "Sign-in for this business is not ready. Ask your platform administrator.",
    "tenant_control": "Owner control is not ready. Ask your platform administrator.",
    "staff_administration": "Team management is not ready. Ask your platform administrator.",
    "recovery": (
        "Save recovery codes in Account security so you can get back in "
        "if you lose your password."
    ),
}
_READINESS_STATES = {"ready": "Ready", "blocked": "To do", "unknown": "Not checked"}
_DONE_NOTICES = {
    "called": "Next customer called.",
    "no_show": "Marked as no-show.",
    "skipped": "Customer skipped.",
    "completed": "Service finished.",
    "checked_in": "Customer checked in.",
    "walk_in": "Customer added to the queue.",
    "booked": "Appointment booked.",
    "rescheduled": "Appointment moved.",
    "cancelled": "Appointment cancelled.",
    "attendance": "Attendance answer recorded.",
    "eta": "Arrival time noted.",
    "selected": "Customer called to the counter.",
    "held": "Customer set aside.",
    "released": "Customer back in line.",
    "registered": "Customer registered.",
}
_OPEN_RESERVATION_STATUSES = frozenset({"confirmed"})
_ANSWERED_ATTENDANCE = frozenset({"accepted", "declined"})


@dataclass
class RuntimeRead:
    status: int = 0
    payload: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def denied(self) -> bool:
        return self.status == 403


def _entries() -> list[dict[str, Any]]:
    return []


@dataclass
class _QueueView:
    queue_id: str
    name: str
    location_id: str | None
    serving: list[dict[str, Any]] = field(default_factory=_entries)
    called: list[dict[str, Any]] = field(default_factory=_entries)
    waiting: list[dict[str, Any]] = field(default_factory=_entries)
    status: int = 0


def _zone(name: object) -> ZoneInfo | None:
    if not isinstance(name, str) or not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def business_zone(business: object) -> tuple[ZoneInfo, str]:
    """The business clock: its default zone, else its first location's zone, else UTC."""

    info = as_mapping(business)
    zone = _zone(info.get("default_timezone"))
    if zone is not None:
        return zone, str(info["default_timezone"])
    for location in as_list(info.get("locations")):
        zone = _zone(as_mapping(location).get("timezone"))
        if zone is not None:
            return zone, str(as_mapping(location)["timezone"])
    return ZoneInfo("UTC"), "UTC"


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def day_sheet(entries: list[dict[str, Any]], zone: ZoneInfo, now: datetime) -> list[dict[str, Any]]:
    """Hour rows that contain bookings, plus the current hour, in business time."""

    hours: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        start = _parse_instant(entry.get("start_at"))
        end = _parse_instant(entry.get("end_at"))
        if start is None:
            continue
        local_start = start.astimezone(zone)
        status = str(entry.get("status") or "")
        outcome = str(entry.get("attendance_outcome") or "")
        css = "checked-in" if entry.get("checked_in_at") else ""
        if entry.get("no_show_at") or outcome == "no_show":
            css = "no-show"
        elif status in {"cancelled", "canceled", "released", "expired"}:
            css = "cancelled"
        estimate = _parse_instant(entry.get("estimated_arrival_at"))
        # Offered actions mirror what the owner read reports; the owner still
        # validates status, revision and subject authority on every command.
        open_booking = (
            status in _OPEN_RESERVATION_STATUSES
            and not entry.get("no_show_at")
            and outcome != "no_show"
        )
        hours.setdefault(local_start.hour, []).append(
            {
                "name": entry.get("subject_display_name") or "Customer",
                "start": local_start.strftime("%H:%M"),
                "end": end.astimezone(zone).strftime("%H:%M") if end else "",
                "status": status.replace("_", " "),
                "css": css,
                "checked_in": bool(entry.get("checked_in_at")),
                "reservation_id": entry.get("reservation_id"),
                "revision": entry.get("revision"),
                "subject_party_id": entry.get("subject_party_id"),
                "offering_version_id": entry.get("offering_version_id"),
                "location_id": entry.get("location_id"),
                "attendance": str(entry.get("attendance_status") or ""),
                "eta": estimate.astimezone(zone).strftime("%H:%M") if estimate else "",
                "open": open_booking and bool(entry.get("reservation_id")),
                "can_check_in": open_booking
                and not entry.get("checked_in_at")
                and not entry.get("active_queue_entry_count"),
                "needs_answer": open_booking
                and str(entry.get("attendance_status") or "") not in _ANSWERED_ATTENDANCE,
            }
        )
    current_hour = now.astimezone(zone).hour
    rows = sorted(set(hours) | {current_hour})
    return [
        {"hour": f"{hour:02d}:00", "now": hour == current_hour, "bookings": hours.get(hour, [])}
        for hour in rows
    ]


def _queue_view(queue: dict[str, Any], read: RuntimeRead) -> _QueueView:
    view = _QueueView(
        queue_id=str(queue.get("id")),
        name=str(queue.get("display_name") or queue.get("queue_key") or "Queue"),
        location_id=queue.get("location_id") if isinstance(queue.get("location_id"), str) else None,
        status=read.status,
    )
    if not read.ok:
        return view
    for raw in as_list(read.payload):
        entry = dict(as_mapping(raw))
        service = entry.get("service_status")
        if service in {"in_progress", "paused"}:
            view.serving.append(entry)
        elif entry.get("status") == "called":
            view.called.append(entry)
        elif entry.get("status") in {"waiting", "arrived", "admitted", "checked_in"}:
            view.waiting.append(entry)
    view.waiting.sort(key=lambda item: str(item.get("admitted_at") or item.get("arrived_at") or ""))
    return view


def _readiness(payload: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in as_mapping(payload).items():
        section = as_mapping(value)
        status = section.get("status")
        if not isinstance(status, str):
            continue
        hints = [
            str(as_mapping(blocker).get("resolution_hint"))
            for blocker in as_list(section.get("blockers"))
            if as_mapping(blocker).get("resolution_hint")
        ]
        rows.append(
            {
                "key": key,
                "label": _READINESS_LABELS.get(key, key.replace("_", " ").capitalize()),
                "status": status,
                "state_label": _READINESS_STATES.get(status, status.capitalize()),
                "hint": _READINESS_GUIDANCE.get(key) or (hints[0] if hints else ""),
            }
        )
    return rows


async def runtime_operations(
    state: AdminConsoleState, names: tuple[str, ...]
) -> dict[str, AdminOperation | None]:
    """Resolve owner operations by operationId from the live runtime catalog."""

    catalog = (await state.runtime_catalog()).by_id()
    return {name: catalog.get(name) for name in names}


async def runtime_read(
    state: AdminConsoleState,
    operation: AdminOperation | None,
    *,
    organization_id: str,
    bearer: str,
    path_values: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> RuntimeRead:
    """Run one owner Query; a missing or non-GET operation is reported as unread."""

    if operation is None or operation.method.upper() != "GET":
        return RuntimeRead(status=0)
    path = operation.path_template
    for name, value in (path_values or {}).items():
        path = path.replace("{" + name + "}", quote(value, safe=""))
    try:
        response = await state.runtime_request(
            "GET", path, organization_id=organization_id, bearer=bearer, params=params
        )
    except (httpx.HTTPError, RuntimeError):
        return RuntimeRead(status=503)
    return RuntimeRead(status=response.status_code, payload=response.payload)


def workspace_unavailable(state: AdminConsoleState, request: Request, title: str) -> Response:
    return state.templates.TemplateResponse(
        request,
        "unavailable.html",
        state.context(
            request,
            title=title,
            message="Configure the runtime API URL to open this business workspace.",
        ),
        status_code=503,
    )


def local_instant(day: str, clock: str, zone_name: str) -> str | None:
    """Turn a business-local date and HH:MM into an absolute ISO instant.

    This is presentation only: the owner validates the resulting instant.
    """

    zone = _zone(zone_name)
    if zone is None:
        return None
    try:
        local_day = date.fromisoformat(day)
        local_clock = time.fromisoformat(clock)
    except ValueError:
        return None
    instant = datetime.combine(local_day, local_clock.replace(tzinfo=None), tzinfo=zone)
    return instant.astimezone(UTC).isoformat()


def today_path(organization_id: UUID | str) -> str:
    return f"/tenants/{organization_id}/today"


@dataclass(frozen=True)
class FrontDeskPost:
    """A CSRF-verified front-desk form submission for the signed-in session."""

    session: AdminSession
    values: dict[str, str]


async def front_desk_post(
    state: AdminConsoleState, request: Request, organization_id: UUID
) -> FrontDeskPost | Response:
    session = state.session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    if state.runtime is None:
        return workspace_unavailable(state, request, "Today unavailable")
    form = await request.form()
    values = {key: str(value) for key, value in form.items()}
    if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
        # A forged or stale form never reaches the owner API.
        return RedirectResponse(today_path(organization_id) + "?done=", status_code=303)
    return FrontDeskPost(session=session, values=values)


def front_desk_failure(
    state: AdminConsoleState,
    request: Request,
    organization_id: UUID,
    outcome: ExecutionOutcome,
    *,
    back: str,
) -> Response:
    return state.templates.TemplateResponse(
        request,
        "resources/today_action_failed.html",
        state.context(
            request,
            organization_id=str(organization_id),
            result=outcome.to_view(),
            revision_conflict=outcome.error_code == "revision_conflict",
            back=back,
        ),
        status_code=outcome.status if 400 <= outcome.status < 600 else 502,
    )


SubmissionBuilder = Callable[[Mapping[str, str]], "dict[str, str] | ExecutionOutcome"]


async def front_desk_action(
    state: AdminConsoleState,
    request: Request,
    organization_id: UUID,
    operation_id: str,
    build: SubmissionBuilder,
    *,
    done: str,
    back: str | None = None,
    success_location: Callable[[ExecutionOutcome], str | None] | None = None,
) -> Response:
    """Execute one owner command through the shared executor (PRG on success).

    ``build`` maps the browser form onto the owner operation's own field names;
    the executor then validates them against the runtime OpenAPI schema and uses
    the form intent as the ``Idempotency-Key``.
    """

    back = back or today_path(organization_id)
    post = await front_desk_post(state, request, organization_id)
    if not isinstance(post, FrontDeskPost):
        return post
    operation = (await runtime_operations(state, (operation_id,)))[operation_id]
    if operation is None:
        return Response("This action is not available on this installation", status_code=503)
    submitted = build(post.values)
    if isinstance(submitted, ExecutionOutcome):
        return front_desk_failure(state, request, organization_id, submitted, back=back)
    submitted["_intent_id"] = post.values.get("_intent_id", "")
    outcome = await execute_operation(
        state,
        operation,
        bearer=post.session.access_token,
        form=submitted,
        surface="runtime",
        organization_id=str(organization_id),
    )
    if not outcome.ok:
        return front_desk_failure(state, request, organization_id, outcome, back=back)
    location = success_location(outcome) if success_location is not None else None
    location = location or f"{today_path(organization_id)}?done={done}"
    return RedirectResponse(location, status_code=303)


def _picked(
    values: Mapping[str, str], names: tuple[str, ...], fixed: dict[str, str]
) -> dict[str, str]:
    submitted = {name: values[name] for name in names if values.get(name, "") != ""}
    submitted.update(fixed)
    return submitted


def pick(*names: str, **fixed: str) -> SubmissionBuilder:
    """Forward only the named non-empty form fields plus fixed path values."""

    return lambda values: _picked(values, names, fixed)


def _with_local_instant(target: str, names: tuple[str, ...], **fixed: str) -> SubmissionBuilder:
    """Like :func:`pick`, adding ``target`` from business-local date/time fields."""

    def build(values: Mapping[str, str]) -> dict[str, str] | ExecutionOutcome:
        submitted = _picked(values, names, fixed)
        clock = values.get("local_time", "").strip()
        if not clock:
            return submitted
        instant = local_instant(values.get("local_date", ""), clock, values.get("zone_name", ""))
        if instant is None:
            return form_error("Enter a valid time, for example 10:30.")
        submitted[target] = instant
        return submitted

    return build


def install_tenant_workspace_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _operations(names: tuple[str, ...]) -> dict[str, AdminOperation | None]:
        return await runtime_operations(state, names)

    async def _read(
        operation: AdminOperation | None,
        *,
        organization_id: str,
        bearer: str,
        path_values: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> RuntimeRead:
        return await runtime_read(
            state,
            operation,
            organization_id=organization_id,
            bearer=bearer,
            path_values=path_values,
            params=params,
        )

    def _unavailable(request: Request, title: str) -> Response:
        return workspace_unavailable(state, request, title)

    async def home(request: Request, organization_id: UUID) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(f"/login?next=/tenants/{organization_id}", status_code=303)
        if state.runtime is None:
            return _unavailable(request, "Business home unavailable")
        org = str(organization_id)
        try:
            ops = await _operations(
                (
                    "business_get_info",
                    "onboarding_read",
                    "staff_overview_get",
                    "agent_list",
                    "staff_invitation_proposal_list",
                )
            )
        except Exception:
            return Response("Business operation catalog unavailable", status_code=503)
        bearer = session.access_token
        business, readiness, team, agents, proposals = await asyncio.gather(
            _read(ops["business_get_info"], organization_id=org, bearer=bearer),
            _read(ops["onboarding_read"], organization_id=org, bearer=bearer),
            _read(ops["staff_overview_get"], organization_id=org, bearer=bearer),
            _read(ops["agent_list"], organization_id=org, bearer=bearer, params={"limit": "50"}),
            _read(
                ops["staff_invitation_proposal_list"],
                organization_id=org,
                bearer=bearer,
                params={"status": "pending", "limit": "50"},
            ),
        )
        if 401 in {business.status, readiness.status, team.status}:
            response = RedirectResponse("/login", status_code=303)
            state.clear_session(response, request)
            return response
        agent_items = [
            as_mapping(item) for item in as_list(as_mapping(agents.payload).get("items"))
        ]
        chief = next(
            (
                item
                for item in agent_items
                if str(item.get("purpose") or "").startswith(CHIEF_OF_STAFF_PURPOSE_PREFIX)
                and item.get("status") != "revoked"
            ),
            None,
        )
        readiness_rows = _readiness(readiness.payload) if readiness.ok else []
        info = as_mapping(business.payload) if business.ok else {}
        return state.templates.TemplateResponse(
            request,
            "resources/business_home.html",
            state.context(
                request,
                organization_id=org,
                business=info,
                business_status=business.status,
                readiness=readiness_rows,
                readiness_status=readiness.status,
                ready_count=sum(1 for row in readiness_rows if row["status"] == "ready"),
                team=as_mapping(team.payload) if team.ok else None,
                team_status=team.status,
                agents=agent_items if agents.ok else None,
                agents_status=agents.status,
                chief=chief,
                pending_proposals=(
                    len(as_list(as_mapping(proposals.payload).get("items")))
                    if proposals.ok
                    else None
                ),
            ),
        )

    async def today(request: Request, organization_id: UUID, done: str = "") -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(
                f"/login?next=/tenants/{organization_id}/today", status_code=303
            )
        if state.runtime is None:
            return _unavailable(request, "Today unavailable")
        org = str(organization_id)
        try:
            ops = await _operations(
                ("business_get_info", "queue_list", "queue_staff_read", "appointments_day_board")
            )
        except Exception:
            return Response("Business operation catalog unavailable", status_code=503)
        bearer = session.access_token
        business, queues = await asyncio.gather(
            _read(ops["business_get_info"], organization_id=org, bearer=bearer),
            _read(ops["queue_list"], organization_id=org, bearer=bearer),
        )
        if 401 in {business.status, queues.status}:
            response = RedirectResponse("/login", status_code=303)
            state.clear_session(response, request)
            return response
        zone, zone_name = business_zone(business.payload)
        now = datetime.now(UTC)
        local_day = now.astimezone(zone).date()
        window_start = datetime.combine(local_day, time.min, tzinfo=zone)
        window_end = window_start + timedelta(days=1)
        active_queues = (
            [
                dict(as_mapping(item))
                for item in as_list(queues.payload)
                if as_mapping(item).get("active") is True
            ][:_MAX_QUEUES]
            if queues.ok
            else []
        )
        board, *queue_reads = await asyncio.gather(
            _read(
                ops["appointments_day_board"],
                organization_id=org,
                bearer=bearer,
                params={
                    "window_start": window_start.astimezone(UTC).isoformat(),
                    "window_end": window_end.astimezone(UTC).isoformat(),
                    "limit": "200",
                },
            ),
            *(
                _read(
                    ops["queue_staff_read"],
                    organization_id=org,
                    bearer=bearer,
                    path_values={"queue_id": str(queue.get("id"))},
                )
                for queue in active_queues
            ),
        )
        board_entries = (
            [dict(as_mapping(item)) for item in as_list(board.payload)] if board.ok else []
        )
        queue_views = [
            _queue_view(queue, read) for queue, read in zip(active_queues, queue_reads, strict=True)
        ]
        return state.templates.TemplateResponse(
            request,
            "resources/today.html",
            state.context(
                request,
                organization_id=org,
                business_name=as_mapping(business.payload).get("display_name")
                if business.ok
                else None,
                zone_name=zone_name,
                local_date=local_day,
                local_now=now.astimezone(zone).strftime("%H:%M"),
                queues=queue_views,
                queues_status=queues.status,
                board_status=board.status,
                board_entries=board_entries,
                sheet=day_sheet(board_entries, zone, now) if board.ok else [],
                checked_in_count=sum(1 for entry in board_entries if entry.get("checked_in_at")),
                waiting_count=sum(len(view.waiting) for view in queue_views),
                notice=_DONE_NOTICES.get(done),
                today_iso=local_day.isoformat(),
                intent_id=token_urlsafe(16),
            ),
        )

    async def _act(
        request: Request,
        organization_id: UUID,
        operation_id: str,
        build: SubmissionBuilder,
        done: str,
    ) -> Response:
        return await front_desk_action(
            state, request, organization_id, operation_id, build, done=done
        )

    async def call_next(request: Request, organization_id: UUID, queue_id: UUID) -> Response:
        return await _act(
            request, organization_id, "queue_call_next", pick(queue_id=str(queue_id)), "called"
        )

    async def no_show(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_mark_no_show",
            pick("expected_revision", queue_entry_id=str(entry_id)),
            "no_show",
        )

    async def skip(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_skip",
            pick("expected_revision", "reason", queue_entry_id=str(entry_id)),
            "skipped",
        )

    async def operator_select(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_operator_select",
            pick("expected_revision", "reason", queue_entry_id=str(entry_id)),
            "selected",
        )

    async def recall_hold(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_recall_hold",
            _with_local_instant(
                "until_at",
                ("expected_revision", "condition_kind", "reason"),
                queue_entry_id=str(entry_id),
            ),
            "held",
        )

    async def release_hold(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_release_recall_hold",
            pick("expected_revision", "hold_id", queue_entry_id=str(entry_id)),
            "released",
        )

    async def complete(request: Request, organization_id: UUID, session_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "service_session_complete",
            pick("expected_revision", service_session_id=str(session_id)),
            "completed",
        )

    async def check_in(request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        # The queue is the operation's path resource; the reservation and its
        # subject come from the day-board read and are validated by the owner.
        return await _act(
            request,
            organization_id,
            "queue_check_in",
            pick("queue_id", "subject_party_id", reservation_id=str(reservation_id)),
            "checked_in",
        )

    async def attendance(request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "appointments_confirm_attendance",
            pick("response", "expected_revision", reservation_id=str(reservation_id)),
            "attendance",
        )

    async def arrival_estimate(
        request: Request, organization_id: UUID, reservation_id: UUID
    ) -> Response:
        return await _act(
            request,
            organization_id,
            "appointments_record_arrival_estimate",
            _with_local_instant(
                "estimated_arrival_at",
                ("expected_revision",),
                reservation_id=str(reservation_id),
            ),
            "eta",
        )

    async def cancel(request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "appointments_cancel",
            pick("expected_revision", "reason", reservation_id=str(reservation_id)),
            "cancelled",
        )

    app.add_api_route("/tenants/{organization_id}", home, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/today", today, methods=["GET"])
    root = "/tenants/{organization_id}/today"
    for path, handler in (
        ("/queues/{queue_id}/call-next", call_next),
        ("/entries/{entry_id}/no-show", no_show),
        ("/entries/{entry_id}/skip", skip),
        ("/entries/{entry_id}/operator-select", operator_select),
        ("/entries/{entry_id}/recall-hold", recall_hold),
        ("/entries/{entry_id}/recall-hold/release", release_hold),
        ("/sessions/{session_id}/complete", complete),
        ("/appointments/{reservation_id}/check-in", check_in),
        ("/appointments/{reservation_id}/attendance", attendance),
        ("/appointments/{reservation_id}/arrival-estimate", arrival_estimate),
        ("/appointments/{reservation_id}/cancel", cancel),
    ):
        app.add_api_route(root + path, handler, methods=["POST"])


# Owner operations projected by the Today front desk (here and in
# ``routes_front_desk_booking``). Discoverability only: authority, schemas and
# revisions stay on each owner operation.
TODAY_OPERATION_IDS = frozenset(
    {
        "appointments_book",
        "appointments_cancel",
        "appointments_confirm_attendance",
        "appointments_day_board",
        "appointments_find_slots",
        "appointments_record_arrival_estimate",
        "appointments_reschedule",
        "business_get_info",
        "catalog_search_offerings",
        "parties_lookup",
        "parties_register",
        "queue_call_next",
        "queue_check_in",
        "queue_list",
        "queue_mark_no_show",
        "queue_operator_select",
        "queue_recall_hold",
        "queue_release_recall_hold",
        "queue_skip",
        "queue_staff_read",
        "service_session_complete",
    }
)

__all__ = [
    "CHIEF_OF_STAFF_PURPOSE_PREFIX",
    "TODAY_OPERATION_IDS",
    "FrontDeskPost",
    "RuntimeRead",
    "business_zone",
    "day_sheet",
    "front_desk_action",
    "front_desk_failure",
    "front_desk_post",
    "install_tenant_workspace_routes",
    "local_instant",
    "pick",
    "runtime_operations",
    "runtime_read",
    "today_path",
    "workspace_unavailable",
]
