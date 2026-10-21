"""Configuration UI forwarding, scope binding and owner-read preconditions."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER = "22222222-2222-4222-8222-222222222222"
_ROOT = f"/tenants/{_TENANT}/configuration"
_READ = "communications_channel_policy_get"
_WRITE = "communications_configure_channel_policy"


def _document() -> dict[str, Any]:
    def entry(key: str, *, write: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operationId": key,
            "summary": key,
            "x-request-engine-capability": "test.canonical.only",
            "x-request-engine-kind": "command" if write else "query",
            "x-request-engine-idempotency": "required" if write else "none",
            "parameters": [
                {"name": "purpose", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
        }
        if write:
            result["parameters"].append(
                {"name": "X-RE-Organization-ID", "in": "header", "schema": {"type": "string"}}
            )
            result["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": [
                                "expected_revision",
                                "authority_party_id",
                                "organization_id",
                            ],
                            "properties": {
                                "expected_revision": {"type": "integer"},
                                "authority_party_id": {"type": "string"},
                                "organization_id": {"type": "string"},
                            },
                        }
                    }
                }
            }
        return result

    return {
        "paths": {
            "/canonical/channels/{purpose}": {
                "get": entry(_READ),
                "put": entry(_WRITE, write=True),
            },
            "/canonical/onboarding": {"get": {"operationId": "onboarding_read"}},
            "/canonical/resources": {
                "get": {
                    "operationId": "booking_resource_list",
                    "parameters": [
                        {"name": key, "in": "query", "schema": {"type": "string"}}
                        for key in ("authority_party_id", "limit", "after")
                    ],
                }
            },
            "/canonical/assignment": {
                "post": entry("booking_resource_assignment_create", write=True)
            },
        }
    }


class Port:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.failure: ControlResponse | None = None
        self.resources: list[dict[str, Any]] = []

    async def openapi(self) -> dict[str, Any]:
        return _document()

    async def aclose(self) -> None:
        pass

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "authenticated-owner"}, {})
        if self.failure:
            return self.failure
        if path == "/canonical/onboarding":
            return ControlResponse(
                200,
                {
                    "communications": {
                        "status": "blocked",
                        "ready": False,
                        "blockers": [
                            {
                                "code": "disabled",
                                "operation_id": _READ,
                                "resolution_hint": "Read the disabled purpose first",
                            }
                        ],
                    }
                },
                {},
            )
        if path == "/canonical/resources":
            return ControlResponse(
                200, {"items": self.resources, "next_cursor": "next-resource"}, {}
            )
        return ControlResponse(
            200,
            {"purpose": "appointment_reminder", "revision": 4, "configured": True, "enabled": True},
            {},
        )


def _client(tmp_path: Path, control: Port, runtime: Port) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        control_api_base_url="http://control:8001",
        runtime_api_base_url="http://runtime:8000",
        session_secret=SecretStr("test-session-secret-long-enough-40-characters"),
        cookie_secure=False,
        session_store_directory=tmp_path / "sessions",
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    )


async def _login(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
    ).status_code == 303


def _csrf(page: httpx.Response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match
    return match[1]


@pytest.mark.asyncio
async def test_readiness_and_canonical_read_fill_real_channel_revision(tmp_path: Path) -> None:
    control, runtime = Port(), Port()
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        page = await client.get(_ROOT)
        assert "Read the disabled purpose first" in page.text
        assert f"{_ROOT}/{_READ}" in page.text
        assert "include inactive items" in page.text
        form = await client.get(f"{_ROOT}/{_READ}?purpose=appointment_reminder")
        result = await client.post(
            f"{_ROOT}/{_READ}", data={"csrf_token": _csrf(form), "purpose": "appointment_reminder"}
        )
        assert "expected_revision=4" in result.text
        assert runtime.calls[-1][1] == "/canonical/channels/appointment_reminder"
        assert runtime.calls[-1][2]["extra_headers"] == {"X-RE-Organization-ID": _TENANT}
        assert len(control.calls) == 1


@pytest.mark.asyncio
async def test_form_and_header_cannot_override_selected_tenant_or_authenticated_actor(
    tmp_path: Path,
) -> None:
    control, runtime = Port(), Port()
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        form = await client.get(f"{_ROOT}/{_WRITE}?organization_id={_OTHER}")
        assert f'value="{_TENANT}"' in form.text
        values = {
            "csrf_token": _csrf(form),
            "purpose": "appointment_reminder",
            "expected_revision": "4",
            "authority_party_id": "represented-party",
            "organization_id": _OTHER,
            "X-RE-Organization-ID": _OTHER,
            "principal_id": "forged-principal",
            "_intent_id": "same-reviewed-change",
        }
        for _ in range(2):
            result = await client.post(
                f"{_ROOT}/{_WRITE}", data=values, headers={"X-RE-Organization-ID": _OTHER}
            )
            assert "Action completed" in result.text
        for method, path, kwargs in runtime.calls:
            assert method == "PUT" and path == "/canonical/channels/appointment_reminder"
            assert kwargs["bearer"] == "authenticated-owner"
            assert kwargs["json_body"] == {
                "expected_revision": 4,
                "authority_party_id": "represented-party",
                "organization_id": _TENANT,
            }
            assert kwargs["extra_headers"] == {
                "idempotency-key": "same-reviewed-change",
                "X-RE-Organization-ID": _TENANT,
            }


@pytest.mark.asyncio
async def test_empty_supply_page_does_not_invent_revision_and_cursor_preserves_filters(
    tmp_path: Path,
) -> None:
    control, runtime = Port(), Port()
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        url = f"{_ROOT}/booking_resource_list"
        form = await client.get(url)
        values = {
            "csrf_token": _csrf(form),
            "authority_party_id": "represented-party",
            "limit": "2",
            "after": "previous",
        }
        result = await client.post(url, data=values)
        assert "Continue from this owner read" not in result.text
        match = re.search(r'href="([^"]+)"[^>]*>Next page', result.text)
        assert match
        params = parse_qs(urlsplit(match[1].replace("&amp;", "&")).query)
        assert params == {
            "authority_party_id": ["represented-party"],
            "limit": ["2"],
            "after": ["next-resource"],
        }
        runtime.resources = [
            {"resource_id": "33333333-3333-4333-8333-333333333333", "availability_revision": 9}
        ]
        result = await client.post(url, data=values)
        assert "expected_resource_availability_revision=9" in result.text
        assert "authority_party_id=represented-party" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status", [("recent_authentication_required", 403), ("configuration_changed", 409)]
)
async def test_stale_or_step_up_keeps_original_intent_and_revision(
    tmp_path: Path, code: str, status: int
) -> None:
    control, runtime = Port(), Port()
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        form = await client.get(f"{_ROOT}/{_WRITE}")
        runtime.failure = ControlResponse(
            status, {"error": {"code": code, "message": "Reload current state"}}, {}
        )
        result = await client.post(
            f"{_ROOT}/{_WRITE}",
            data={
                "csrf_token": _csrf(form),
                "purpose": "appointment_reminder",
                "expected_revision": "4",
                "authority_party_id": "party",
                "organization_id": _OTHER,
                "_intent_id": "keep-original",
            },
        )
        assert code in result.text
        if status == 403:
            assert 'data-retry-form="tenant-configuration-operation"' in result.text
        assert len(runtime.calls) == 1
        assert runtime.calls[0][2]["json_body"]["expected_revision"] == 4
        assert runtime.calls[0][2]["extra_headers"]["idempotency-key"] == "keep-original"


@pytest.mark.asyncio
async def test_csrf_and_unregistered_operations_never_reach_runtime(tmp_path: Path) -> None:
    control, runtime = Port(), Port()
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        result = await client.post(f"{_ROOT}/{_WRITE}", data={"csrf_token": "wrong"})
        assert "csrf_failed" in result.text
        assert (await client.post(f"{_ROOT}/payments_refund")).status_code == 404
        assert not runtime.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [True, -1, "9", [9], None])
async def test_malformed_owner_revision_never_offers_actions(tmp_path: Path, revision: Any) -> None:
    control, runtime = Port(), Port()
    runtime.resources = [
        {"resource_id": "33333333-3333-4333-8333-333333333333", "availability_revision": revision}
    ]
    async with _client(tmp_path, control, runtime) as client:
        await _login(client)
        url = f"{_ROOT}/booking_resource_list"
        form = await client.get(url)
        result = await client.post(
            url, data={"csrf_token": _csrf(form), "authority_party_id": "represented-party"}
        )
        assert "Continue from this owner read" not in result.text
        assert "expected_resource_availability_revision=" not in result.text


class InventoryPort(Port):
    def __init__(self, payload: Any) -> None:
        super().__init__()
        self.payload = payload

    async def openapi(self) -> dict[str, Any]:
        document = _document()
        document["paths"]["/canonical/queues"] = {
            "get": {
                "operationId": "queue_service_queue_configuration_list",
                "parameters": [
                    {"name": key, "in": "query", "schema": {"type": "string"}}
                    for key in ("authority_party_id", "limit", "cursor")
                ],
            }
        }
        document["paths"]["/canonical/queues/{queue_id}"] = {
            "get": {
                "operationId": "queue_service_queue_configuration_read",
                "parameters": [
                    {
                        "name": "queue_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "authority_party_id",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
            }
        }
        return document

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/canonical/queues":
            self.calls.append((method, path, kwargs))
            return ControlResponse(200, self.payload, {})
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_inventory_read_links_preserve_party_tenant_and_cursor_without_a_write(
    tmp_path: Path,
) -> None:
    runtime = InventoryPort(
        {
            "items": [
                {
                    "queue_id": _OTHER,
                    "queue_key": "reception",
                    "display_name": "Inactive reception",
                    "location_id": _TENANT,
                    "offering_id": None,
                    "policy_key": "fifo",
                    "active": False,
                    "revision": 8,
                }
            ],
            "next_cursor": _OTHER,
        }
    )
    operation_id = "queue_service_queue_configuration_list"
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}/{operation_id}")
        response = await client.post(
            f"{_ROOT}/{operation_id}",
            data={
                "csrf_token": _csrf(page),
                "authority_party_id": _TENANT,
                "limit": "10",
            },
        )
        assert "Inactive reception" in response.text
        assert (
            f"queue_service_queue_configuration_read?queue_id={_OTHER}&amp;authority_party_id={_TENANT}"
            in response.text
        )
        assert f"cursor={_OTHER}" in response.text
        assert "limit=10" in response.text
        assert "Change configuration" not in response.text
        assert runtime.calls == [
            (
                "GET",
                "/canonical/queues",
                {
                    "bearer": "authenticated-owner",
                    "json_body": None,
                    "params": {"authority_party_id": _TENANT, "limit": "10"},
                    "extra_headers": {"X-RE-Organization-ID": _TENANT},
                },
            )
        ]


_INVALID_INVENTORIES: list[dict[str, Any]] = [
    {},
    {"items": [{}], "next_cursor": None},
    {"items": [], "next_cursor": True},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _INVALID_INVENTORIES)
async def test_incomplete_successful_inventory_response_fails_closed(
    tmp_path: Path, payload: Any
) -> None:
    runtime = InventoryPort(payload)
    operation_id = "queue_service_queue_configuration_list"
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}/{operation_id}")
        response = await client.post(
            f"{_ROOT}/{operation_id}",
            data={
                "csrf_token": _csrf(page),
                "authority_party_id": _TENANT,
            },
        )
        assert "invalid_owner_response" in response.text
        assert "502" in response.text
        assert "Action completed" not in response.text
        assert "Continue from this owner read" not in response.text
        assert "Next page" not in response.text
        assert len(runtime.calls) == 1


class ReadinessPort(Port):
    def __init__(self, payload: Any) -> None:
        super().__init__()
        self.readiness_payload = payload

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/canonical/onboarding":
            self.calls.append((method, path, kwargs))
            return ControlResponse(200, self.readiness_payload, {})
        return await super().request(method, path, **kwargs)


_INVALID_READINESS: list[dict[str, Any]] = [
    {},
    {"communications": {"ready": True, "blockers": []}},
    {"communications": {"status": "unknown", "ready": True, "blockers": []}},
    {"communications": {"status": ["ready"], "ready": True, "blockers": []}},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _INVALID_READINESS)
async def test_incomplete_readiness_is_visible_without_a_ready_status(
    tmp_path: Path, payload: Any
) -> None:
    async with _client(tmp_path, Port(), ReadinessPort(payload)) as client:
        await _login(client)
        page = await client.get(_ROOT)
        assert page.status_code == 200
        assert "Setup readiness is incomplete" in page.text
        assert "invalid_owner_response" in page.text
        assert '<span class="badge">ready</span>' not in page.text


@pytest.mark.asyncio
async def test_unknown_owner_readiness_is_displayed_as_unknown(tmp_path: Path) -> None:
    async with _client(
        tmp_path,
        Port(),
        ReadinessPort({"communications": {"status": "unknown", "ready": False, "blockers": []}}),
    ) as client:
        await _login(client)
        page = await client.get(_ROOT)
        # Unknown stays visibly unknown and is never shown as ready.
        assert '<span class="badge ">Not checked</span>' in page.text
        assert ">Ready</span>" not in page.text


@pytest.mark.asyncio
async def test_task_search_only_filters_presentation_and_keeps_selected_tenant(
    tmp_path: Path,
) -> None:
    runtime = Port()
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}?q=channel&organization_id={_OTHER}")
        assert f"{_ROOT}/{_READ}" in page.text
        assert f"{_ROOT}/{_WRITE}" in page.text
        assert f"{_ROOT}/booking_resource_list" not in page.text
        assert runtime.calls == [
            (
                "GET",
                "/canonical/onboarding",
                {
                    "bearer": "authenticated-owner",
                    "json_body": None,
                    "params": None,
                    "extra_headers": {"X-RE-Organization-ID": _TENANT},
                },
            )
        ]
        empty = await client.get(f"{_ROOT}?q=unmatched-configuration-task")
        assert "No configuration tasks match this search" in empty.text


class LocationPort(Port):
    def __init__(self) -> None:
        super().__init__()
        self.location: dict[str, Any] = {
            "location_id": _OTHER,
            "location_key": "office",
            "display_name": "Main office",
            "timezone": "America/Santo_Domingo",
            "active": False,
            "operational_revision": 7,
            "hours_windows": [],
            "public_contacts": [],
            **{
                key: None
                for key in (
                    "address_line1",
                    "address_line2",
                    "locality",
                    "administrative_area",
                    "postal_code",
                    "country_code",
                    "latitude",
                    "longitude",
                    "geocoding_source",
                    "geocoded_at",
                )
            },
        }
        self.invalid_inventory = False
        self.inventory_items: list[dict[str, Any]] | None = None

    async def openapi(self) -> dict[str, Any]:
        parameters = [
            {
                "name": "authority_party_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
            },
        ]
        return {
            "paths": {
                "/locations": {
                    "get": {
                        "operationId": "catalog_location_configuration_list",
                        "parameters": parameters,
                    }
                },
                "/locations/{location_id}": {
                    "get": {
                        "operationId": "catalog_location_configuration_read",
                        "parameters": parameters
                        + [
                            {
                                "name": "location_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                    },
                    "put": {
                        "operationId": "catalog_location_update",
                        "parameters": [
                            {
                                "name": "location_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": [
                                            "authority_party_id",
                                            "expected_operational_revision",
                                            "timezone",
                                            "active",
                                        ],
                                        "properties": {
                                            "authority_party_id": {"type": "string"},
                                            "expected_operational_revision": {"type": "integer"},
                                            "timezone": {"type": "string"},
                                            "active": {"type": "boolean"},
                                        },
                                    }
                                }
                            }
                        },
                    },
                },
            }
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/locations":
            body = (
                {}
                if self.invalid_inventory
                else {
                    "items": self.inventory_items
                    if self.inventory_items is not None
                    else [self.location],
                    "next_cursor": None,
                }
            )
            return ControlResponse(200, body, {})
        return ControlResponse(200, self.location, {})


@pytest.mark.asyncio
async def test_location_selector_loads_current_revision_without_a_command(tmp_path: Path) -> None:
    runtime = LocationPort()
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        start = await client.get(f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}")
        assert '<select name="location_id"' in start.text
        assert "Main office (inactive)" in start.text
        assert "Load current settings" in start.text
        assert 'name="expected_operational_revision"' not in start.text
        loaded = await client.get(
            f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}"
            f"&location_id={_OTHER}&expected_operational_revision=900&active=true"
        )
        assert 'type="hidden" name="expected_operational_revision" value="7"' in loaded.text
        assert 'name="active" value="true" checked' not in loaded.text
        assert 'name="timezone" value="America/Santo_Domingo"' in loaded.text
        assert all(method == "GET" for method, _, _ in runtime.calls)
        assert all(
            kwargs["extra_headers"]["X-RE-Organization-ID"] == _TENANT
            for _, _, kwargs in runtime.calls
        )


@pytest.mark.asyncio
async def test_failed_inventory_does_not_offer_an_unverified_location(tmp_path: Path) -> None:
    runtime = LocationPort()
    runtime.invalid_inventory = True
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}&location_id={_OTHER}"
        )
        assert "Current choices could not be verified" in page.text
        assert 'data-confirm="Apply' not in page.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


@pytest.mark.asyncio
async def test_guided_steps_preserve_explicit_party_without_assuming_readiness(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path, Port(), Port()) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}?authority_party_id={_OTHER}")
        # The party-identifier card is gone: setup is the guided flow, and advanced
        # tasks keep the explicitly supplied Party without asking anyone to type it.
        assert "Set up your clinic" in page.text
        assert f'href="/tenants/{_TENANT}/setup"' in page.text
        assert "Represented business party" not in page.text
        assert "Advanced settings" in page.text
        assert f"booking_resource_list?authority_party_id={_OTHER}" in page.text
        assert "blocked" in page.text


@pytest.mark.asyncio
async def test_selected_location_outside_first_page_is_verified_by_detail(tmp_path: Path) -> None:
    runtime = LocationPort()
    runtime.inventory_items = []
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}&location_id={_OTHER}"
        )
        assert 'type="hidden" name="expected_operational_revision" value="7"' in page.text
        assert "could not be verified" not in page.text
        assert any(path == f"/locations/{_OTHER}" for _, path, _ in runtime.calls)
        assert all(method == "GET" for method, _, _ in runtime.calls)


@pytest.mark.asyncio
async def test_detail_of_different_location_never_unlocks_an_edit(tmp_path: Path) -> None:
    runtime = LocationPort()
    runtime.inventory_items = []
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}&location_id={_TENANT}"
        )
        assert "previous selection could not be verified" in page.text
        assert 'data-confirm="Apply' not in page.text
        assert 'name="expected_operational_revision"' not in page.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


class DefinitionPort(Port):
    async def openapi(self) -> dict[str, Any]:
        return {
            "paths": {
                "/definitions": {"get": {"operationId": "request_definitions_list"}},
                "/definitions/{definition_id}": {
                    "get": {
                        "operationId": "request_definition_read",
                        "parameters": [
                            {
                                "name": "definition_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                    },
                    "put": {
                        "operationId": "request_definition_set_active",
                        "parameters": [
                            {
                                "name": "definition_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["expected_revision", "active"],
                                        "properties": {
                                            "expected_revision": {"type": "integer"},
                                            "active": {"type": "boolean"},
                                        },
                                    }
                                }
                            }
                        },
                    },
                },
            }
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        row: dict[str, Any] = {
            "definition_id": _OTHER,
            "request_key": "appointment",
            "display_name": "Book appointment",
            "active": False,
            "revision": 12,
            "version_id": _TENANT,
            "version": 1,
            "input_schema": {},
            "result_schema": None,
        }
        return ControlResponse(
            200, {"items": [row], "next_cursor": None} if path == "/definitions" else row, {}
        )


@pytest.mark.asyncio
async def test_definition_picker_and_revision_need_no_manual_reference(tmp_path: Path) -> None:
    runtime = DefinitionPort()
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        chooser = await client.get(f"{_ROOT}/request_definition_set_active")
        assert '<select name="definition_id"' in chooser.text
        assert "Book appointment (inactive)" in chooser.text
        assert 'name="expected_revision"' not in chooser.text
        current = await client.get(
            f"{_ROOT}/request_definition_set_active?definition_id={_OTHER}&expected_revision=900"
        )
        assert 'type="hidden" name="expected_revision" value="12"' in current.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


@pytest.mark.asyncio
async def test_loaded_edit_keeps_identity_bound_to_its_current_settings(tmp_path: Path) -> None:
    runtime = LocationPort()
    runtime.location["operational_revision"] = 1
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        loaded = await client.get(
            f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}&location_id={_OTHER}"
        )
        assert '<select name="location_id"' not in loaded.text
        assert f'type="hidden" name="location_id" value="{_OTHER}"' in loaded.text
        assert 'type="hidden" name="expected_operational_revision" value="1"' in loaded.text
        assert "Choose a different item and load its current settings" in loaded.text
        chooser = await client.get(f"{_ROOT}/catalog_location_update?authority_party_id={_TENANT}")
        assert '<select name="location_id"' in chooser.text
        assert 'name="expected_operational_revision"' not in chooser.text
        setup = await client.get(f"{_ROOT}/setup?authority_party_id={_TENANT}")
        assert setup.status_code == 200
        assert "Set up your clinic" in setup.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


class HoursPort(LocationPort):
    async def openapi(self) -> dict[str, Any]:
        document = await super().openapi()
        source = document["paths"]["/locations/{location_id}"]["put"]
        hours = {**source, "operationId": "catalog_location_hours_replace"}
        hours["requestBody"] = {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": [
                            "authority_party_id",
                            "expected_operational_revision",
                            "windows",
                        ],
                        "properties": {
                            "authority_party_id": {"type": "string"},
                            "expected_operational_revision": {"type": "integer"},
                            "windows": {"type": "array", "items": {"type": "object"}},
                        },
                    }
                }
            }
        }
        document["paths"]["/locations/{location_id}/hours"] = {"put": hours}
        return document


@pytest.mark.asyncio
async def test_schedule_replacement_never_clears_hours_without_explicit_confirmation(
    tmp_path: Path,
) -> None:
    runtime = HoursPort()
    path = f"{_ROOT}/catalog_location_hours_replace"
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(f"{path}?authority_party_id={_TENANT}&location_id={_OTHER}")
        assert "Current opening hours and their revision were loaded" in page.text
        assert "Current settings were loaded automatically" not in page.text
        assert 'name="_confirm_replacement" value="true" required' in page.text
        outcome = await client.post(
            path,
            data={
                "csrf_token": _csrf(page),
                "authority_party_id": _TENANT,
                "location_id": _OTHER,
                "expected_operational_revision": "7",
                "windows": "[]",
            },
        )
        assert "Confirm that this complete schedule replaces" in outcome.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


@pytest.mark.asyncio
async def test_schedule_editor_prefills_the_actual_complete_owner_schedule(tmp_path: Path) -> None:
    runtime = HoursPort()
    runtime.location["hours_windows"] = [
        {
            "weekday": 0,
            "local_start": "09:00:00",
            "local_end": "17:00:00",
            "valid_from": "2026-10-01",
            "valid_until": None,
        }
    ]
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/catalog_location_hours_replace?authority_party_id={_TENANT}&location_id={_OTHER}"
        )
        row = re.search(
            r'<textarea name="windows\[0\]"[^>]*>(.*?)</textarea>', page.text, re.DOTALL
        )
        assert row is not None
        assert json.loads(html.unescape(row.group(1))) == runtime.location["hours_windows"][0]
        assert 'name="windows[1]"' not in page.text
        assert 'type="hidden" name="expected_operational_revision" value="7"' in page.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


_INVALID_LOCATION_CHILDREN: list[tuple[str, Any]] = [
    ("hours_windows", None),
    ("public_contacts", None),
    ("hours_windows", [{"weekday": True}]),
    ("public_contacts", [{"channel": {}, "value": "a", "label": None}]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,invalid", _INVALID_LOCATION_CHILDREN)
async def test_partial_child_snapshots_never_become_empty_replacement(
    tmp_path: Path, field: str, invalid: Any
) -> None:
    runtime = HoursPort()
    runtime.location[field] = invalid
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/catalog_location_hours_replace?authority_party_id={_TENANT}&location_id={_OTHER}"
        )
        assert "current configuration could not be verified" in page.text
        assert 'data-confirm="Apply' not in page.text
        assert all(method == "GET" for method, _, _ in runtime.calls)


@pytest.mark.asyncio
async def test_url_revision_without_an_owner_read_is_not_claimed_as_loaded(tmp_path: Path) -> None:
    runtime = Port()
    async with _client(tmp_path, Port(), runtime) as client:
        await _login(client)
        page = await client.get(
            f"{_ROOT}/{_WRITE}?purpose=appointment_reminder&expected_revision=900"
        )
    assert page.status_code == 200
    assert 'type="number" step="1" name="expected_revision" value="900"' in page.text
    assert "Current version loaded" not in page.text
    assert 'type="hidden" name="expected_revision"' not in page.text
    assert runtime.calls == []
