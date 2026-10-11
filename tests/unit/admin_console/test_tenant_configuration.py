"""Configuration UI forwarding, scope binding and owner-read preconditions."""

from __future__ import annotations

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
        assert '<span class="badge">unknown</span>' in page.text
        assert '<span class="badge">ready</span>' not in page.text


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
