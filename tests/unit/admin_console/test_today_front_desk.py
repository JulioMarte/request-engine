"""Today front desk: each console action reaches the right owner operation.

The upstream here serves the REAL runtime OpenAPI document (built from the
native app), so field names, structured schemas, paths and idempotency rules
are the owner's, not a hand-written copy. Responses are controlled; runtime
authorization itself is proven by owner and PostgreSQL E2E tests.
"""

import html
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.clinic_setup import long_date, zone_label
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    arrival_label,
    attendance_label,
    booking_status_label,
    checked_in_count,
    seen_count,
)
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.app import create_native_app

pytestmark = [pytest.mark.unit]
ORG = "11111111-1111-4111-8111-111111111111"
QUEUE = "44444444-4444-4444-8444-444444444444"
ENTRY = "55555555-5555-4555-8555-555555555555"
RESERVATION = "66666666-6666-4666-8666-666666666666"
PARTY = "77777777-7777-4777-8777-777777777777"
VERSION = "88888888-8888-4888-8888-888888888888"
HOLD = "99999999-9999-4999-8999-999999999999"
LOCATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@cache
def _runtime_openapi() -> dict[str, Any]:
    app = create_native_app(
        session_factory=cast(Any, object()),
        native_identity_authority_id=UUID(ORG),
        appointment_option_signing_key=b"front-desk-console-test-key-32by",
    )
    return app.openapi()


def _ok(payload: object, status: int = 200) -> ControlResponse:
    return ControlResponse(status, payload, {})


def _error(status: int, code: str, message: str = "") -> ControlResponse:
    return ControlResponse(status, {"error": {"code": code, "message": message}}, {})


class _Upstream:
    def __init__(self, routes: dict[tuple[str, str], ControlResponse] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def openapi(self) -> dict[str, Any]:
        return _runtime_openapi()

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "verified-token"}, {})
        return self.routes.get(
            (method, path), ControlResponse(404, {"error": {"code": "not_found"}}, {})
        )

    async def aclose(self) -> None:
        pass

    def posted(self, path: str) -> list[dict[str, Any]]:
        return [
            kwargs for method, called, kwargs in self.calls if method == "POST" and called == path
        ]


_BUSINESS = _ok(
    {
        "display_name": "Consultorio Duarte",
        "default_timezone": "America/Santo_Domingo",
        "locations": [
            {"id": LOCATION, "display_name": "Sede Gazcue", "timezone": "America/Santo_Domingo"}
        ],
    }
)


def _today_routes() -> dict[tuple[str, str], ControlResponse]:
    return {
        ("GET", "/v1/business"): _BUSINESS,
        ("GET", "/v1/queues"): _ok(
            [
                {
                    "id": QUEUE,
                    "display_name": "Sala de espera",
                    "active": True,
                    "location_id": LOCATION,
                }
            ]
        ),
        ("GET", f"/v1/queues/{QUEUE}/staff"): _ok(
            [
                {
                    "queue_entry_id": ENTRY,
                    "subject_display_name": "Luis Rojas",
                    "status": "waiting",
                    "admitted_at": "2026-10-20T13:00:00Z",
                    "queue_revision": 4,
                    "recall_hold_id": None,
                }
            ]
        ),
        ("GET", "/v1/appointments/day-board"): _ok(
            [
                {
                    "reservation_id": RESERVATION,
                    "offering_version_id": VERSION,
                    "subject_party_id": PARTY,
                    "subject_display_name": "María Pérez",
                    "location_id": LOCATION,
                    "start_at": "2026-10-21T14:00:00Z",
                    "end_at": "2026-10-21T14:30:00Z",
                    "status": "confirmed",
                    "revision": 3,
                    "attendance_status": "pending",
                    "attendance_outcome": "pending",
                    "checked_in_at": None,
                    "no_show_at": None,
                    "active_queue_entry_count": 0,
                }
            ]
        ),
    }


def _console(tmp_path: Path, runtime: _Upstream) -> FastAPI:
    settings = AdminConsoleSettings(
        session_store_directory=tmp_path / "sessions",
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )
    return create_admin_console_app(settings, client=_Upstream(), runtime_client=runtime)


@asynccontextmanager
async def _signed_in(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "password"})
        yield client


def _csrf(text: str) -> str:
    marker = 'data-csrf="'
    start = text.index(marker) + len(marker)
    return text[start : text.index('"', start)]


async def _today_csrf(client: httpx.AsyncClient) -> str:
    page = await client.get(f"/tenants/{ORG}/today")
    assert page.status_code == 200, page.text
    return _csrf(page.text)


@pytest.mark.asyncio
async def test_today_offers_appointment_and_queue_actions_from_owner_reads(tmp_path: Path) -> None:
    runtime = _Upstream(_today_routes())
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    text = page.text
    assert f"/today/appointments/{RESERVATION}/check-in" in text
    assert f"/today/appointments/{RESERVATION}/attendance" in text
    assert f"/today/appointments/{RESERVATION}/arrival-estimate" in text
    assert f"/today/appointments/{RESERVATION}/cancel" in text
    assert f"offering_version_id={VERSION}&amp;revision=3" in text
    assert f"/today/entries/{ENTRY}/operator-select" in text
    assert f"/today/entries/{ENTRY}/recall-hold" in text
    # The subject comes from the owner read, never typed by the operator.
    assert f'name="subject_party_id" value="{PARTY}"' in text
    assert 'href="/tenants/' + ORG + '/today/visit"' in text


@pytest.mark.asyncio
async def test_finished_or_cancelled_bookings_offer_no_actions(tmp_path: Path) -> None:
    routes = _today_routes()
    board = cast(list[dict[str, Any]], routes[("GET", "/v1/appointments/day-board")].payload)
    board[0] = {**board[0], "status": "cancelled"}
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    assert "María Pérez" in page.text
    assert f"/today/appointments/{RESERVATION}/" not in page.text


@pytest.mark.parametrize(
    ("path", "form", "upstream", "body", "done"),
    [
        (
            f"/today/appointments/{RESERVATION}/check-in",
            {"queue_id": QUEUE, "subject_party_id": PARTY},
            f"/v1/queues/{QUEUE}/check-in",
            {"subject_party_id": PARTY, "reservation_id": RESERVATION},
            "checked_in",
        ),
        (
            f"/today/appointments/{RESERVATION}/attendance",
            {"response": "accepted", "expected_revision": "3"},
            f"/v1/appointments/{RESERVATION}/attendance",
            {"response": "accepted", "expected_revision": 3},
            "attendance",
        ),
        (
            f"/today/appointments/{RESERVATION}/arrival-estimate",
            {
                "expected_revision": "3",
                "local_time": "10:40",
                "local_date": "2026-10-21",
                "zone_name": "America/Santo_Domingo",
            },
            f"/v1/appointments/{RESERVATION}/arrival-estimate",
            # 10:40 in Santo Domingo (UTC-4) is 14:40 UTC.
            {"estimated_arrival_at": "2026-10-21T14:40:00+00:00", "expected_revision": 3},
            "eta",
        ),
        (
            f"/today/appointments/{RESERVATION}/cancel",
            {"expected_revision": "3"},
            f"/v1/appointments/{RESERVATION}/cancel",
            {"expected_revision": 3},
            "cancelled",
        ),
        (
            f"/today/entries/{ENTRY}/operator-select",
            {"expected_revision": "4", "reason": "urgent"},
            f"/v1/queue-entries/{ENTRY}/operator-select",
            {"reason": "urgent", "expected_revision": 4},
            "selected",
        ),
        (
            f"/today/entries/{ENTRY}/recall-hold",
            {
                "expected_revision": "4",
                "condition_kind": "until_time",
                "local_time": "11:15",
                "local_date": "2026-10-21",
                "zone_name": "America/Santo_Domingo",
                "reason": "Lab results",
            },
            f"/v1/queue-entries/{ENTRY}/recall-hold",
            {
                "condition_kind": "until_time",
                "expected_revision": 4,
                "until_at": "2026-10-21T15:15:00+00:00",
                "reason": "Lab results",
            },
            "held",
        ),
        (
            f"/today/entries/{ENTRY}/recall-hold",
            {"expected_revision": "4", "condition_kind": "until_customer_initiates"},
            f"/v1/queue-entries/{ENTRY}/recall-hold",
            {"condition_kind": "until_customer_initiates", "expected_revision": 4},
            "held",
        ),
        (
            f"/today/entries/{ENTRY}/recall-hold/release",
            {"expected_revision": "5", "hold_id": HOLD},
            f"/v1/queue-entries/{ENTRY}/recall-hold/release",
            {"hold_id": HOLD, "expected_revision": 5},
            "released",
        ),
        (
            f"/today/visit/{PARTY}/book",
            {"option_id": "signed.option.token"},
            "/v1/appointments",
            {"option_id": "signed.option.token", "subject_party_id": PARTY},
            "booked",
        ),
        (
            f"/today/visit/{PARTY}/walk-in",
            {"queue_id": QUEUE},
            f"/v1/queues/{QUEUE}/check-in",
            {"subject_party_id": PARTY},
            "walk_in",
        ),
        (
            f"/today/appointments/{RESERVATION}/reschedule",
            {"option_id": "signed.option.later", "expected_revision": "3"},
            f"/v1/appointments/{RESERVATION}/reschedule",
            {"option_id": "signed.option.later", "expected_revision": 3},
            "rescheduled",
        ),
    ],
)
@pytest.mark.asyncio
async def test_front_desk_action_calls_owner_operation_with_intent_key(
    tmp_path: Path,
    path: str,
    form: dict[str, str],
    upstream: str,
    body: dict[str, Any],
    done: str,
) -> None:
    routes = _today_routes()
    routes[("POST", upstream)] = _ok({"status": "ok"})
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        response = await client.post(
            f"/tenants/{ORG}{path}",
            data={"csrf_token": csrf, "_intent_id": "front-desk-intent-01", **form},
        )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/tenants/{ORG}/today?done={done}"
    (call,) = runtime.posted(upstream)
    assert call["json_body"] == body
    assert call["extra_headers"]["idempotency-key"] == "front-desk-intent-01"
    assert call["extra_headers"]["X-RE-Organization-ID"] == ORG
    assert call["bearer"] == "verified-token"


@pytest.mark.asyncio
async def test_revision_conflict_is_explained_and_never_retried(tmp_path: Path) -> None:
    routes = _today_routes()
    routes[("POST", f"/v1/appointments/{RESERVATION}/cancel")] = _error(
        409, "revision_conflict", "Reservation revision changed"
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        response = await client.post(
            f"/tenants/{ORG}/today/appointments/{RESERVATION}/cancel",
            data={"csrf_token": csrf, "_intent_id": "cancel-intent-0001", "expected_revision": "2"},
        )
    assert response.status_code == 409
    assert "Otra persona cambió esta cita" in response.text
    assert len(runtime.posted(f"/v1/appointments/{RESERVATION}/cancel")) == 1


@pytest.mark.asyncio
async def test_owner_denial_and_forged_forms_never_succeed(tmp_path: Path) -> None:
    routes = _today_routes()
    routes[("POST", "/v1/appointments")] = _error(403, "forbidden", "Subject authority required")
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        denied = await client.post(
            f"/tenants/{ORG}/today/visit/{PARTY}/book",
            data={"csrf_token": csrf, "_intent_id": "book-intent-00001", "option_id": "tok"},
        )
        forged = await client.post(
            f"/tenants/{ORG}/today/visit/{PARTY}/book",
            data={"csrf_token": "wrong", "_intent_id": "book-intent-00002", "option_id": "tok"},
        )
    assert denied.status_code == 403
    assert "permiso" in denied.text
    assert forged.status_code == 303 and forged.headers["location"].endswith("?done=")
    assert len(runtime.posted("/v1/appointments")) == 1


@pytest.mark.asyncio
async def test_invalid_local_time_is_rejected_before_the_owner_call(tmp_path: Path) -> None:
    runtime = _Upstream(_today_routes())
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        response = await client.post(
            f"/tenants/{ORG}/today/appointments/{RESERVATION}/arrival-estimate",
            data={
                "csrf_token": csrf,
                "_intent_id": "eta-intent-000001",
                "expected_revision": "3",
                "local_time": "25:99",
                "local_date": "2026-10-21",
                "zone_name": "America/Santo_Domingo",
            },
        )
    assert response.status_code == 422
    assert not runtime.posted(f"/v1/appointments/{RESERVATION}/arrival-estimate")


@pytest.mark.asyncio
async def test_customer_lookup_posts_privately_and_links_to_the_owner_party(
    tmp_path: Path,
) -> None:
    routes = _today_routes()
    routes[("GET", "/v1/parties/lookup")] = _ok(
        [
            {
                "party_id": PARTY,
                "party_kind": "person",
                "display_name": "María Pérez",
                "active": True,
                "contact_points": [{"channel": "phone", "value": "+18095550101"}],
                "documents": [],
            }
        ]
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        visit = await client.get(f"/tenants/{ORG}/today/visit")
        found = await client.post(
            f"/tenants/{ORG}/today/visit/lookup",
            data={"csrf_token": _csrf(visit.text), "mode": "phone", "value": "809-555-0101"},
        )
    assert found.status_code == 200
    assert f'href="/tenants/{ORG}/today/visit/{PARTY}"' in found.text
    lookup = next(call for call in runtime.calls if call[1] == "/v1/parties/lookup")
    assert lookup[0] == "GET"
    assert lookup[2]["params"] == {"mode": "phone", "value": "809-555-0101"}


@pytest.mark.asyncio
async def test_registration_maps_plain_fields_onto_owner_schema(tmp_path: Path) -> None:
    routes = _today_routes()
    routes[("POST", "/v1/parties")] = _ok({"party_id": PARTY, "display_name": "Ana Gil"}, 201)
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        visit = await client.get(f"/tenants/{ORG}/today/visit")
        created = await client.post(
            f"/tenants/{ORG}/today/visit/register",
            data={
                "csrf_token": _csrf(visit.text),
                "_intent_id": "register-intent-01",
                "display_name": "Ana Gil",
                "phone": "8095550199",
                "cedula": "00112345678",
            },
        )
        bare = await client.post(
            f"/tenants/{ORG}/today/visit/register",
            data={
                "csrf_token": _csrf(visit.text),
                "_intent_id": "register-intent-02",
                "display_name": "Sin Contacto",
            },
        )
    assert created.status_code == 303
    assert created.headers["location"] == f"/tenants/{ORG}/today/visit/{PARTY}?done=registered"
    first, second = runtime.posted("/v1/parties")
    assert first["json_body"] == {
        "party_kind": "person",
        "display_name": "Ana Gil",
        "contact_points": [{"channel": "phone", "value": "8095550199"}],
        "documents": [{"kind": "cedula", "value": "00112345678"}],
    }
    assert first["extra_headers"]["idempotency-key"] == "register-intent-01"
    assert second["json_body"] == {
        "party_kind": "person",
        "display_name": "Sin Contacto",
        "contact_points": [],
        "documents": [],
    }
    assert bare.status_code == 303


@pytest.mark.asyncio
async def test_slot_search_uses_business_day_and_offers_signed_options(tmp_path: Path) -> None:
    routes = _today_routes()
    routes[("GET", "/v1/catalog/offerings")] = _ok(
        {
            "items": [
                {
                    "id": VERSION,
                    "display_name": "Consulta general",
                    "latest_version": {"id": VERSION, "duration_minutes": 30},
                }
            ],
            "next_cursor": None,
        }
    )
    routes[("GET", "/v1/appointments/slots")] = _ok(
        [
            {
                "option_id": "signed.option.token",
                "start_at": "2026-10-22T13:00:00Z",
                "end_at": "2026-10-22T13:30:00Z",
                "location_id": LOCATION,
                "amount": "1500.00",
                "currency": "DOP",
            }
        ]
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(
            f"/tenants/{ORG}/today/visit/{PARTY}",
            params={"offering_version_id": VERSION, "day": "2026-10-22"},
        )
    assert page.status_code == 200
    assert 'value="signed.option.token"' in page.text
    assert "09:00–09:30" in page.text and "Sede Gazcue" in page.text
    slots = next(call for call in runtime.calls if call[1] == "/v1/appointments/slots")
    params = slots[2]["params"]
    assert params["offering_version_id"] == VERSION
    # The business day 2026-10-22 in Santo Domingo starts at 04:00 UTC.
    assert params["window_start"] == "2026-10-22T04:00:00+00:00"
    assert params["window_end"] == "2026-10-23T04:00:00+00:00"


RESOURCE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SECOND_RESOURCE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SESSION = "abababab-abab-4bab-8bab-abababababab"
_SERVING_PATH = f"/v1/locations/{LOCATION}/serving-resources"


def _html_text(markup: str) -> str:
    """Visible text with tags removed and whitespace collapsed (entities decoded)."""

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _called_entry(**changes: Any) -> dict[str, Any]:
    return {
        "queue_entry_id": ENTRY,
        "subject_display_name": "Luis Rojas",
        "status": "called",
        "admitted_at": "2026-10-20T13:00:00Z",
        "queue_revision": 5,
        "service_session_id": None,
        "service_status": None,
        "service_revision": None,
        "recall_hold_id": None,
        **changes,
    }


def _service_routes() -> dict[tuple[str, str], ControlResponse]:
    routes = _today_routes()
    routes[("GET", f"/v1/queues/{QUEUE}/staff")] = _ok([_called_entry()])
    routes[("GET", _SERVING_PATH)] = _ok(
        {
            "location_id": LOCATION,
            "observed_at": "2026-10-22T14:00:00Z",
            "items": [
                {"resource_id": RESOURCE, "display_name": "Dra. Ana Pérez"},
                {"resource_id": SECOND_RESOURCE, "display_name": "Consultorio 2"},
            ],
        }
    )
    return routes


@pytest.mark.asyncio
async def test_called_customer_can_start_service_with_staff_at_the_queue_location(
    tmp_path: Path,
) -> None:
    runtime = _Upstream(_service_routes())
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    text = page.text
    assert page.status_code == 200, text
    assert f"/today/entries/{ENTRY}/start-service" in text
    assert 'name="expected_queue_revision" value="5"' in text
    # The owner's serving set for this queue's location is offered as-is.
    assert f'value="{RESOURCE}@{LOCATION}"' in text and "Dra. Ana Pérez" in text
    assert f'value="{SECOND_RESOURCE}@{LOCATION}"' in text and "Consultorio 2" in text
    # Only the location-scoped owner read is used: no supply/authority reads.
    paths = {call[1] for call in runtime.calls}
    assert _SERVING_PATH in paths
    assert not paths & {
        "/v1/me/authority",
        "/v1/booking/resources",
        "/v1/operations/resource-assignments",
    }


@pytest.mark.asyncio
async def test_staff_read_is_skipped_when_nobody_is_waiting_to_start(tmp_path: Path) -> None:
    runtime = _Upstream(_today_routes())
    async with _signed_in(_console(tmp_path, runtime)) as client:
        await client.get(f"/tenants/{ORG}/today")
    assert not [call for call in runtime.calls if call[1] == _SERVING_PATH]


@pytest.mark.parametrize(
    ("answer", "explanation"),
    [
        (
            _error(403, "capability_required"),
            "necesita el permiso «Iniciar atención»",
        ),
        (
            _error(503, "unavailable"),
            "No se pudo cargar la lista de médicos y consultorios",
        ),
    ],
)
@pytest.mark.asyncio
async def test_missing_staff_read_is_explained_instead_of_a_broken_form(
    tmp_path: Path, answer: ControlResponse, explanation: str
) -> None:
    routes = _service_routes()
    routes[("GET", _SERVING_PATH)] = answer
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    assert page.status_code == 200, page.text
    assert explanation in _html_text(page.text)
    assert "/start-service" not in page.text


@pytest.mark.asyncio
async def test_no_staff_at_the_location_invites_adding_one(tmp_path: Path) -> None:
    routes = _service_routes()
    routes[("GET", _SERVING_PATH)] = _ok(
        {"location_id": LOCATION, "observed_at": "2026-10-22T14:00:00Z", "items": []}
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    assert "Ningún médico o consultorio trabaja en esta sede ahora mismo" in page.text
    assert f'href="/tenants/{ORG}/setup?step=providers"' in page.text
    assert "/start-service" not in page.text


@pytest.mark.asyncio
async def test_customer_in_service_offers_finish_not_start(tmp_path: Path) -> None:
    routes = _service_routes()
    routes[("GET", f"/v1/queues/{QUEUE}/staff")] = _ok(
        [
            _called_entry(
                status="serving",
                service_session_id=SESSION,
                # The owner read carries the ServiceSession status column itself.
                service_status="active",
                service_revision=1,
                queue_revision=6,
            )
        ]
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    text = page.text
    assert f"/today/sessions/{SESSION}/complete" in text
    assert 'name="expected_revision" value="1"' in text
    assert "En atención" in text
    assert "/start-service" not in text
    assert not [call for call in runtime.calls if call[1] == "/v1/booking/resources"]


@pytest.mark.asyncio
async def test_start_service_posts_owner_payload_with_intent_key(tmp_path: Path) -> None:
    routes = _service_routes()
    upstream = f"/v1/queue-entries/{ENTRY}/service/start"
    routes[("POST", upstream)] = _ok({"id": SESSION, "status": "in_progress"}, 201)
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        response = await client.post(
            f"/tenants/{ORG}/today/entries/{ENTRY}/start-service",
            data={
                "csrf_token": csrf,
                "_intent_id": "start-service-intent-1",
                "staff": f"{RESOURCE}@{LOCATION}",
                "expected_queue_revision": "5",
            },
        )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/tenants/{ORG}/today?done=started"
    (call,) = runtime.posted(upstream)
    assert call["json_body"] == {
        "resource_id": RESOURCE,
        "location_id": LOCATION,
        "expected_queue_revision": 5,
    }
    assert call["extra_headers"]["idempotency-key"] == "start-service-intent-1"
    assert call["bearer"] == "verified-token"


@pytest.mark.asyncio
async def test_start_service_without_a_choice_never_reaches_the_owner(tmp_path: Path) -> None:
    runtime = _Upstream(_service_routes())
    async with _signed_in(_console(tmp_path, runtime)) as client:
        csrf = await _today_csrf(client)
        response = await client.post(
            f"/tenants/{ORG}/today/entries/{ENTRY}/start-service",
            data={
                "csrf_token": csrf,
                "_intent_id": "start-service-intent-2",
                "staff": "",
                "expected_queue_revision": "5",
            },
        )
    assert response.status_code == 422
    assert "Elija el médico o consultorio" in response.text
    assert not runtime.posted(f"/v1/queue-entries/{ENTRY}/service/start")


@pytest.mark.asyncio
async def test_counts_and_labels_follow_the_owner_day_board(tmp_path: Path) -> None:
    routes = _today_routes()
    board = cast(list[dict[str, Any]], routes[("GET", "/v1/appointments/day-board")].payload)
    # Checked in through the queue: the reservation's own attendance check-in
    # stays empty and the owner reports the active queue entry instead.
    board[0] = {
        **board[0],
        "attendance_status": "accepted",
        "active_queue_entry_count": 1,
        "queue_entry_id": ENTRY,
        "queue_entry_status": "called",
    }
    board.append(
        {
            **board[0],
            "reservation_id": VERSION,
            "subject_display_name": "Pedro Gil",
            "attendance_status": "pending",
            "active_queue_entry_count": 0,
            "queue_entry_id": None,
            "queue_entry_status": None,
        }
    )
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    text = _html_text(page.text)
    assert "2 Reservadas" in text
    assert "1 Llegaron" in text
    assert "Llamado al mostrador" in text
    assert "Reservada · Confirmó que viene" in text
    assert "Reservada · Sin respuesta" in text
    assert "confirmed" not in text.casefold()
    assert "confirmada" not in text.casefold()
    # The arrived customer is not offered a second check-in; the other one is.
    assert f"/today/appointments/{RESERVATION}/check-in" not in page.text
    assert f"/today/appointments/{VERSION}/check-in" in page.text


@pytest.mark.parametrize(
    ("entry", "label"),
    [
        ({"checked_in_at": "2026-10-21T14:01:00Z"}, "Llegó"),
        ({"active_queue_entry_count": 1}, "Llegó"),
        ({"active_queue_entry_count": 1, "queue_entry_status": "waiting"}, "En la fila"),
        ({"active_queue_entry_count": 1, "queue_entry_status": "serving"}, "En atención"),
        ({"active_queue_entry_count": 0, "checked_in_at": None}, ""),
        # After the visit completes no queue entry is active any more; the
        # owner's served-visit facts keep the arrival truthful.
        ({"active_queue_entry_count": 0, "visit_arrived_at": "2026-10-21T13:50:00Z"}, "Llegó"),
        (
            {
                "active_queue_entry_count": 0,
                "visit_arrived_at": "2026-10-21T13:50:00Z",
                "served_at": "2026-10-21T14:25:00Z",
            },
            "Atendido",
        ),
        # Sent back to a queue after being seen: the live queue position wins.
        (
            {
                "active_queue_entry_count": 1,
                "queue_entry_status": "waiting",
                "served_at": "2026-10-21T14:25:00Z",
            },
            "En la fila",
        ),
    ],
)
def test_arrival_label_reads_both_owner_arrival_facts(entry: dict[str, Any], label: str) -> None:
    assert arrival_label(entry) == label
    assert checked_in_count([entry]) == (1 if label else 0)
    assert seen_count([entry]) == (1 if entry.get("served_at") else 0)


@pytest.mark.asyncio
async def test_seen_booking_reads_as_seen_and_offers_no_arrival_actions(tmp_path: Path) -> None:
    routes = _today_routes()
    board = cast(list[dict[str, Any]], routes[("GET", "/v1/appointments/day-board")].payload)
    # The day board after book -> check in -> call -> start -> finish: no active
    # queue entry and no reservation attendance check-in, only the served visit.
    board[0] = {
        **board[0],
        "active_queue_entry_count": 0,
        "queue_entry_id": None,
        "queue_entry_status": None,
        "served_queue_entry_id": ENTRY,
        "served_at": "2026-10-21T14:25:00Z",
        "visit_arrived_at": "2026-10-21T13:50:00Z",
    }
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    text = _html_text(page.text)
    # 14:25 UTC is 10:25 in Santo Domingo (UTC-4): business time, not UTC.
    assert "Atendido a las 10:25" in text
    assert "1 Llegaron" in text
    assert "1 Atendidos" in text
    assert "Sin respuesta" not in text
    assert f"/today/appointments/{RESERVATION}/check-in" not in page.text
    assert f"/today/appointments/{RESERVATION}/attendance" not in page.text
    assert f"/today/appointments/{RESERVATION}/arrival-estimate" not in page.text
    # The owner still accepts cancel/reschedule of a confirmed reservation after
    # its visit, so the console keeps offering what the owner would accept.
    assert f"/today/appointments/{RESERVATION}/cancel" in page.text


@pytest.mark.parametrize(
    ("status", "attendance", "status_label", "attendance_text"),
    [
        ("confirmed", "accepted", "Reservada", "Confirmó que viene"),
        ("confirmed", "declined", "Reservada", "Dijo que no viene"),
        ("confirmed", "pending", "Reservada", "Sin respuesta"),
        ("cancelled", "", "Cancelada", "Sin respuesta"),
        ("pending_payment", "maybe_later", "Pending payment", "Maybe later"),
    ],
)
def test_booking_and_attendance_labels_are_distinct_and_readable(
    status: str, attendance: str, status_label: str, attendance_text: str
) -> None:
    assert booking_status_label(status) == status_label
    assert attendance_label(attendance) == attendance_text


@pytest.mark.asyncio
async def test_signed_out_page_keeps_its_place_but_a_form_post_does_not(tmp_path: Path) -> None:
    app = _console(tmp_path, _Upstream(_today_routes()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        page = await client.get(f"/tenants/{ORG}/today", params={"done": "called"})
        slots = await client.get(
            f"/tenants/{ORG}/today/visit/{PARTY}", params={"offering_version_id": VERSION}
        )
        posted = await client.post(
            f"/tenants/{ORG}/today/queues/{QUEUE}/call-next", data={"csrf_token": "x"}
        )
    assert page.status_code == 303
    assert page.headers["location"] == f"/login?next=%2Ftenants%2F{ORG}%2Ftoday%3Fdone%3Dcalled"
    assert slots.headers["location"] == (
        f"/login?next=%2Ftenants%2F{ORG}%2Ftoday%2Fvisit%2F{PARTY}"
        f"%3Foffering_version_id%3D{VERSION}"
    )
    assert posted.status_code == 303 and posted.headers["location"] == "/login"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 21), "miércoles 21 de octubre"),
        (date(2026, 1, 4), "domingo 4 de enero"),
        (date(2027, 9, 6), "lunes 6 de septiembre"),
    ],
)
def test_business_dates_read_in_spanish_without_the_os_locale(day: date, expected: str) -> None:
    # Calendar facts (21 Oct 2026 is a Wednesday) are the oracle, not strftime.
    assert long_date(day) == expected
    assert zone_label("America/Santo_Domingo") == "hora de Santo Domingo"
