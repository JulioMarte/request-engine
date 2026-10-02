"""Unit tests for the task-oriented resource workspaces and shared executor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.inputs import build_inputs, summarize_payload
from request_engine.entrypoints.http.admin_console.resources import (
    MissingOperation,
    pagination_params,
    payload_path,
    prefill_values,
    resolve_operation,
)
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _param(name: str, location: str, required: bool = False) -> dict[str, Any]:
    return {"name": name, "in": location, "required": required, "schema": {"type": "string"}}


def _obj(required: list[str], props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "required": required, "properties": props}


def _op(
    operation_id: str,
    *,
    capability: str,
    kind: str,
    idempotency: str,
    owner: str = "tenancy",
    params: list[dict[str, Any]] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "operationId": operation_id,
        "summary": operation_id,
        "tags": [owner],
        "x-request-engine-capability": capability,
        "x-request-engine-kind": kind,
        "x-request-engine-idempotency": idempotency,
        "x-request-engine-exposure": "operator",
        "x-request-engine-owner": owner,
    }
    if params is not None:
        entry["parameters"] = params
    if body is not None:
        entry["requestBody"] = {"content": {"application/json": {"schema": body}}}
    return entry


def _openapi() -> dict[str, Any]:
    revision_body = _obj(
        ["expected_revision"],
        {"expected_revision": {"type": "integer"}, "reason_code": {"type": "string"}},
    )
    return {
        "components": {"schemas": {}},
        "paths": {
            "/v1/platform/native-identities": {
                "get": _op(
                    "platform_native_identity_list",
                    capability="platform.identity.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("after", "query"), _param("limit", "query")],
                ),
                "post": _op(
                    "platform_native_identity_provision",
                    capability="platform.identity.provision",
                    kind="command",
                    idempotency="required",
                    body=_obj(
                        ["login_handle", "password"],
                        {"login_handle": {"type": "string"}, "password": {"type": "string"}},
                    ),
                ),
            },
            "/v1/platform/native-identities/{native_identity_id}": {
                "get": _op(
                    "platform_native_identity_get",
                    capability="platform.identity.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("native_identity_id", "path", True)],
                )
            },
            "/v1/platform/native-identities/{native_identity_id}:disable": {
                "post": _op(
                    "platform_native_identity_disable",
                    capability="platform.identity.disable",
                    kind="command",
                    idempotency="required",
                    params=[_param("native_identity_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/provisioners": {
                "get": _op(
                    "platform_native_provisioner_list",
                    capability="platform.provisioner.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("after", "query"), _param("limit", "query")],
                ),
                "post": _op(
                    "platform_native_provisioner_create",
                    capability="platform.tenant_provisioner.provision",
                    kind="command",
                    idempotency="required",
                    body=_obj(
                        ["native_identity_id"],
                        {"native_identity_id": {"type": "string"}},
                    ),
                ),
            },
            "/v1/platform/provisioners/{principal_id}": {
                "get": _op(
                    "platform_native_provisioner_get",
                    capability="platform.provisioner.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("principal_id", "path", True)],
                )
            },
            "/v1/platform/provisioners/{principal_id}:suspend": {
                "post": _op(
                    "platform_native_provisioner_suspend",
                    capability="platform.provisioner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/provisioners/{principal_id}:reactivate": {
                "post": _op(
                    "platform_native_provisioner_reactivate",
                    capability="platform.provisioner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/provisioners/{principal_id}:revoke": {
                "post": _op(
                    "platform_native_provisioner_revoke",
                    capability="platform.provisioner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/configurations": {
                "get": _op(
                    "platform_configuration_list",
                    capability="platform.configuration.read",
                    kind="query",
                    idempotency="none",
                    owner="platform_configuration",
                )
            },
            "/v1/platform/recovery-policy": {
                "get": _op(
                    "platform_recovery_policy_get",
                    capability="platform.configuration.read",
                    kind="query",
                    idempotency="none",
                    owner="platform_configuration",
                )
            },
            "/v1/platform/owner-invitations": {
                "post": _op(
                    "platform_owner_invitation_create",
                    capability="platform.owner.provision",
                    kind="command",
                    idempotency="required",
                    body=_obj(
                        ["provenance_reference"], {"provenance_reference": {"type": "string"}}
                    ),
                )
            },
            "/v1/platform/owner-invitations/{invitation_id}:revoke": {
                "post": _op(
                    "platform_owner_invitation_revoke",
                    capability="platform.owner.provision",
                    kind="command",
                    idempotency="required",
                    params=[_param("invitation_id", "path", True)],
                    body=_obj(["reason_code"], {"reason_code": {"type": "string"}}),
                )
            },
            "/v1/platform/owner-invitations/{invitation_id}:activate": {
                "post": _op(
                    "platform_owner_invitation_activate",
                    capability="platform.owner.provision",
                    kind="command",
                    idempotency="required",
                    params=[_param("invitation_id", "path", True)],
                )
            },
            "/v1/platform/owners/{principal_id}:suspend": {
                "post": _op(
                    "platform_owner_suspend",
                    capability="platform.owner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/owners/{principal_id}:reactivate": {
                "post": _op(
                    "platform_owner_reactivate",
                    capability="platform.owner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/owners/{principal_id}:revoke": {
                "post": _op(
                    "platform_owner_revoke",
                    capability="platform.owner.manage_lifecycle",
                    kind="command",
                    idempotency="required",
                    params=[_param("principal_id", "path", True)],
                    body=revision_body,
                )
            },
            "/v1/platform/organizations": {
                "get": _op(
                    "platform_organization_list",
                    capability="platform.organization.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("after", "query"), _param("limit", "query")],
                ),
                "post": _op(
                    "platform_native_organization_create",
                    capability="organization.provision",
                    kind="command",
                    idempotency="required",
                    body=_obj(["organization_key"], {"organization_key": {"type": "string"}}),
                ),
            },
            "/v1/platform/organizations/{organization_id}": {
                "get": _op(
                    "platform_organization_get",
                    capability="platform.organization.read",
                    kind="query",
                    idempotency="none",
                    params=[_param("organization_id", "path", True)],
                )
            },
            "/v1/platform/recovery-operators": {
                "post": _op(
                    "platform_native_recovery_operator_create",
                    capability="platform.recovery_operator.provision",
                    kind="command",
                    idempotency="required",
                    body=_obj(["native_identity_id"], {"native_identity_id": {"type": "string"}}),
                )
            },
            "/v1/platform/secrets": {
                "post": _op(
                    "platform_secret_create",
                    capability="platform.secret.write",
                    kind="command",
                    idempotency="required",
                    owner="platform_configuration",
                    body=_obj(
                        ["purpose", "value"],
                        {"purpose": {"type": "string"}, "value": {"type": "string"}},
                    ),
                )
            },
            "/v1/platform/signing-keyrings/appointment-option": {
                "post": _op(
                    "platform_appointment_signing_keyring_create",
                    capability="platform.secret.write",
                    kind="command",
                    idempotency="required",
                    owner="platform_configuration",
                    body=_obj(["key_id"], {"key_id": {"type": "string"}}),
                )
            },
        },
    }


_NATIVE_ID = "11111111-1111-1111-1111-111111111111"
_PRINCIPAL_ID = "22222222-2222-2222-2222-222222222222"
_PRINCIPAL_ITEM = {
    "principal_id": _PRINCIPAL_ID,
    "principal_kind": "provisioner",
    "active": True,
    "authority_revision": 7,
    "binding_status": "active",
}
_ORGANIZATION_ID = "33333333-3333-3333-3333-333333333333"
_ORGANIZATION_ITEM = {
    "organization_id": _ORGANIZATION_ID,
    "organization_key": "acme",
    "display_name": "Acme Clinic",
    "operational_status": "active",
    "default_timezone": "America/Santo_Domingo",
}


class FakeControl:
    def __init__(self, *, suspend: ControlResponse | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.suspend = suspend

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        setup_bearer: str | None = None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse:
        self.calls.append(
            (
                method,
                path,
                {
                    "json": json_body,
                    "params": params,
                    "headers": extra_headers,
                    "bearer": bearer,
                },
            )
        )
        if method == "POST" and path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "test-token"}, {})
        if method == "GET" and path == "/v1/platform/native-identities":
            return ControlResponse(
                200,
                {
                    "items": [
                        {
                            "native_identity_id": _NATIVE_ID,
                            "status": "active",
                            "revision": 3,
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "next_cursor": None,
                },
                {},
            )
        if method == "GET" and path == f"/v1/platform/native-identities/{_NATIVE_ID}":
            return ControlResponse(
                200,
                {
                    "native_identity_id": _NATIVE_ID,
                    "status": "active",
                    "revision": 3,
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {},
            )
        if method == "GET" and path == "/v1/platform/provisioners":
            return ControlResponse(200, {"items": [_PRINCIPAL_ITEM], "next_after": None}, {})
        if method == "GET" and path == f"/v1/platform/provisioners/{_PRINCIPAL_ID}":
            return ControlResponse(200, _PRINCIPAL_ITEM, {})
        if method == "POST" and path == f"/v1/platform/provisioners/{_PRINCIPAL_ID}:suspend":
            if self.suspend is not None:
                return self.suspend
            return ControlResponse(
                200,
                {
                    "fact_id": "fact",
                    "principal_id": _PRINCIPAL_ID,
                    "action": "suspend",
                    "authority_revision": 8,
                    "binding_status": "suspended",
                },
                {},
            )
        if method == "POST" and path == "/v1/platform/organizations":
            return ControlResponse(
                201,
                {
                    "organization_id": _ORGANIZATION_ID,
                    "organization_party_id": "44444444-4444-4444-4444-444444444444",
                },
                {},
            )
        if method == "GET" and path == "/v1/platform/organizations":
            return ControlResponse(200, {"items": [_ORGANIZATION_ITEM], "next_after": None}, {})
        if method == "GET" and path == f"/v1/platform/organizations/{_ORGANIZATION_ID}":
            return ControlResponse(200, _ORGANIZATION_ITEM, {})
        if method == "GET" and path == "/v1/platform/configurations":
            return ControlResponse(
                200,
                {
                    "items": [
                        {"configuration_kind": "email.delivery", "revision": 1, "state": "active"},
                        {"configuration_kind": "email.delivery", "revision": 2, "state": "draft"},
                    ]
                },
                {},
            )
        if method == "GET" and path == "/v1/platform/recovery-policy":
            return ControlResponse(
                200,
                {
                    "source": "default",
                    "preset_name": "p",
                    "active_revision": 1,
                    "provider_kind": "x",
                    "configuration": {},
                },
                {},
            )
        return ControlResponse(404, {"error": {"code": "not_found", "message": "unknown"}}, {})

    async def openapi(self) -> dict[str, Any]:
        return _openapi()

    async def aclose(self) -> None:
        return None


def _settings() -> AdminConsoleSettings:
    return AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control:8001",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
        follow_redirects=False,
    )


async def _login(client: httpx.AsyncClient) -> None:
    response = await client.post("/login", data={"login_handle": "owner", "password": "pw"})
    assert response.status_code == 303


def test_missing_operation_raises() -> None:
    catalog = load_catalog(_openapi())
    with pytest.raises(MissingOperation):
        resolve_operation(catalog, "platform_does_not_exist")


def test_pagination_params_only_forwards_declared() -> None:
    catalog = load_catalog(_openapi())
    operation = resolve_operation(catalog, "platform_native_provisioner_list")
    assert operation is not None
    params = pagination_params(operation, {"after": "abc", "limit": "10", "unrelated": "x"})
    assert params == {"after": "abc", "limit": "10"}


def test_payload_path_and_prefill() -> None:
    item = {"authority_revision": 7, "nested": {"deep": "v"}}
    assert payload_path(item, "authority_revision") == "7"
    assert payload_path(item, "nested.deep") == "v"
    assert payload_path(item, "absent") == ""
    assert prefill_values(item, (("expected_revision", "authority_revision"),)) == {
        "expected_revision": "7"
    }


def test_build_inputs_marks_secrets_and_prefills() -> None:
    catalog = load_catalog(_openapi())
    operation = resolve_operation(catalog, "platform_native_identity_disable")
    assert operation is not None
    inputs = build_inputs(operation, values={"expected_revision": "3"})
    by_name = {item["name"]: item for item in inputs}
    assert by_name["expected_revision"]["value"] == "3"
    assert by_name["native_identity_id"]["location"] == "path"
    provision = resolve_operation(catalog, "platform_native_identity_provision")
    assert provision is not None
    provision_inputs = build_inputs(provision, secret_fields=("password",))
    assert {item["name"]: item["secret"] for item in provision_inputs}["password"] is True


def test_summarize_payload_buckets_scalars_and_nested() -> None:
    scalars, nested = summarize_payload(
        {"status": "active", "active": True, "missing": None, "tags": ["a", "b"], "meta": {"k": 1}}
    )
    rendered = dict(scalars)
    assert rendered["status"] == "active"
    assert rendered["active"] == "yes"
    assert rendered["tags"] == "a, b"
    assert [key for key, _ in nested] == ["meta"]


@pytest.mark.asyncio
async def test_resources_index_lists_workspaces() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources")
    assert response.status_code == 200
    assert "Native identities" in response.text
    assert "Platform owners" in response.text
    assert "Deployment recovery" in response.text


@pytest.mark.asyncio
async def test_native_identity_list_detail_and_prefill() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        listing = await client.get("/resources/native-identities")
        assert listing.status_code == 200
        assert _NATIVE_ID in listing.text
        detail = await client.get(f"/resources/native-identities/{_NATIVE_ID}")
        assert detail.status_code == 200
        assert 'name="native_identity_id" value="' + _NATIVE_ID + '"' in detail.text
        assert 'name="expected_revision" value="3"' in detail.text


@pytest.mark.asyncio
async def test_detail_hides_actions_when_authoritative_read_fails() -> None:
    class FailedDetail(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "GET" and path == f"/v1/platform/native-identities/{_NATIVE_ID}":
                return ControlResponse(404, {"error": {"code": "not_found", "message": "gone"}}, {})
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=FailedDetail())
    async with _client(app) as client:
        await _login(client)
        response = await client.get(f"/resources/native-identities/{_NATIVE_ID}")
    assert response.status_code == 200
    assert "Item unavailable" in response.text
    assert 'id="action-disable"' not in response.text


@pytest.mark.asyncio
async def test_list_error_is_not_rendered_as_a_genuine_empty_collection() -> None:
    class FailedList(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "GET" and path == "/v1/platform/native-identities":
                return ControlResponse(
                    503, {"error": {"code": "unavailable", "message": "later"}}, {}
                )
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=FailedList())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources/native-identities")
    assert "Could not load native identities" in response.text
    assert "No native identities yet" not in response.text


@pytest.mark.asyncio
async def test_resource_action_runs_owner_operation_with_idempotency() -> None:
    control = FakeControl()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        await _login(client)
        detail = await client.get(f"/resources/provisioners/{_PRINCIPAL_ID}")
        match = _CSRF_RE.search(detail.text)
        assert match is not None
        executed = await client.post(
            f"/resources/provisioners/{_PRINCIPAL_ID}/actions/suspend",
            data={
                "csrf_token": match.group(1),
                "principal_id": _PRINCIPAL_ID,
                "expected_revision": "7",
                "reason_code": "security_investigation",
            },
        )
    assert executed.status_code == 200
    assert "suspended" in executed.text
    target = (
        "POST",
        f"/v1/platform/provisioners/{_PRINCIPAL_ID}:suspend",
    )
    call = next(item for item in control.calls if (item[0], item[1]) == target)
    assert call[2]["headers"]["idempotency-key"]
    assert call[2]["json"]["expected_revision"] == 7
    assert call[2]["bearer"] == "test-token"


@pytest.mark.asyncio
async def test_repeated_form_intent_reuses_the_same_idempotency_key() -> None:
    control = FakeControl()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        await _login(client)
        detail = await client.get(f"/resources/provisioners/{_PRINCIPAL_ID}")
        match = _CSRF_RE.search(detail.text)
        assert match is not None
        form = {
            "csrf_token": match.group(1),
            "_intent_id": "same-browser-intent",
            "principal_id": _PRINCIPAL_ID,
            "expected_revision": "7",
            "reason_code": "security_investigation",
        }
        first = await client.post(
            f"/resources/provisioners/{_PRINCIPAL_ID}/actions/suspend", data=form
        )
        second = await client.post(
            f"/resources/provisioners/{_PRINCIPAL_ID}/actions/suspend", data=form
        )
    assert first.status_code == second.status_code == 200
    calls = [
        item
        for item in control.calls
        if item[0] == "POST" and item[1] == f"/v1/platform/provisioners/{_PRINCIPAL_ID}:suspend"
    ]
    assert [item[2]["headers"]["idempotency-key"] for item in calls] == [
        "same-browser-intent",
        "same-browser-intent",
    ]


@pytest.mark.asyncio
async def test_resource_action_rejects_bad_csrf() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        denied = await client.post(
            f"/resources/provisioners/{_PRINCIPAL_ID}/actions/suspend",
            data={"csrf_token": "wrong", "principal_id": _PRINCIPAL_ID, "expected_revision": "7"},
        )
    assert denied.status_code == 200
    assert "csrf_failed" in denied.text


@pytest.mark.asyncio
async def test_step_up_result_retries_the_same_form() -> None:
    step_up = ControlResponse(
        403,
        {"error": {"code": "phishing_resistant_auth_required", "message": "step up"}},
        {},
    )
    app = create_admin_console_app(_settings(), client=FakeControl(suspend=step_up))
    async with _client(app) as client:
        await _login(client)
        detail = await client.get(f"/resources/provisioners/{_PRINCIPAL_ID}")
        match = _CSRF_RE.search(detail.text)
        assert match is not None
        executed = await client.post(
            f"/resources/provisioners/{_PRINCIPAL_ID}/actions/suspend",
            data={
                "csrf_token": match.group(1),
                "principal_id": _PRINCIPAL_ID,
                "expected_revision": "7",
                "reason_code": "security_investigation",
            },
        )
    assert executed.status_code == 200
    assert 'data-retry-form="action-suspend"' in executed.text
    assert "Confirm with passkey" in executed.text
    assert "Your entries will be preserved" in executed.text
    assert "Technical details" in executed.text


@pytest.mark.asyncio
async def test_secrets_workspace_states_it_cannot_list() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources/secrets")
    assert response.status_code == 200
    assert "no secret-enumeration operation" in response.text
    assert "Create secret" in response.text


@pytest.mark.asyncio
async def test_owners_workspace_states_it_cannot_list() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources/owners")
    assert response.status_code == 200
    assert "no owner enumeration operation" in response.text


@pytest.mark.asyncio
async def test_organizations_workspace_uses_platform_create_operation() -> None:
    control = FakeControl()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        await _login(client)
        page = await client.get("/resources/organizations")
        assert page.status_code == 200
        assert "Acme Clinic" in page.text
        detail = await client.get(f"/resources/organizations/{_ORGANIZATION_ID}")
        assert detail.status_code == 200
        assert "America/Santo_Domingo" in detail.text
        match = _CSRF_RE.search(page.text)
        assert match is not None
        created = await client.post(
            "/resources/organizations",
            data={
                "csrf_token": match.group(1),
                "_intent_id": "create-organization-acme",
                "organization_key": "acme",
            },
        )
    assert created.status_code == 200
    assert "completed successfully" in created.text
    call = next(
        item
        for item in control.calls
        if item[0] == "POST" and item[1] == "/v1/platform/organizations"
    )
    assert call[2]["json"] == {"organization_key": "acme"}
    assert call[2]["headers"]["idempotency-key"] == "create-organization-acme"
    assert call[2]["bearer"] == "test-token"


@pytest.mark.asyncio
async def test_configurations_workspace_groups_kinds() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources/configurations")
    assert response.status_code == 200
    assert "email.delivery" in response.text


@pytest.mark.asyncio
async def test_resources_require_a_session() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        assert (await client.get("/resources")).status_code == 303
        assert (await client.get("/resources/native-identities")).status_code == 303
