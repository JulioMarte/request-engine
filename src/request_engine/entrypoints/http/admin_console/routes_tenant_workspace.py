"""Business home and the live "Today" front desk, projected from the runtime API.

Every read and action is an existing owner operation resolved from the runtime
OpenAPI catalog by operationId. Unavailable or denied reads are shown as such;
nothing is inferred, counted or defaulted on the owner's behalf. Actions reuse
the shared executor (form intent -> Idempotency-Key) and follow
post/redirect/get so a refresh never repeats a command.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.execution import execute_operation
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
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
_DONE_NOTICES = {
    "called": "Next customer called.",
    "no_show": "Marked as no-show.",
    "skipped": "Customer skipped.",
    "completed": "Service finished.",
    "checked_in": "Customer checked in.",
}


@dataclass
class _Read:
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
        hours.setdefault(local_start.hour, []).append(
            {
                "name": entry.get("subject_display_name") or "Customer",
                "start": local_start.strftime("%H:%M"),
                "end": end.astimezone(zone).strftime("%H:%M") if end else "",
                "status": status.replace("_", " "),
                "css": css,
                "checked_in": bool(entry.get("checked_in_at")),
            }
        )
    current_hour = now.astimezone(zone).hour
    rows = sorted(set(hours) | {current_hour})
    return [
        {"hour": f"{hour:02d}:00", "now": hour == current_hour, "bookings": hours.get(hour, [])}
        for hour in rows
    ]


def _queue_view(queue: dict[str, Any], read: _Read) -> _QueueView:
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
                "hint": hints[0] if hints else "",
            }
        )
    return rows


def install_tenant_workspace_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _operations(names: tuple[str, ...]) -> dict[str, AdminOperation | None]:
        catalog = (await state.runtime_catalog()).by_id()
        return {name: catalog.get(name) for name in names}

    async def _read(
        operation: AdminOperation | None,
        *,
        organization_id: str,
        bearer: str,
        path_values: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> _Read:
        if operation is None or operation.method.upper() != "GET":
            return _Read(status=0)
        path = operation.path_template
        for name, value in (path_values or {}).items():
            path = path.replace("{" + name + "}", quote(value, safe=""))
        try:
            response = await state.runtime_request(
                "GET", path, organization_id=organization_id, bearer=bearer, params=params
            )
        except (httpx.HTTPError, RuntimeError):
            return _Read(status=503)
        return _Read(status=response.status_code, payload=response.payload)

    def _unavailable(request: Request, title: str) -> Response:
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
                intent_id=token_urlsafe(16),
            ),
        )

    async def _act(
        request: Request,
        organization_id: UUID,
        operation_id: str,
        path_values: dict[str, str],
        allowed_fields: tuple[str, ...],
        done: str,
    ) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if state.runtime is None:
            return _unavailable(request, "Today unavailable")
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        back = f"/tenants/{organization_id}/today"
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return RedirectResponse(back + "?done=", status_code=303)
        operation = (await _operations((operation_id,)))[operation_id]
        if operation is None:
            return Response("This action is not available on this installation", status_code=503)
        submitted = {name: values[name] for name in allowed_fields if values.get(name, "") != ""}
        submitted.update(path_values)
        submitted["_intent_id"] = values.get("_intent_id", "")
        outcome = await execute_operation(
            state,
            operation,
            bearer=session.access_token,
            form=submitted,
            surface="runtime",
            organization_id=str(organization_id),
        )
        if outcome.ok:
            return RedirectResponse(f"{back}?done={done}", status_code=303)
        return state.templates.TemplateResponse(
            request,
            "resources/today_action_failed.html",
            state.context(
                request,
                organization_id=str(organization_id),
                result=outcome.to_view(),
                back=back,
            ),
            status_code=outcome.status if 400 <= outcome.status < 600 else 502,
        )

    async def call_next(request: Request, organization_id: UUID, queue_id: UUID) -> Response:
        return await _act(
            request, organization_id, "queue_call_next", {"queue_id": str(queue_id)}, (), "called"
        )

    async def no_show(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_mark_no_show",
            {"queue_entry_id": str(entry_id)},
            ("expected_revision",),
            "no_show",
        )

    async def skip(request: Request, organization_id: UUID, entry_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "queue_skip",
            {"queue_entry_id": str(entry_id)},
            ("expected_revision", "reason"),
            "skipped",
        )

    async def complete(request: Request, organization_id: UUID, session_id: UUID) -> Response:
        return await _act(
            request,
            organization_id,
            "service_session_complete",
            {"service_session_id": str(session_id)},
            ("expected_revision",),
            "completed",
        )

    app.add_api_route("/tenants/{organization_id}", home, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/today", today, methods=["GET"])
    app.add_api_route(
        "/tenants/{organization_id}/today/queues/{queue_id}/call-next", call_next, methods=["POST"]
    )
    app.add_api_route(
        "/tenants/{organization_id}/today/entries/{entry_id}/no-show", no_show, methods=["POST"]
    )
    app.add_api_route(
        "/tenants/{organization_id}/today/entries/{entry_id}/skip", skip, methods=["POST"]
    )
    app.add_api_route(
        "/tenants/{organization_id}/today/sessions/{session_id}/complete",
        complete,
        methods=["POST"],
    )


TODAY_OPERATION_IDS = frozenset(
    {
        "appointments_day_board",
        "queue_call_next",
        "queue_mark_no_show",
        "queue_skip",
        "queue_staff_read",
        "service_session_complete",
    }
)

__all__ = [
    "CHIEF_OF_STAFF_PURPOSE_PREFIX",
    "TODAY_OPERATION_IDS",
    "business_zone",
    "day_sheet",
    "install_tenant_workspace_routes",
]
