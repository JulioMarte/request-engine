"""Console consent review forwarding, not a substitute for owner authority proofs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

_ROOT = "/resources/controller-policy-adoptions"
_API = "/v1/platform/controller-policy-adoptions"
_ID = "a8098c1a-f86e-11da-bd1a-00112444be1e"


def _document() -> dict[str, Any]:
    def operation(action: str) -> dict[str, Any]:
        item: dict[str, Any] = {
            "operationId": f"platform_controller_policy_adoption_{action}",
            "x-request-engine-exposure": "operator",
            "x-request-engine-owner": "tenancy",
            "x-request-engine-capability": "test.catalog.permission",
            "x-request-engine-kind": "command" if action == "apply" else "query",
            "x-request-engine-idempotency": "required" if action == "apply" else "none",
            "security": [{"BearerAuth": []}],
        }
        if action == "list":
            item["parameters"] = [
                {"name": key, "in": "query", "schema": {"type": "string"}}
                for key in ("after", "limit")
            ]
        else:
            item["parameters"] = [
                {"name": "request_id", "in": "path", "required": True, "schema": {"type": "string"}}
            ]
        if action == "apply":
            item["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["expected_request_revision"],
                            "properties": {"expected_request_revision": {"type": "integer"}},
                        }
                    }
                }
            }
        return item

    return {
        "paths": {
            _API: {"get": operation("list")},
            f"{_API}/{{request_id}}": {"get": operation("review")},
            f"{_API}/{{request_id}}:apply": {"post": operation("apply")},
        }
    }


class Control:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.document = _document()
        self.failure: ControlResponse | None = None

    async def openapi(self) -> dict[str, Any]:
        return self.document

    async def aclose(self) -> None:
        pass

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "owner-token"}, {})
        if self.failure:
            return self.failure
        if path == _API:
            return ControlResponse(
                200,
                {
                    "items": [
                        {
                            "request_id": _ID,
                            "organization_id": "11111111-1111-4111-8111-111111111111",
                            "status": "pending",
                            "controller_principal_id": "22222222-2222-4222-8222-222222222222",
                            "request_revision": 7,
                            "expected_authority_revision": 3,
                            "created_at": "2026-10-01T00:00:00Z",
                            "expires_at": "2026-11-01T00:00:00Z",
                            "source_policy_key": "old",
                            "target_policy_key": "current",
                        }
                    ],
                    "next_after": _ID,
                },
                {},
            )
        return ControlResponse(
            200,
            {
                "request_id": _ID,
                "organization_id": "11111111-1111-4111-8111-111111111111",
                "controller_principal_id": "22222222-2222-4222-8222-222222222222",
                "request_revision": 7,
                "expected_authority_revision": 3,
                "current_authority_revision": 3,
                "reason": "Enable appointment administration",
                "source_policy_key": "old",
                "target_policy_key": "current",
                "proposed_capabilities": ["appointments.book"],
                "revoked_capabilities": ["staff.manage"],
                "expires_at": "2026-11-01T00:00:00Z",
                "proposed_delta_does_not_restore_revoked_capabilities": False,
            },
            {},
        )


def _client(tmp_path: Path, control: Control) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        control_api_base_url="http://control:8001",
        session_secret=SecretStr("test-session-secret-long-enough-40-characters"),
        cookie_secure=False,
        session_store_directory=tmp_path / "sessions",
    )
    app = create_admin_console_app(settings, client=control)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    )


async def _login(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
    ).status_code == 303


@pytest.mark.asyncio
async def test_list_review_apply_preserves_consent_revision_and_intent(tmp_path: Path) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        listing = await client.get(f"{_ROOT}?limit=2&after=previous&arbitrary=ignored")
        assert f"{_ROOT}/{_ID}" in listing.text
        assert "after=" in listing.text and "limit=2" in listing.text
        assert control.calls[-1][2]["params"] == {"after": "previous", "limit": "2"}
        review = await client.get(f"{_ROOT}/{_ID}")
        assert 'name="expected_request_revision" value="7"' in review.text
        assert "appointments.book" in review.text and "staff.manage" in review.text
        assert "Enable appointment administration" in review.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', review.text)
        assert csrf
        values = {
            "csrf_token": csrf[1],
            "expected_request_revision": "7",
            "_intent_id": "same-reviewed-intent",
            "request_id": "forged",
        }
        for _ in range(2):
            result = await client.post(f"{_ROOT}/{_ID}/apply", data=values)
            assert "Action completed" in result.text
        applies = [
            call for call in control.calls if call[0] == "POST" and call[1].endswith(":apply")
        ]
        assert len(applies) == 2
        for _, path, kwargs in applies:
            assert path == f"{_API}/{_ID}:apply"
            assert kwargs["json_body"] == {"expected_request_revision": 7}
            assert kwargs["extra_headers"] == {"idempotency-key": "same-reviewed-intent"}
            assert kwargs["bearer"] == "owner-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["recent_authentication_required", "phishing_resistant_auth_required"]
)
async def test_review_step_up_can_confirm_and_reload(tmp_path: Path, code: str) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        control.failure = ControlResponse(403, {"error": {"code": code}}, {})
        page = await client.get(f"{_ROOT}/{_ID}")
        assert "Confirm with passkey and retry" in page.text
        assert 'data-retry-form="adoption-review"' in page.text
        assert "Apply reviewed policy" not in page.text


@pytest.mark.asyncio
async def test_csrf_and_catalog_drift_never_forward_apply(tmp_path: Path) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        result = await client.post(f"{_ROOT}/{_ID}/apply", data={"expected_request_revision": "7"})
        assert "csrf_failed" in result.text
        assert not any(path.endswith(":apply") for _, path, _ in control.calls)
        control.document["paths"].pop(f"{_API}/{{request_id}}")
        result = await client.get(f"{_ROOT}/{_ID}")
        assert "operation_unavailable" in result.text
        assert "Apply reviewed policy" not in result.text


@pytest.mark.asyncio
async def test_failed_list_is_not_reported_as_empty(tmp_path: Path) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        control.failure = ControlResponse(403, {"error": {"code": "forbidden"}}, {})
        result = await client.get(_ROOT)
        assert "forbidden" in result.text
        assert "No policy adoption requests" not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [("controller_policy_adoption_conflict", 409), ("recent_authentication_required", 403)],
)
async def test_apply_failure_preserves_original_revision_without_new_review(
    tmp_path: Path, code: str, status: int
) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}/{_ID}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf
        control.failure = ControlResponse(status, {"error": {"code": code}}, {})
        values = {
            "csrf_token": csrf[1],
            "expected_request_revision": "7",
            "_intent_id": "reviewed-original",
        }
        result = await client.post(f"{_ROOT}/{_ID}/apply", data=values)
        assert code in result.text
        if status == 403:
            assert 'data-retry-form="adoption-apply"' in result.text
        assert (
            len(
                [
                    path
                    for method, path, _ in control.calls
                    if method == "GET" and path == f"{_API}/{_ID}"
                ]
            )
            == 1
        )
        assert control.calls[-1][2]["json_body"] == {"expected_request_revision": 7}
        assert control.calls[-1][2]["extra_headers"] == {"idempotency-key": "reviewed-original"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"request_id": _ID, "request_revision": 1},
        {"request_id": _ID, "request_revision": True},
        {"request_id": _ID, "request_revision": 0},
        {"request_id": "22222222-2222-4222-8222-222222222222", "request_revision": 7},
    ],
)
async def test_malformed_successful_review_never_offers_apply(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        control.failure = ControlResponse(200, payload, {})
        page = await client.get(f"{_ROOT}/{_ID}")
        assert page.status_code == 502
        assert "control_response_invalid" in page.text
        assert "Apply reviewed policy" not in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": "not-a-list"},
        {"items": [None]},
        {"items": [{"request_id": "invalid", "organization_id": "invalid", "status": "pending"}]},
    ],
)
async def test_malformed_collection_is_not_a_successful_empty_result(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        control.failure = ControlResponse(200, payload, {})
        page = await client.get(_ROOT)
        assert page.status_code == 502
        assert "control_response_invalid" in page.text
        assert "No policy adoption requests" not in page.text


@pytest.mark.asyncio
async def test_catalog_unreachable_returns_safe_unavailable_view(tmp_path: Path) -> None:
    class UnavailableCatalog(Control):
        async def openapi(self) -> dict[str, Any]:
            raise httpx.ConnectError("internal-service-details")

    async with _client(tmp_path, UnavailableCatalog()) as client:
        await _login(client)
        page = await client.get(f"{_ROOT}/{_ID}")
        assert page.status_code == 503
        assert "catalog_unavailable" in page.text
        assert "Apply reviewed policy" not in page.text
        assert "internal-service-details" not in page.text


@pytest.mark.asyncio
async def test_review_without_adoption_authority_explains_the_two_owner_rule(
    tmp_path: Path,
) -> None:
    control = Control()
    async with _client(tmp_path, control) as client:
        await _login(client)
        control.failure = ControlResponse(403, {"error": {"code": "capability_required"}}, {})
        page = await client.get(f"{_ROOT}/{_ID}")
    assert "can't approve permission changes" in page.text
    assert 'href="/resources/owners/invitations"' in page.text
    assert "Apply reviewed policy" not in page.text
    assert "Idempotency-Key" not in page.text
