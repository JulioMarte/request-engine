"""Proof of API-only invitation forwarding, CSRF and pretenant acceptance."""

import os
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.modules.tenancy.api.staff_invitations import (
    StaffInvitationChangeBody,
    StaffInvitationCreateBody,
)

ORG = "11111111-1111-4111-8111-111111111111"
INVITATION = "22222222-2222-4222-8222-222222222222"
TOKEN = INVITATION + "." + "a" * 43


class InvitationApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.list_status = 200
        self.accept_status = 200
        self.accept_error_code = ""
        self.preview_status = 200
        self.delivery_status = "unknown"

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "real-upstream-token"}, {})
        if path == "/v1/staff/invitations" and method == "GET":
            return ControlResponse(
                self.list_status,
                {
                    "items": [
                        {
                            "invitation_id": INVITATION,
                            "organization_id": ORG,
                            "email": "recipient@example.org",
                            "status": "pending",
                            "revision": 7,
                            "delivery_status": self.delivery_status,
                            "expires_at": "2026-10-04T00:00:00Z",
                        }
                    ],
                    "next_after": None,
                },
                {},
            )
        if path.endswith(":accept"):
            return ControlResponse(
                self.accept_status,
                {"token": "must-never-be-echoed", "error": {"code": self.accept_error_code}},
                {},
            )
        if path.endswith(":preview"):
            return ControlResponse(
                self.preview_status,
                {
                    "organization_display_name": "Example organization",
                    "expires_at": "2026-10-04T00:00:00Z",
                    "token": "must-never-be-echoed",
                },
                {},
            )
        return ControlResponse(201, {}, {})

    async def openapi(self) -> dict[str, Any]:
        paths: dict[str, Any] = {}
        for action, method, path in (
            ("list", "get", "/v1/staff/invitations"),
            ("create", "post", "/v1/staff/invitations"),
            ("resend", "post", "/v1/staff/invitations/{invitation_id}:resend"),
            ("revoke", "post", "/v1/staff/invitations/{invitation_id}:revoke"),
            ("accept", "post", "/v1/staff/invitations/{invitation_id}:accept"),
            ("preview", "post", "/v1/staff/invitations/{invitation_id}:preview"),
        ):
            op: dict[str, Any] = {
                "operationId": f"staff_invitation_{action}",
                "security": [{"SubjectBearer": []}],
                "x-request-engine-owner": "tenancy",
                "x-request-engine-capability": "staff.read" if action == "list" else "staff.invite",
                "x-request-engine-idempotency": "none"
                if action in {"list", "accept"}
                else "required",
                "parameters": [
                    {
                        "name": "invitation_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ]
                if "{" in path
                else [],
            }
            if method == "post":
                schema = (
                    StaffInvitationCreateBody.model_json_schema()
                    if action == "create"
                    else StaffInvitationChangeBody.model_json_schema()
                )
                op["requestBody"] = {"content": {"application/json": {"schema": schema}}}
            paths.setdefault(path, {})[method] = op
        return {"paths": paths}

    async def aclose(self) -> None:
        pass


def client_for(api: InvitationApi) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=api, runtime_client=api)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://console")


def csrf(page: httpx.Response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match is not None
    return match.group(1)


@pytest.mark.asyncio
async def test_preview_requires_session_csrf_and_forwards_only_proof() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        anonymous = await client.post("/staff-invitations/preview", data={"token": TOKEN})
        await client.post("/login", data={"login_handle": "recipient", "password": "pw"})
        page = await client.get("/staff-invitations/accept")
        denied = await client.post("/staff-invitations/preview", data={"token": TOKEN})
        preview = await client.post(
            "/staff-invitations/preview",
            data={"csrf_token": csrf(page), "token": TOKEN, "organization_id": ORG},
        )
    assert anonymous.status_code == 401
    assert denied.status_code == 403
    assert preview.json() == {
        "ok": True,
        "organization_display_name": "Example organization",
        "expires_at": "2026-10-04T00:00:00Z",
    }
    assert preview.headers["cache-control"] == "no-store"
    assert "must-never-be-echoed" not in preview.text
    assert [call for call in api.calls if call[1].endswith(":preview")] == [
        (
            "POST",
            f"/v1/staff/invitations/{INVITATION}:preview",
            {"bearer": "real-upstream-token", "json_body": {"token": TOKEN}},
        )
    ]
    assert not any(call[1].endswith(":accept") for call in api.calls)
    assert 'id="invitation-preview"' in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 409, 503])
async def test_preview_failure_never_exposes_upstream_proof_or_organization(status: int) -> None:
    api = InvitationApi()
    api.preview_status = status
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "recipient", "password": "pw"})
        page = await client.get("/staff-invitations/accept")
        preview = await client.post(
            "/staff-invitations/preview", data={"csrf_token": csrf(page), "token": TOKEN}
        )
    assert preview.status_code == status
    assert "Example organization" not in preview.text
    assert "must-never-be-echoed" not in preview.text
    assert not any(call[1].endswith(":accept") for call in api.calls)


@pytest.mark.asyncio
async def test_accept_requires_session_csrf_and_forwards_no_tenant_or_subject() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        anonymous = await client.post("/staff-invitations/accept", data={"token": TOKEN})
        await client.post("/login", data={"login_handle": "recipient", "password": "pw"})
        page = await client.get(f"/staff-invitations/{INVITATION}/accept")
        denied = await client.post("/staff-invitations/accept", data={"token": TOKEN})
        accepted = await client.post(
            "/staff-invitations/accept",
            data={
                "csrf_token": csrf(page),
                "token": TOKEN,
                "organization_id": ORG,
                "principal_id": ORG,
            },
        )
    assert anonymous.status_code == 401
    assert denied.status_code == 403
    assert accepted.json() == {"ok": True, "next": "/my-organizations"}
    assert "must-never-be-echoed" not in accepted.text
    calls = [call for call in api.calls if call[1].endswith(":accept")]
    assert calls == [
        (
            "POST",
            f"/v1/staff/invitations/{INVITATION}:accept",
            {
                "bearer": "real-upstream-token",
                "json_body": {"token": TOKEN},
            },
        )
    ]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert TOKEN not in page.text


@pytest.mark.asyncio
async def test_resend_forwards_exact_revision_and_stable_intent() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff-invitations")
        result = await client.post(
            f"/tenants/{ORG}/staff-invitations/{INVITATION}/resend",
            data={
                "csrf_token": csrf(page),
                "expected_revision": "7",
                "provenance_reference": "owner:resend",
                "_intent_id": "same-intent",
            },
        )
    assert result.status_code == 303
    assert 'value="7"' in page.text
    assert "unknown" in page.text and "email arrived" in page.text
    call = api.calls[-1]
    assert call[2]["json_body"] == {"expected_revision": 7, "provenance_reference": "owner:resend"}
    assert call[2]["extra_headers"] == {
        "idempotency-key": "same-intent",
        "X-RE-Organization-ID": ORG,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 503])
async def test_failed_list_explains_failure_and_hides_create_and_mutations(status: int) -> None:
    api = InvitationApi()
    api.list_status = status
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff-invitations")
    assert page.status_code == status
    assert 'role="alert"' in page.text
    assert "Invitations unavailable. Check your session and permissions, then reload." in page.text
    assert "Create invitation" not in page.text
    assert "recipient@example.org" not in page.text
    assert all(method != "POST" or path == "/auth/native/sessions" for method, path, _ in api.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("next_url", ["https://evil.example", "//evil.example", "/setup"])
async def test_login_return_is_allowlisted(next_url: str) -> None:
    async with client_for(InvitationApi()) as client:
        response = await client.post(
            "/login",
            data={
                "login_handle": "recipient",
                "password": "pw",
                "next": next_url,
            },
        )
        valid = await client.post(
            "/login",
            data={
                "login_handle": "recipient",
                "password": "pw",
                "next": "/staff-invitations/accept",
            },
        )
    assert response.headers["location"] == "/"
    assert valid.headers["location"] == "/staff-invitations/accept"


@pytest.mark.asyncio
async def test_enrollment_uses_canonical_anonymous_api_without_echoing_credentials() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        denied = await client.post("/staff-invitations/enroll", data={"login_handle": "new"})
        page = await client.get("/staff-invitations/enroll")
        response = await client.post(
            "/staff-invitations/enroll",
            data={
                "csrf_token": csrf(page),
                "login_handle": "new",
                "password": "secret-password",
            },
        )
    assert denied.status_code == 403
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/staff-invitations/accept"
    assert api.calls[-1] == (
        "POST",
        "/auth/native/identities",
        {
            "json_body": {"login_handle": "new", "password": "secret-password"},
        },
    )
    assert "secret-password" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 409, 503])
async def test_acceptance_failure_is_sanitized_and_never_redirects(status: int) -> None:
    api = InvitationApi()
    api.accept_status = status
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "recipient", "password": "pw"})
        page = await client.get("/staff-invitations/accept")
        response = await client.post(
            "/staff-invitations/accept",
            data={
                "csrf_token": csrf(page),
                "token": TOKEN,
            },
        )
    assert response.status_code == status
    assert "must-never-be-echoed" not in response.text
    assert "next" not in response.json()


@pytest.mark.asyncio
async def test_create_requires_csrf_before_any_owner_mutation() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        denied = await client.post(
            f"/tenants/{ORG}/staff-invitations",
            data={
                "email": "recipient@example.org",
                "provenance_reference": "test",
            },
        )
        page = await client.get(f"/tenants/{ORG}/staff-invitations")
        created = await client.post(
            f"/tenants/{ORG}/staff-invitations",
            data={
                "csrf_token": csrf(page),
                "email": "recipient@example.org",
                "provenance_reference": "test",
                "expires_in_hours": "72",
                "_intent_id": "create-once",
            },
        )
    assert denied.status_code == 403
    assert created.status_code == 303
    calls = [call for call in api.calls if call[:2] == ("POST", "/v1/staff/invitations")]
    assert len(calls) == 1
    assert calls[0][2]["json_body"] == {
        "email": "recipient@example.org",
        "provenance_reference": "test",
        "expires_in_hours": 72,
    }
    assert calls[0][2]["extra_headers"]["idempotency-key"] == "create-once"


@pytest.mark.asyncio
async def test_smtp_acceptance_never_claims_inbox_receipt_or_no_inflight_mail() -> None:
    api = InvitationApi()
    api.delivery_status = "delivered"
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff-invitations")
    assert "Accepted by mail server (inbox not confirmed)" in page.text
    assert "email already being submitted may still arrive" in page.text


@pytest.mark.asyncio
async def test_enrollment_rejects_forged_double_submit_cookie_before_api() -> None:
    api = InvitationApi()
    async with client_for(api) as client:
        client.cookies.set("staff_enrollment_csrf", "forged.same-value")
        response = await client.post(
            "/staff-invitations/enroll",
            data={
                "csrf_token": "forged.same-value",
                "login_handle": "attacker",
                "password": "pw",
            },
        )
    assert response.status_code == 403
    assert api.calls == []


@pytest.mark.asyncio
async def test_existing_member_needs_access_review_not_another_invitation() -> None:
    api = InvitationApi()
    api.accept_status = 409
    api.accept_error_code = "staff_invitation_identity_already_linked"
    async with client_for(api) as client:
        await client.post("/login", data={"login_handle": "recipient", "password": "pw"})
        page = await client.get("/staff-invitations/accept")
        response = await client.post(
            "/staff-invitations/accept", data={"csrf_token": csrf(page), "token": TOKEN}
        )
    assert response.status_code == 409
    assert "existing membership and permissions" in response.json()["error"]
    assert "another invitation will not restore access" in response.json()["error"]
    assert TOKEN not in response.text
    assert "must-never-be-echoed" not in response.text
