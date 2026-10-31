"""Guided clinic setup: each plain form reaches the exact owner operations.

The upstream serves the REAL runtime OpenAPI document (built from the native
app), so the console resolves the owners' real paths and methods by
operationId. Responses are controlled here; owner authorization, schemas and
idempotency themselves are proven by the PostgreSQL E2E journey
``tests/e2e/test_console_clinic_setup_journey.py``.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
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
from request_engine.entrypoints.http.admin_console.clinic_setup import (
    SetupInputError,
    choose_key,
    money_label,
    phone_number,
    slugify,
)
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.app import create_native_app

pytestmark = [pytest.mark.unit]
ORG = "11111111-1111-4111-8111-111111111111"
PARTY = "22222222-2222-4222-8222-222222222222"
OTHER_PARTY = "33333333-3333-4333-8333-333333333333"
LOCATION = "44444444-4444-4444-8444-444444444444"
CAPABILITY = "55555555-5555-4555-8555-555555555555"
OFFERING = "66666666-6666-4666-8666-666666666666"
VERSION = "77777777-7777-4777-8777-777777777777"
CURSOR = "88888888-8888-4888-8888-888888888888"
WEEKDAYS = {
    f"day{day}_{part}": value
    for day in range(5)
    for part, value in (("open", "on"), ("start", "08:00"), ("end", "17:00"))
}
Handler = Callable[[dict[str, Any]], ControlResponse]


@cache
def _runtime_openapi() -> dict[str, Any]:
    app = create_native_app(
        session_factory=cast(Any, object()),
        native_identity_authority_id=UUID(ORG),
        appointment_option_signing_key=b"clinic-setup-console-test-key-32b",
    )
    return app.openapi()


def _ok(payload: object, status: int = 200) -> ControlResponse:
    return ControlResponse(status, payload, {})


def _error(status: int, message: str = "") -> ControlResponse:
    return ControlResponse(status, {"error": {"code": "denied", "message": message}}, {})


def _authority(kwargs: dict[str, Any]) -> ControlResponse:
    # Page 1 holds an unrelated representation; the business Party is on page 2.
    params = cast(dict[str, str], kwargs.get("params") or {})
    if params.get("after") == CURSOR:
        return _ok(
            {
                "principal_id": ORG,
                "representations": [
                    {"represented_party_id": PARTY, "scope_key": "operations.manage_profile"}
                ],
                "next_after": None,
            }
        )
    return _ok(
        {
            "principal_id": ORG,
            "representations": [
                {"represented_party_id": OTHER_PARTY, "scope_key": "appointments.book"}
            ],
            "next_after": CURSOR,
        }
    )


def _empty_page(_: dict[str, Any]) -> ControlResponse:
    return _ok({"items": [], "next_cursor": None})


class _Upstream:
    def __init__(self, routes: dict[tuple[str, str], Handler | ControlResponse]) -> None:
        self.routes: dict[tuple[str, str], Handler | ControlResponse] = {
            ("GET", "/v1/me/authority"): _authority,
            ("GET", "/v1/business"): _ok(
                {"display_name": "Centro Médico Duarte", "locations": [], "contacts": []}
            ),
            ("GET", "/v1/catalog/locations/configuration"): _empty_page,
            ("GET", "/v1/catalog/offerings/configuration"): _empty_page,
            ("GET", "/v1/booking/resources"): _empty_page,
            ("GET", "/v1/queues/configuration"): _empty_page,
            ("GET", "/v1/catalog/resource-capabilities"): _empty_page,
            **routes,
        }
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def openapi(self) -> dict[str, Any]:
        return _runtime_openapi()

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "verified-token"}, {})
        route = self.routes.get((method, path))
        if route is None:
            return ControlResponse(404, {"error": {"code": "not_found"}}, {})
        return route(kwargs) if callable(route) else route

    async def aclose(self) -> None:
        pass

    def writes(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [call for call in self.calls if call[0] in {"POST", "PUT", "PATCH"}]

    def sent(self, method: str, path: str) -> list[dict[str, Any]]:
        return [kw for m, p, kw in self.calls if (m, p) == (method, path)]


def _console(tmp_path: Path, runtime: _Upstream) -> FastAPI:
    settings = AdminConsoleSettings(
        session_store_directory=tmp_path / "sessions",
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )
    return create_admin_console_app(settings, client=_Upstream({}), runtime_client=runtime)


@asynccontextmanager
async def _signed_in(runtime: _Upstream, tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_console(tmp_path, runtime)),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "password"})
        yield client


async def _csrf(client: httpx.AsyncClient) -> str:
    page = await client.get(f"/tenants/{ORG}/setup")
    assert page.status_code == 200, page.text
    marker = 'data-csrf="'
    start = page.text.index(marker) + len(marker)
    return page.text[start : page.text.index('"', start)]


async def _submit(
    client: httpx.AsyncClient, step: str, form: dict[str, str], intent: str = "intent-0001"
) -> httpx.Response:
    data = {"csrf_token": await _csrf(client), "_intent_id": intent, **form}
    return await client.post(f"/tenants/{ORG}/setup/{step}", data=data)


def _location_created(_: dict[str, Any]) -> ControlResponse:
    return _ok({"location_id": LOCATION, "location_key": "sede-gazcue", "operational_revision": 1})


def test_generated_keys_are_unique_and_replay_safe() -> None:
    assert slugify("Clínica Peña & Asociados") == "clinica-pena-asociados"
    assert slugify("¡¡!!", fallback="location") == "location"
    taken = [{"location_key": "sede-gazcue", "display_name": "Sede Gazcue (vieja)"}]
    assert choose_key(
        "sede-gazcue", taken, key_field="location_key", display_name="Sede Gazcue"
    ) == (
        "sede-gazcue-2",
        None,
    )
    mine = [*taken, {"location_key": "sede-gazcue-2", "display_name": "sede gazcue "}]
    key, existing = choose_key(
        "sede-gazcue", mine, key_field="location_key", display_name="Sede Gazcue"
    )
    assert key == "sede-gazcue-2" and existing is mine[1]


def test_local_phone_numbers_become_international() -> None:
    assert phone_number("809-555-0123") == "+18095550123"
    assert phone_number("+34 600 123 456") == "+34600123456"
    with pytest.raises(SetupInputError):
        phone_number("555-01")


@pytest.mark.asyncio
async def test_business_party_is_resolved_from_the_owner_across_pages(tmp_path: Path) -> None:
    runtime = _Upstream({})
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(f"/tenants/{ORG}/setup")
    assert page.status_code == 200
    assert "Configure Centro Médico Duarte" in page.text
    assert PARTY not in page.text and "authority_party_id" not in page.text
    authority = runtime.sent("GET", "/v1/me/authority")
    assert [call["params"] for call in authority] == [
        {"limit": "100"},
        {"limit": "100", "after": CURSOR},
    ]
    inventory = runtime.sent("GET", "/v1/catalog/locations/configuration")
    assert inventory[0]["params"]["authority_party_id"] == PARTY


@pytest.mark.asyncio
async def test_missing_business_party_blocks_setup_without_writing(tmp_path: Path) -> None:
    runtime = _Upstream(
        {("GET", "/v1/me/authority"): _ok({"representations": [], "next_after": None})}
    )
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(f"/tenants/{ORG}/setup?step=location")
        assert "Todavía no se puede empezar la configuración" in page.text
        assert 'action="/tenants/' + ORG + '/setup/location"' not in page.text
        refused = await _submit(client, "location", {"display_name": "Sede", **WEEKDAYS})
    assert refused.status_code == 409
    assert not runtime.writes()


@pytest.mark.asyncio
async def test_location_step_creates_then_sets_hours_and_phone(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("POST", "/v1/operations/locations"): _location_created,
            ("PUT", f"/v1/operations/locations/{LOCATION}/hours"): _ok({"operational_revision": 2}),
            ("PUT", f"/v1/operations/locations/{LOCATION}/contacts"): _ok({"contacts": []}),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(
            client,
            "location",
            {
                "display_name": "Sede Gazcue",
                "address_line1": "Av. Independencia 123",
                "locality": "Santo Domingo",
                "administrative_area": "Distrito Nacional",
                "country_code": "DO",
                "phone": "809 555 0102",
                **WEEKDAYS,
            },
        )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/tenants/{ORG}/setup?step=services&done=location"
    (create,) = runtime.sent("POST", "/v1/operations/locations")
    assert create["json_body"] == {
        "authority_party_id": PARTY,
        "location_key": "sede-gazcue",
        "display_name": "Sede Gazcue",
        "timezone": "America/Santo_Domingo",
        "country_code": "DO",
        "address_line1": "Av. Independencia 123",
        "locality": "Santo Domingo",
        "administrative_area": "Distrito Nacional",
    }
    assert create["extra_headers"]["Idempotency-Key"] == "clinic-setup:intent-0001:location"
    (hours,) = runtime.sent("PUT", f"/v1/operations/locations/{LOCATION}/hours")
    assert hours["json_body"] == {
        "authority_party_id": PARTY,
        "expected_operational_revision": 1,
        "windows": [
            {"weekday": day, "local_start": "08:00", "local_end": "17:00"} for day in range(5)
        ],
    }
    assert hours["extra_headers"]["Idempotency-Key"] == "clinic-setup:intent-0001:hours:1"
    (phone,) = runtime.sent("PUT", f"/v1/operations/locations/{LOCATION}/contacts")
    assert phone["json_body"] == {
        "authority_party_id": PARTY,
        "contacts": [{"channel": "phone", "value": "+18095550102"}],
    }


@pytest.mark.asyncio
async def test_resubmitting_an_existing_location_converges_instead_of_duplicating(
    tmp_path: Path,
) -> None:
    existing = {
        "location_id": LOCATION,
        "location_key": "sede-gazcue",
        "display_name": "Sede Gazcue",
    }
    detail = {
        **existing,
        "operational_revision": 4,
        "hours_windows": [
            {"weekday": d, "local_start": "08:00:00", "local_end": "17:00:00"} for d in range(5)
        ],
        "public_contacts": [],
    }
    runtime = _Upstream(
        {
            ("GET", "/v1/catalog/locations/configuration"): _ok(
                {"items": [existing], "next_cursor": None}
            ),
            ("GET", f"/v1/catalog/locations/{LOCATION}/configuration"): _ok(detail),
            ("PUT", f"/v1/operations/locations/{LOCATION}/hours"): _ok({"operational_revision": 5}),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        same = await _submit(client, "location", {"display_name": "Sede Gazcue", **WEEKDAYS})
        assert same.status_code == 303
        # Nothing changed: no create, and the identical hours are not replaced.
        assert not runtime.writes()
        later = await _submit(
            client,
            "location",
            {
                "display_name": "Sede Gazcue",
                **WEEKDAYS,
                "day5_open": "on",
                "day5_start": "08:00",
                "day5_end": "12:00",
            },
            intent="intent-0002",
        )
    assert later.status_code == 303
    assert [(m, p) for m, p, _ in runtime.writes()] == [
        ("PUT", f"/v1/operations/locations/{LOCATION}/hours")
    ]
    (hours,) = runtime.sent("PUT", f"/v1/operations/locations/{LOCATION}/hours")
    assert hours["json_body"]["expected_operational_revision"] == 4
    assert hours["extra_headers"]["Idempotency-Key"] == "clinic-setup:intent-0002:hours:4"


@pytest.mark.asyncio
async def test_a_different_location_with_a_colliding_key_gets_a_new_key(tmp_path: Path) -> None:
    other = {
        "location_id": LOCATION,
        "location_key": "sede-gazcue",
        "display_name": "Sede Gazcué Norte",
    }
    runtime = _Upstream(
        {
            ("GET", "/v1/catalog/locations/configuration"): _ok(
                {"items": [other], "next_cursor": None}
            ),
            ("POST", "/v1/operations/locations"): _location_created,
            ("PUT", f"/v1/operations/locations/{LOCATION}/hours"): _ok({}),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(client, "location", {"display_name": "Sede Gazcue", **WEEKDAYS})
    assert response.status_code == 303
    (create,) = runtime.sent("POST", "/v1/operations/locations")
    assert create["json_body"]["location_key"] == "sede-gazcue-2"


@pytest.mark.asyncio
async def test_invalid_hours_are_explained_and_nothing_is_sent(tmp_path: Path) -> None:
    runtime = _Upstream({})
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(
            client,
            "location",
            {"display_name": "Sede", "day1_open": "on", "day1_start": "17:00", "day1_end": "08:00"},
        )
    assert response.status_code == 422
    assert "El martes, la hora de cierre debe ser después de la hora de apertura." in response.text
    assert 'value="Sede"' in response.text  # what the person typed is kept
    assert not runtime.writes()


@pytest.mark.asyncio
async def test_service_step_runs_capability_offering_and_price(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("POST", "/v1/catalog/resource-capabilities"): _ok({"capability_id": CAPABILITY}, 201),
            ("POST", "/v1/catalog/offerings"): _ok(
                {"offering_id": OFFERING, "offering_version_id": VERSION}, 201
            ),
            ("PUT", f"/v1/operations/offering-versions/{VERSION}/booking-terms"): _ok({}),
        }
    )
    form = {
        "display_name": "Consulta general",
        "duration_minutes": "45",
        "price": "1,500.50",
        "currency": "DOP",
    }
    async with _signed_in(runtime, tmp_path) as client:
        first = await _submit(client, "services", form)
        replay = await _submit(client, "services", form)
    assert first.status_code == replay.status_code == 303
    capability = runtime.sent("POST", "/v1/catalog/resource-capabilities")
    assert capability[0]["json_body"] == {
        "authority_party_id": PARTY,
        "capability_key": "provides-consulta-general",
        "display_name": "Ofrece Consulta general",
    }
    offering = runtime.sent("POST", "/v1/catalog/offerings")
    assert offering[0]["json_body"] == {
        "authority_party_id": PARTY,
        "offering_key": "consulta-general",
        "display_name": "Consulta general",
        "duration_minutes": 45,
        "slot_step_minutes": 45,
        "requirements": [{"capability_id": CAPABILITY, "quantity": 1}],
    }
    terms = runtime.sent("PUT", f"/v1/operations/offering-versions/{VERSION}/booking-terms")
    assert terms[0]["json_body"] == {
        "authority_party_id": PARTY,
        "amount": "1500.50",
        "currency": "DOP",
    }
    # A browser replay of the same form sends the same keys, so the owner replays.
    for calls in (capability, offering, terms):
        assert len(calls) == 2
        assert (
            calls[0]["extra_headers"]["Idempotency-Key"]
            == calls[1]["extra_headers"]["Idempotency-Key"]
        )
        assert calls[0]["json_body"] == calls[1]["json_body"]


@pytest.mark.asyncio
async def test_price_is_required_because_slots_need_terms(tmp_path: Path) -> None:
    runtime = _Upstream({})
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(client, "services", {"display_name": "Consulta", "price": ""})
    assert response.status_code == 422
    assert "Use 0 si el servicio es gratis." in response.text
    assert not runtime.writes()


@pytest.mark.asyncio
async def test_provider_step_sends_location_services_and_availability(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/catalog/locations/configuration"): _ok(
                {
                    "items": [
                        {"location_id": LOCATION, "location_key": "sede", "display_name": "Sede"}
                    ],
                    "next_cursor": None,
                }
            ),
            ("GET", "/v1/catalog/offerings/configuration"): _ok(
                {
                    "items": [
                        {
                            "offering_id": OFFERING,
                            "offering_version_id": VERSION,
                            "offering_key": "consulta",
                            "display_name": "Consulta",
                            "active": True,
                            "bookable": True,
                            "duration_minutes": 30,
                        }
                    ],
                    "next_cursor": None,
                }
            ),
            ("GET", f"/v1/catalog/offering-versions/{VERSION}/configuration"): _ok(
                {"requirements": [{"capability_id": CAPABILITY, "quantity": 1}]}
            ),
            ("POST", "/v1/booking/resources"): _ok({"resource_id": OFFERING}, 201),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(f"/tenants/{ORG}/setup?step=providers")
        assert f'name="capability_id" value="{CAPABILITY}"' in page.text
        response = await _submit(
            client,
            "providers",
            {
                "display_name": "Dra. Ana Pérez",
                "kind": "doctor",
                "location_id": LOCATION,
                "capability_id": CAPABILITY,
                **WEEKDAYS,
            },
        )
    assert response.status_code == 303, response.text
    (create,) = runtime.sent("POST", "/v1/booking/resources")
    assert create["json_body"] == {
        "authority_party_id": PARTY,
        "location_id": LOCATION,
        "resource_key": "doctor-dra-ana-perez",
        "display_name": "Dra. Ana Pérez",
        "capacity_model": "exclusive",
        "capability_ids": [CAPABILITY],
        "weekly_availability": [
            {"weekday": d, "local_start": "08:00", "local_end": "17:00"} for d in range(5)
        ],
    }


@pytest.mark.asyncio
async def test_permission_refusal_is_explained_and_the_step_can_be_skipped(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("PATCH", "/v1/operations/organization/profile"): _error(403, "missing capability"),
            ("PUT", "/v1/operations/organization/contacts"): _ok({}),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(
            client, "clinic", {"legal_name": "Duarte SRL", "email": "citas@duarte.do"}
        )
    assert response.status_code == 403
    assert "Su negocio todavía no tiene permiso para cambiar su perfil." in response.text
    assert "el administrador de la plataforma debe actualizarlos" in response.text
    assert f'href="/tenants/{ORG}/setup?step=location">Saltar este paso' in response.text
    (profile,) = runtime.sent("PATCH", "/v1/operations/organization/profile")
    assert profile["json_body"] == {
        "authority_party_id": PARTY,
        "default_timezone": "America/Santo_Domingo",
        "default_currency": "DOP",
        "default_locale": "es-DO",
        "legal_name": "Duarte SRL",
    }
    assert not runtime.sent("PUT", "/v1/operations/organization/contacts")


@pytest.mark.asyncio
async def test_finish_shows_plain_readiness_and_real_free_times(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/business"): _ok(
                {
                    "display_name": "Duarte",
                    "locations": [{"id": LOCATION, "timezone": "America/Santo_Domingo"}],
                }
            ),
            ("GET", "/v1/catalog/offerings/configuration"): _ok(
                {
                    "items": [
                        {
                            "offering_id": OFFERING,
                            "offering_version_id": VERSION,
                            "offering_key": "consulta",
                            "display_name": "Consulta",
                            "active": True,
                            "bookable": True,
                        }
                    ],
                    "next_cursor": None,
                }
            ),
            ("GET", "/v1/onboarding/readiness"): _ok(
                {
                    "locations": {"status": "ready", "ready": True, "blockers": []},
                    "walk_in_queue": {
                        "status": "blocked",
                        "ready": False,
                        "blockers": [
                            {
                                "code": "service_queue_missing",
                                "resolution_hint": "Create an active service queue",
                            }
                        ],
                    },
                }
            ),
            ("GET", "/v1/appointments/slots"): _ok(
                [
                    {
                        "option_id": "o1",
                        "start_at": "2030-01-07T13:00:00+00:00",
                        "end_at": "2030-01-07T13:30:00+00:00",
                    }
                ]
            ),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(f"/tenants/{ORG}/setup?step=finish")
    assert "Primeros horarios libres para Consulta" in page.text
    assert "lunes 7 de enero, 09:00" in page.text  # 13:00 UTC in Santo Domingo
    assert "Opcional: agregue una fila de espera" in page.text
    assert "Create an active service queue" not in page.text  # owner jargon is translated
    assert f'href="/tenants/{ORG}/today">Ir a Hoy' in page.text
    (slots,) = runtime.sent("GET", "/v1/appointments/slots")
    assert slots["params"]["offering_version_id"] == VERSION


def _existing_service(amount: str | None) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/v1/catalog/offerings/configuration"): _ok(
            {
                "items": [
                    {
                        "offering_id": OFFERING,
                        "offering_version_id": VERSION,
                        "offering_key": "consulta-general",
                        "display_name": "Consulta general",
                        "active": True,
                        "bookable": True,
                        "duration_minutes": 30,
                    }
                ],
                "next_cursor": None,
            }
        ),
        ("GET", "/v1/catalog/offerings/consulta-general"): _ok(
            {"latest_version": {"id": VERSION, "amount": amount, "currency": "DOP"}}
        ),
        ("PUT", f"/v1/operations/offering-versions/{VERSION}/booking-terms"): _error(409),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price", "done"), [("1500", "service_exists"), ("2000", "service_price_kept")]
)
async def test_resubmitted_service_with_a_price_is_never_priced_twice(
    tmp_path: Path, price: str, done: str
) -> None:
    # Base terms are set once per version; a second configure is the owner's 409,
    # which must not be shown as someone else's concurrent change.
    runtime = _Upstream(_existing_service("1500.00"))
    form = {"display_name": "Consulta general", "duration_minutes": "30", "price": price}
    async with _signed_in(runtime, tmp_path) as client:
        response = await _submit(client, "services", form)
    assert response.status_code == 303, response.text
    assert response.headers["location"].endswith(f"step=services&done={done}")
    assert runtime.writes() == []


@pytest.mark.parametrize(
    ("amount", "currency", "label"),
    [
        ("1500.000000", "DOP", "RD$ 1,500.00"),
        ("0", "DOP", "RD$ 0.00"),
        ("20.5", "usd", "US$ 20.50"),
        ("1234567.891", "EUR", "1,234,567.89 EUR"),
        ("not-a-number", "DOP", ""),
    ],
)
def test_prices_read_as_the_front_desk_says_them(amount: str, currency: str, label: str) -> None:
    assert money_label(amount, currency) == label
