"""Unit tests for the task-oriented resource workspaces and shared executor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import UUID

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
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.modules.platform_configuration.api.deployment_http import DeploymentBindingBody

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
    # The generic operations form passes no workspace secret list; a credential
    # must still never render as visible text there.
    generic = {item["name"]: item["secret"] for item in build_inputs(provision)}
    assert generic == {"login_handle": False, "password": True}


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
async def test_owners_workspace_without_canonical_read_fails_closed() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await _login(client)
        response = await client.get("/resources/owners")
    assert response.status_code == 503
    assert "Owner information is temporarily unavailable" in response.text
    assert "No owner information or action forms are shown" in response.text


@pytest.mark.asyncio
async def test_organizations_workspace_uses_platform_create_operation() -> None:
    control = FakeControl()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        await _login(client)
        page = await client.get("/resources/organizations")
        assert page.status_code == 200
        assert "Acme Clinic" in page.text
        assert 'href="/resources/business-setup"' in page.text
        detail = await client.get(f"/resources/organizations/{_ORGANIZATION_ID}")
        assert detail.status_code == 200
        assert "America/Santo_Domingo" in detail.text
        setup_page = await client.get("/resources/business-setup")
        match = _CSRF_RE.search(setup_page.text)
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


class ReadPayloadControl(FakeControl):
    def __init__(self, path: str, payload: Any, *, status: int = 200) -> None:
        super().__init__()
        self.read_path, self.read_payload, self.read_status = path, payload, status

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if method == "GET" and path == self.read_path:
            self.calls.append((method, path, kwargs))
            return ControlResponse(self.read_status, self.read_payload, {})
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"native_identity_id": _NATIVE_ID},
        {"native_identity_id": _NATIVE_ID, "revision": True, "status": "active"},
        {"native_identity_id": _PRINCIPAL_ID, "revision": 3, "status": "active"},
    ],
)
async def test_partial_identity_read_never_offers_disable(payload: Any) -> None:
    control = ReadPayloadControl(f"/v1/platform/native-identities/{_NATIVE_ID}", payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get(f"/resources/native-identities/{_NATIVE_ID}")
    assert "invalid_owner_response" in page.text
    assert 'id="action-disable"' not in page.text
    assert len([call for call in control.calls if call[0] == "POST"]) == 1  # login only


_PARTIAL_IDENTITY_PAGES: list[Any] = [
    {},
    {"items": []},
    {"items": [{}], "next_cursor": None},
    {"items": [], "next_cursor": True},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _PARTIAL_IDENTITY_PAGES)
async def test_partial_identity_page_is_not_a_genuine_empty_collection(payload: Any) -> None:
    control = ReadPayloadControl("/v1/platform/native-identities", payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/native-identities")
    assert "invalid_owner_response" in page.text
    assert "No native identities yet" not in page.text


@pytest.mark.asyncio
async def test_valid_empty_identity_page_remains_empty_without_transport_error() -> None:
    control = ReadPayloadControl(
        "/v1/platform/native-identities", {"items": [], "next_cursor": None}
    )
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/native-identities")
    assert "No native identities yet" in page.text
    assert "invalid_owner_response" not in page.text


class ExtendedReadControl(ReadPayloadControl):
    async def openapi(self) -> dict[str, Any]:
        document = _openapi()
        for path, key, params, method in (
            (
                "/v1/platform/configurations/{configuration_kind}",
                "platform_configuration_revision_list",
                [_param("configuration_kind", "path", True)],
                "get",
            ),
            (
                "/v1/platform/configurations/{configuration_kind}/{revision}",
                "platform_configuration_revision_get",
                [_param("configuration_kind", "path", True), _param("revision", "path", True)],
                "get",
            ),
            ("/v1/platform/configurations:stage", "platform_configuration_stage", [], "post"),
            ("/v1/platform/configurations:validate", "platform_configuration_validate", [], "post"),
            ("/v1/platform/configurations:activate", "platform_configuration_activate", [], "post"),
            ("/v1/platform/configurations:disable", "platform_configuration_disable", [], "post"),
            ("/v1/platform/providers:test", "platform_provider_test", [], "post"),
            (
                "/v1/platform/secrets/{binding_id}",
                "platform_secret_metadata_get",
                [_param("binding_id", "path", True)],
                "get",
            ),
            ("/v1/platform/secrets:rotate", "platform_secret_rotate", [], "post"),
            ("/v1/platform/secrets:revoke", "platform_secret_revoke", [], "post"),
            (
                "/v1/platform/keyrings:rotate",
                "platform_appointment_signing_keyring_rotate",
                [],
                "post",
            ),
            (
                "/v1/platform/deployment-recovery:plan",
                "platform_deployment_recovery_plan",
                [],
                "get",
            ),
            (
                "/v1/platform/deployment-recovery:configure",
                "platform_deployment_recovery_configure",
                [],
                "post",
            ),
            (
                "/v1/platform/deployment-recovery:reconcile",
                "platform_deployment_recovery_reconcile",
                [],
                "post",
            ),
        ):
            document["paths"][path] = {
                method: _op(
                    key,
                    capability="test.transport.only",
                    kind="query" if method == "get" else "command",
                    idempotency="none" if method == "get" else "required",
                    params=params,
                )
            }
        return document

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if method == "GET" and path == "/v1/platform/configurations/email.delivery":
            self.calls.append((method, path, kwargs))
            if path == self.read_path:
                return ControlResponse(self.read_status, self.read_payload, {})
            return ControlResponse(200, {"items": []}, {})
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream,console,forbidden_forms",
    [
        (
            "/v1/platform/secrets/" + _NATIVE_ID,
            "/resources/secrets/" + _NATIVE_ID,
            ("secret-rotate", "secret-revoke"),
        ),
        (
            "/v1/platform/configurations/email.delivery/3",
            "/resources/configurations/email.delivery/3",
            ("action-validate", "action-activate"),
        ),
        (
            "/v1/platform/deployment-recovery:plan",
            "/resources/deployment-recovery",
            ("configure", "reconcile"),
        ),
    ],
)
@pytest.mark.parametrize("payload", [{}, None])
async def test_incomplete_control_read_hides_revision_sensitive_actions(
    upstream: str,
    console: str,
    forbidden_forms: tuple[str, ...],
    payload: Any,
) -> None:
    control = ExtendedReadControl(upstream, payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get(console)
    assert "invalid_owner_response" in page.text
    assert all(f'id="{form}"' not in page.text for form in forbidden_forms)
    assert len([call for call in control.calls if call[0] == "POST"]) == 1


_CONFIGURATION_PAGES: list[Any] = [{}, {"items": [{}]}, {"items": []}]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _CONFIGURATION_PAGES)
async def test_configuration_inventory_distinguishes_partial_from_valid_empty(payload: Any) -> None:
    control = ExtendedReadControl("/v1/platform/configurations", payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/configurations")
    assert ("invalid_owner_response" in page.text) is (payload != {"items": []})


@pytest.mark.asyncio
async def test_valid_configuration_detail_with_no_active_revision_keeps_actions() -> None:
    control = ExtendedReadControl(
        "/v1/platform/configurations/email.delivery/3",
        {
            "configuration_kind": "email.delivery",
            "revision": 3,
            "state": "draft",
            "configuration": {},
        },
    )
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/configurations/email.delivery/3")
    assert "invalid_owner_response" not in page.text
    assert 'id="action-activate"' in page.text


@pytest.mark.asyncio
async def test_unconfigured_deployment_preserves_owner_error_without_actions() -> None:
    control = ExtendedReadControl(
        "/v1/platform/deployment-recovery:plan", {"error": {"code": "not_configured"}}, status=404
    )
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/deployment-recovery")
    assert "not_configured" in page.text
    assert "invalid_owner_response" not in page.text
    assert 'id="configure"' not in page.text


_SECRET_READ: dict[str, Any] = {
    "binding_id": _NATIVE_ID,
    "purpose": "email.delivery",
    "revision": 4,
    "backend_version": 6,
}
_DEPLOYMENT_READ: dict[str, Any] = {
    "state": "in_sync",
    "changes": [],
    "binding": {
        "revision": 4,
        "base_url": "https://deployment.example.test",
        "database_uuid": "database-installation",
        "secret_binding_id": _NATIVE_ID,
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream,console,payload,form",
    [
        (
            "/v1/platform/secrets/" + _NATIVE_ID,
            "/resources/secrets/" + _NATIVE_ID,
            _SECRET_READ,
            "secret-rotate",
        ),
        (
            "/v1/platform/deployment-recovery:plan",
            "/resources/deployment-recovery",
            _DEPLOYMENT_READ,
            "configure",
        ),
    ],
)
async def test_valid_secret_and_deployment_read_remain_actionable(
    upstream: str,
    console: str,
    payload: dict[str, Any],
    form: str,
) -> None:
    control = ExtendedReadControl(upstream, payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get(console)
    assert "invalid_owner_response" not in page.text
    assert f'id="{form}"' in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {**_SECRET_READ, "binding_id": _PRINCIPAL_ID},
        {**_SECRET_READ, "revision": True},
        {**_SECRET_READ, "backend_version": 0},
    ],
)
async def test_secret_revision_or_identity_mismatch_cannot_supply_actions(
    payload: dict[str, Any],
) -> None:
    control = ExtendedReadControl("/v1/platform/secrets/" + _NATIVE_ID, payload)
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/secrets/" + _NATIVE_ID)
    assert "invalid_owner_response" in page.text
    assert 'id="secret-rotate"' not in page.text


class InitialDeploymentControl(FakeControl):
    def __init__(self, *, error_code: str = "platform_configuration_changed") -> None:
        super().__init__()
        self.error_code = error_code

    async def openapi(self) -> dict[str, Any]:
        inert = cast(Any, object())
        return create_platform_control_app(
            auth_session_factory=inert,
            platform_read_session_factory=inert,
            platform_write_session_factory=inert,
            native_authority_id=UUID(int=1),
            webauthn_decoy_key=b"initial-binding-ui-proof-key-32-bytes",
        ).openapi()

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/v1/platform/deployment-recovery:plan":
            self.calls.append((method, path, kwargs))
            return ControlResponse(404, {"error": {"code": "platform_configuration_not_found"}}, {})
        if method == "PUT" and path == "/v1/platform/deployment-recovery":
            self.calls.append((method, path, kwargs))
            return ControlResponse(
                403 if self.error_code == "phishing_resistant_auth_required" else 409,
                {"error": {"code": self.error_code}},
                {},
            )
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_initial_deployment_setup_uses_canonical_default_without_get_effects() -> None:
    control = InitialDeploymentControl()
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        anonymous = await client.get("/resources/deployment-recovery/new")
        assert anonymous.status_code == 303
        assert control.calls == []
        await _login(client)
        missing = await client.get("/resources/deployment-recovery")
        assert 'href="/resources/deployment-recovery/new"' in missing.text
        assert "No changes reported" not in missing.text
        page = await client.get("/resources/deployment-recovery/new")
        assert page.status_code == 200
        assert 'id="configure"' in page.text
        assert 'name="expected_active_revision"' in page.text
        assert 'value="0"' not in page.text
        assert 'id="reconcile"' not in page.text
        assert [method for method, _, _ in control.calls] == ["POST", "GET"]
        csrf = _CSRF_RE.search(page.text)
        assert csrf is not None
        data = {
            "csrf_token": csrf.group(1),
            "base_url": "https://deployment.example.test",
            "database_uuid": "database-installation",
            "secret_binding_id": _NATIVE_ID,
            "expected_active_revision": "",
            "scheduled_backup_uuid": "",
            "s3_storage_uuid": "",
            "_intent_id": "initial-binding-proof-intent",
        }
        denied = await client.post(
            "/resources/deployment-recovery/actions/configure", data={**data, "csrf_token": "bad"}
        )
        assert "CSRF" in denied.text
        assert not [call for call in control.calls if call[0] == "PUT"]
        conflict = await client.post("/resources/deployment-recovery/actions/configure", data=data)
        assert "configuration changed" in conflict.text.lower()
        writes = [call for call in control.calls if call[0] == "PUT"]
        assert len(writes) == 1
        forwarded = writes[0][2]
        assert "expected_active_revision" not in forwarded["json_body"]
        assert (
            DeploymentBindingBody.model_validate(forwarded["json_body"]).expected_active_revision
            is None
        )
        assert forwarded["json_body"]["secret_binding_id"] == _NATIVE_ID
        assert forwarded["extra_headers"]["idempotency-key"] == "initial-binding-proof-intent"


@pytest.mark.asyncio
async def test_initial_binding_step_up_points_to_the_actual_submitted_form() -> None:
    control = InitialDeploymentControl(error_code="phishing_resistant_auth_required")
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await _login(client)
        page = await client.get("/resources/deployment-recovery/new")
        csrf = _CSRF_RE.search(page.text)
        assert csrf is not None
        response = await client.post(
            "/resources/deployment-recovery/actions/configure",
            data={
                "csrf_token": csrf.group(1),
                "base_url": "https://deployment.example.test",
                "database_uuid": "database-installation",
                "secret_binding_id": _NATIVE_ID,
                "_intent_id": "initial-binding-step-up-intent",
            },
        )
        assert 'data-retry-form="configure"' in response.text
        assert 'id="configure"' in page.text
        assert "initial-binding-step-up-intent" in response.text
        write = next(call for call in control.calls if call[0] == "PUT")
        assert write[2]["extra_headers"]["idempotency-key"] == "initial-binding-step-up-intent"
        assert "expected_active_revision" not in write[2]["json_body"]
