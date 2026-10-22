"""Front-desk visit journey: find or register the customer, then book or queue.

The receptionist acts for a customer through the same owner operations a
customer or agent uses (``parties_lookup``/``parties_register``,
``catalog_search_offerings``, ``appointments_find_slots``, ``appointments_book``,
``appointments_reschedule`` and ``queue_check_in``). The console supplies the
chosen subject Party and signed slot option exactly as the owner returned them;
whether the signed-in person may act for that subject (delegated Party scope or
the owner's subject-override capability) is decided only by the owner API.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from secrets import token_urlsafe
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import Response

from request_engine.entrypoints.http.admin_console.clinic_setup import (
    long_date,
    money_label,
    zone_label,
)
from request_engine.entrypoints.http.admin_console.execution import (
    ExecutionOutcome,
    form_error,
)
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    FrontDeskPost,
    business_zone,
    front_desk_action,
    front_desk_post,
    pick,
    runtime_operations,
    runtime_read,
    today_path,
    workspace_unavailable,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_LOOKUP_MODES = ("phone", "document", "name")
_MAX_OFFERINGS = "50"
_MAX_SLOTS = "48"


def _day(value: str, zone: ZoneInfo) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC).astimezone(zone).date()


def _window(day: date, zone: ZoneInfo) -> dict[str, str]:
    start = datetime.combine(day, time.min, tzinfo=zone)
    return {
        "window_start": start.astimezone(UTC).isoformat(),
        "window_end": (start + timedelta(days=1)).astimezone(UTC).isoformat(),
    }


def _slot_rows(
    payload: object, zone: ZoneInfo, location_names: Mapping[str, str]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in as_list(payload):
        slot = as_mapping(raw)
        option_id = slot.get("option_id")
        try:
            start = datetime.fromisoformat(str(slot.get("start_at")))
            end = datetime.fromisoformat(str(slot.get("end_at")))
        except ValueError:
            continue
        if not isinstance(option_id, str) or start.tzinfo is None or end.tzinfo is None:
            continue
        amount = slot.get("amount")
        rows.append(
            {
                "option_id": option_id,
                "start": start.astimezone(zone).strftime("%H:%M"),
                "end": end.astimezone(zone).strftime("%H:%M"),
                "location": location_names.get(str(slot.get("location_id")), ""),
                "price": money_label(amount, slot.get("currency")) if amount is not None else "",
            }
        )
    return rows


def _registration(values: Mapping[str, str]) -> dict[str, str] | ExecutionOutcome:
    """Map the plain registration form onto the owner ``parties_register`` schema."""

    name = values.get("display_name", "").strip()
    if not name:
        return form_error("Escriba el nombre completo del paciente.")
    submitted = {"display_name": name, "party_kind": "person"}
    for field, kind_key, kind, value in (
        ("contact_points", "channel", "phone", values.get("phone", "").strip()),
        ("documents", "kind", "cedula", values.get("cedula", "").strip()),
    ):
        if not value:
            continue
        submitted.update(
            {
                f"__structured__{field}": "true",
                f"__include__{field}": "true",
                f"__structured__{field}[0]": "true",
                f"{field}[0].{kind_key}": kind,
                f"{field}[0].value": value,
            }
        )
    return submitted


def _registered_party(outcome: ExecutionOutcome) -> str | None:
    try:
        party_id = as_mapping(json.loads(outcome.payload_json)).get("party_id")
        return str(UUID(str(party_id)))
    except (ValueError, TypeError):
        return None


def install_front_desk_booking_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _business(org: str, bearer: str) -> tuple[ZoneInfo, str, dict[str, str], Any]:
        ops = await runtime_operations(state, ("business_get_info",))
        business = await runtime_read(
            state, ops["business_get_info"], organization_id=org, bearer=bearer
        )
        zone, zone_name = business_zone(business.payload if business.ok else None)
        names = {
            str(as_mapping(location).get("id")): str(as_mapping(location).get("display_name"))
            for location in as_list(as_mapping(business.payload).get("locations"))
        }
        return zone, zone_name, names, business

    def _signed_in(request: Request) -> Response | None:
        if state.session(request) is None:
            return login_redirect(request)
        if state.runtime is None:
            return workspace_unavailable(state, request, "Hoy no disponible")
        return None

    def _visit_page(
        request: Request,
        organization_id: UUID,
        *,
        lookup: dict[str, Any] | None = None,
    ) -> Response:
        return state.templates.TemplateResponse(
            request,
            "resources/today_visit.html",
            state.context(
                request,
                organization_id=str(organization_id),
                lookup=lookup,
                lookup_modes=_LOOKUP_MODES,
                intent_id=token_urlsafe(16),
            ),
            status_code=200,
        )

    async def visit(request: Request, organization_id: UUID) -> Response:
        blocked = _signed_in(request)
        if blocked is not None:
            return blocked
        return _visit_page(request, organization_id)

    async def lookup(request: Request, organization_id: UUID) -> Response:
        # A POST keeps names, phones and cédulas out of URLs and browser
        # history; the owner Query itself is still a GET against the runtime.
        post = await front_desk_post(state, request, organization_id)
        if not isinstance(post, FrontDeskPost):
            return post
        mode = post.values.get("mode", "")
        value = post.values.get("value", "").strip()
        if mode not in _LOOKUP_MODES or not value:
            return _visit_page(
                request, organization_id, lookup={"status": 422, "matches": [], "mode": mode}
            )
        ops = await runtime_operations(state, ("parties_lookup",))
        read = await runtime_read(
            state,
            ops["parties_lookup"],
            organization_id=str(organization_id),
            bearer=post.session.access_token,
            params={"mode": mode, "value": value},
        )
        matches = [
            {
                "party_id": str(as_mapping(item).get("party_id")),
                "name": as_mapping(item).get("display_name"),
                "active": as_mapping(item).get("active") is not False,
                "contacts": ", ".join(
                    str(as_mapping(contact).get("value"))
                    for contact in as_list(as_mapping(item).get("contact_points"))
                ),
            }
            for item in (as_list(read.payload) if read.ok else [])
        ]
        return _visit_page(
            request,
            organization_id,
            lookup={"status": read.status, "matches": matches, "mode": mode},
        )

    async def register(request: Request, organization_id: UUID) -> Response:
        def located(outcome: ExecutionOutcome) -> str | None:
            party_id = _registered_party(outcome)
            if party_id is None:
                return None
            return f"{today_path(organization_id)}/visit/{party_id}?done=registered"

        return await front_desk_action(
            state,
            request,
            organization_id,
            "parties_register",
            _registration,
            done="registered",
            back=f"{today_path(organization_id)}/visit",
            success_location=located,
        )

    async def _slot_page(
        request: Request,
        organization_id: UUID,
        *,
        template: str,
        offering_version_id: str,
        day: str,
        extra: dict[str, Any],
    ) -> Response:
        session = state.session(request)
        assert session is not None
        org = str(organization_id)
        bearer = session.access_token
        zone, zone_name, location_names, _ = await _business(org, bearer)
        local_day = _day(day, zone)
        ops = await runtime_operations(
            state, ("catalog_search_offerings", "appointments_find_slots", "queue_list")
        )
        offerings, slots, queues = await asyncio.gather(
            runtime_read(
                state,
                ops["catalog_search_offerings"],
                organization_id=org,
                bearer=bearer,
                params={"bookable": "true", "limit": _MAX_OFFERINGS},
            ),
            runtime_read(
                state,
                ops["appointments_find_slots"] if offering_version_id else None,
                organization_id=org,
                bearer=bearer,
                params={
                    "offering_version_id": offering_version_id,
                    "limit": _MAX_SLOTS,
                    **_window(local_day, zone),
                },
            ),
            runtime_read(state, ops["queue_list"], organization_id=org, bearer=bearer),
        )
        if 401 in {offerings.status, slots.status, queues.status}:
            response = login_redirect(request)
            state.clear_session(response, request)
            return response
        offering_rows = [
            {
                "version_id": str(as_mapping(as_mapping(item).get("latest_version")).get("id")),
                "name": as_mapping(item).get("display_name"),
                "minutes": as_mapping(as_mapping(item).get("latest_version")).get(
                    "duration_minutes"
                ),
            }
            for item in as_list(as_mapping(offerings.payload).get("items"))
        ]
        return state.templates.TemplateResponse(
            request,
            template,
            state.context(
                request,
                organization_id=org,
                zone_name=zone_name,
                zone_label=zone_label(zone_name),
                day=local_day.isoformat(),
                day_label=long_date(local_day),
                offering_version_id=offering_version_id,
                offerings=offering_rows,
                offerings_status=offerings.status,
                slots=_slot_rows(slots.payload, zone, location_names) if slots.ok else [],
                slots_status=slots.status,
                queues=[
                    {
                        "id": str(as_mapping(item).get("id")),
                        "name": as_mapping(item).get("display_name")
                        or as_mapping(item).get("queue_key"),
                    }
                    for item in as_list(queues.payload)
                    if as_mapping(item).get("active") is True
                ]
                if queues.ok
                else [],
                intent_id=token_urlsafe(16),
                **extra,
            ),
        )

    async def visit_for(
        request: Request,
        organization_id: UUID,
        party_id: UUID,
        offering_version_id: str = "",
        day: str = "",
        done: str = "",
    ) -> Response:
        blocked = _signed_in(request)
        if blocked is not None:
            return blocked
        return await _slot_page(
            request,
            organization_id,
            template="resources/today_visit_slots.html",
            offering_version_id=_uuid_or_empty(offering_version_id),
            day=day,
            extra={"party_id": str(party_id), "registered": done == "registered"},
        )

    async def book(request: Request, organization_id: UUID, party_id: UUID) -> Response:
        return await front_desk_action(
            state,
            request,
            organization_id,
            "appointments_book",
            pick("option_id", subject_party_id=str(party_id)),
            done="booked",
            back=f"{today_path(organization_id)}/visit/{party_id}",
        )

    async def walk_in(request: Request, organization_id: UUID, party_id: UUID) -> Response:
        return await front_desk_action(
            state,
            request,
            organization_id,
            "queue_check_in",
            pick("queue_id", subject_party_id=str(party_id)),
            done="walk_in",
            back=f"{today_path(organization_id)}/visit/{party_id}",
        )

    async def reschedule_page(
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        offering_version_id: str = "",
        revision: str = "",
        day: str = "",
    ) -> Response:
        blocked = _signed_in(request)
        if blocked is not None:
            return blocked
        return await _slot_page(
            request,
            organization_id,
            template="resources/today_reschedule.html",
            offering_version_id=_uuid_or_empty(offering_version_id),
            day=day,
            extra={
                "reservation_id": str(reservation_id),
                "revision": revision if revision.isdigit() else "",
            },
        )

    async def reschedule(request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        return await front_desk_action(
            state,
            request,
            organization_id,
            "appointments_reschedule",
            pick("option_id", "expected_revision", reservation_id=str(reservation_id)),
            done="rescheduled",
        )

    root = "/tenants/{organization_id}/today"
    app.add_api_route(root + "/visit", visit, methods=["GET"])
    app.add_api_route(root + "/visit/lookup", lookup, methods=["POST"])
    app.add_api_route(root + "/visit/register", register, methods=["POST"])
    app.add_api_route(root + "/visit/{party_id}", visit_for, methods=["GET"])
    app.add_api_route(root + "/visit/{party_id}/book", book, methods=["POST"])
    app.add_api_route(root + "/visit/{party_id}/walk-in", walk_in, methods=["POST"])
    app.add_api_route(
        root + "/appointments/{reservation_id}/reschedule", reschedule_page, methods=["GET"]
    )
    app.add_api_route(
        root + "/appointments/{reservation_id}/reschedule", reschedule, methods=["POST"]
    )


def _uuid_or_empty(value: str) -> str:
    try:
        return str(UUID(value)) if value else ""
    except ValueError:
        return ""


__all__ = ["install_front_desk_booking_routes"]
