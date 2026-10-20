"""Recipient owner enrollment without login, implicit grants or credential disclosure."""

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

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
_PRIVATE_PROOF = "private-invitation-proof-test-only"
_PASSWORD = "private-new-password-test-only"
_ID = "11111111-1111-4111-8111-111111111111"


class EnrollmentControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.failure = False
        self.timeout = False
        self.strong_denied = False
        self.override: dict[str, Any] = {}

    async def openapi(self) -> dict[str, Any]:
        return {"paths": {}}

    async def aclose(self) -> None:
        pass

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path in self.override:
            return ControlResponse(200, self.override[path], {})
        if path == "/v1/platform/owner-invitations:enroll":
            if self.timeout:
                raise httpx.ReadTimeout("not confirmed")
            if self.failure:
                return ControlResponse(409, {"error": {"message": _PRIVATE_PROOF}}, {})
            return ControlResponse(
                201,
                {
                    "invitation_id": _ID,
                    "native_identity_id": _ID,
                    "password": _PASSWORD,
                    "invitation_token": _PRIVATE_PROOF,
                },
                {},
            )
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "private-subject-bearer"}, {})
        if path.endswith("recovery-readiness"):
            return ControlResponse(
                200,
                {
                    "active_webauthn_credentials": 1,
                    "active_code_set": False,
                    "remaining_codes": 0,
                    "recovery_state": "ready",
                    "password": _PASSWORD,
                },
                {},
            )
        if path.endswith("registration-options"):
            return ControlResponse(
                200,
                {
                    "public_key": {"challenge": "Y2hhbGxlbmdl", "user": {"id": "dXNlcg"}},
                    "access_token": "never-return-token",
                },
                {},
            )
        if path.endswith("registrations"):
            return ControlResponse(
                201, {"credential_id": _ID, "access_token": "never-return-token"}, {}
            )
        if path.endswith("recovery-codes"):
            if self.strong_denied:
                return ControlResponse(403, {"error": {"message": _PASSWORD}}, {})
            return ControlResponse(
                201, {"codes": ["one-time-private-code"], "access_token": "never-return-token"}, {}
            )
        return ControlResponse(404, None, {})


def _client(control: EnrollmentControl) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        control_api_base_url="http://control",
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        session_secret=SecretStr("owner-enrollment-unit-private-secret-40-chars"),
        cookie_secure=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_admin_console_app(settings, client=control)),
        base_url="http://console",
        headers={"Origin": "http://console", "X-Requested-With": "fetch"},
    )


def _csrf(page: httpx.Response) -> str:
    match = _CSRF.search(page.text)
    assert match is not None
    return match.group(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["normal", "recovery_restricted"])
async def test_account_security_offers_optional_passkey_and_password_recovery(state: str) -> None:
    control = EnrollmentControl()
    control.override["/auth/native/sessions/current/recovery-readiness"] = {
        "active_webauthn_credentials": 0,
        "active_code_set": True,
        "remaining_codes": 2,
        "recovery_state": state,
    }
    async with _client(control) as client:
        await client.post("/login", data={"login_handle": "owner", "password": _PASSWORD})
        page = await client.get("/account/security")
        assert page.status_code == 200
        assert "Optional: add a passkey" in page.text
        assert "Confirm with password" in page.text
        assert "Register passkey" in page.text
        assert ("data-password-recovery-complete" in page.text) is (state == "recovery_restricted")
        if state == "recovery_restricted":
            assert "Completion does not upgrade this recovery session" in page.text
            assert "Sign out to sign in again" in page.text


@pytest.mark.asyncio
async def test_owner_recipient_can_enroll_without_login_and_secrets_never_return(
    caplog: pytest.LogCaptureFixture,
) -> None:
    control = EnrollmentControl()
    async with _client(control) as client:
        page = await client.get("/owner-invitations/enroll")
        assert page.status_code == 200
        cookie = page.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "private" not in cookie
        assert not control.calls
        result = await client.post(
            "/owner-invitations/enroll",
            data={
                "csrf_token": _csrf(page),
                "invitation_token": _PRIVATE_PROOF,
                "login_handle": "invited.owner",
                "password": _PASSWORD,
            },
        )
        assert result.status_code == 200
        assert "Platform owner authority has not been activated" in result.text
        assert "/login?next=/account/security" in result.text
        assert _PRIVATE_PROOF not in result.text
        assert _PASSWORD not in result.text
        call = control.calls[0]
        assert call[1] == "/v1/platform/owner-invitations:enroll"
        assert call[2].get("bearer") is None
        assert call[2]["json_body"] == {
            "invitation_token": _PRIVATE_PROOF,
            "login_handle": "invited.owner",
            "password": _PASSWORD,
        }
        assert len(control.calls) == 1
        assert "re_admin_console=" not in result.headers["set-cookie"]
    assert _PRIVATE_PROOF not in caplog.text
    assert _PASSWORD not in caplog.text
    records = (
        Path(os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"])
        / "owner-enrollment"
    )
    assert not list(records.glob("*.session"))


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [None, "https://foreign.example"])
async def test_owner_enrollment_origin_and_csrf_reject_before_forwarding(
    origin: str | None,
) -> None:
    control = EnrollmentControl()
    async with _client(control) as client:
        page = await client.get("/owner-invitations/enroll")
        if origin is None:
            client.headers.pop("Origin")
        else:
            client.headers["Origin"] = origin
        response = await client.post("/owner-invitations/enroll", data={"csrf_token": _csrf(page)})
        assert response.status_code == 403
        assert not control.calls
        client.headers["Origin"] = "http://console"
        response = await client.post("/owner-invitations/enroll", data={"csrf_token": "wrong"})
        assert response.status_code == 403
        assert not control.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_owner_enrollment_failure_clears_secret_fields_and_never_claims_activation(
    ambiguous: bool,
) -> None:
    control = EnrollmentControl()
    async with _client(control) as client:
        page = await client.get("/owner-invitations/enroll")
        control.timeout = ambiguous
        control.failure = not ambiguous
        result = await client.post(
            "/owner-invitations/enroll",
            data={
                "csrf_token": _csrf(page),
                "invitation_token": _PRIVATE_PROOF,
                "login_handle": "invited.owner",
                "password": _PASSWORD,
            },
        )
        assert result.status_code == (503 if ambiguous else 409)
        assert _PASSWORD not in result.text
        assert _PRIVATE_PROOF not in result.text
        assert "Your account was enrolled" not in result.text
        assert "signing in" in result.text if ambiguous else "could not be enrolled" in result.text


@pytest.mark.asyncio
async def test_account_security_enrollment_and_offline_codes_delegate_subject_only() -> None:
    control = EnrollmentControl()
    async with _client(control) as client:
        anonymous = await client.get("/account/security")
        assert anonymous.status_code == 303
        assert not control.calls
        login = await client.post(
            "/login",
            data={
                "login_handle": "invited.owner",
                "password": _PASSWORD,
                "next": "/account/security",
            },
        )
        assert login.headers["location"] == "/account/security"
        page = await client.get("/account/security")
        assert page.status_code == 200
        assert _PASSWORD not in page.text
        token = _csrf(page)
        denied = await client.post(
            "/account/security/passkey/options", json={"csrf_token": "wrong"}
        )
        assert denied.status_code == 403
        options = await client.post("/account/security/passkey/options", json={"csrf_token": token})
        assert options.status_code == 200
        assert options.json() == {
            "public_key": {"challenge": "Y2hhbGxlbmdl", "user": {"id": "dXNlcg"}}
        }
        complete = await client.post(
            "/account/security/passkey/complete",
            json={"csrf_token": token, "credential": {"id": "authenticator-credential"}},
        )
        assert complete.json() == {"ok": True}
        call = control.calls[-1]
        assert call[2]["bearer"] == "private-subject-bearer"
        assert call[2]["json_body"] == {"credential": {"id": "authenticator-credential"}}
        control.strong_denied = True
        codes_denied = await client.post(
            "/account/security/recovery-codes", data={"csrf_token": token}
        )
        assert codes_denied.status_code == 403
        assert "one-time-private-code" not in codes_denied.text
        assert _PASSWORD not in codes_denied.text
        control.strong_denied = False
        codes = await client.post("/account/security/recovery-codes", data={"csrf_token": token})
        assert "one-time-private-code" in codes.text
        assert "never-return-token" not in codes.text
        assert "no-store" in codes.headers["cache-control"]
        reloaded = await client.get("/account/security")
        assert "one-time-private-code" not in reloaded.text
        assert all(":activate" not in call[1] for call in control.calls)


@pytest.mark.asyncio
async def test_native_private_form_fallback_is_rejected_before_consuming_secrets() -> None:
    control = EnrollmentControl()
    async with _client(control) as client:
        page = await client.get("/owner-invitations/enroll")
        client.headers.pop("X-Requested-With")
        denied = await client.post(
            "/owner-invitations/enroll",
            data={
                "csrf_token": _csrf(page),
                "invitation_token": _PRIVATE_PROOF,
                "login_handle": "invited.owner",
                "password": _PASSWORD,
            },
        )
        assert denied.status_code == 400
        assert not control.calls
        denied = await client.post("/account/security/recovery-codes")
        assert denied.status_code == 400
        assert not control.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"invitation_id": "bogus", "native_identity_id": _ID},
        {"invitation_id": _ID, "native_identity_id": ""},
    ],
)
async def test_malformed_enrollment_success_never_claims_enrollment(
    payload: dict[str, Any],
) -> None:
    control = EnrollmentControl()
    control.override["/v1/platform/owner-invitations:enroll"] = payload
    async with _client(control) as client:
        page = await client.get("/owner-invitations/enroll")
        result = await client.post(
            "/owner-invitations/enroll",
            data={
                "csrf_token": _csrf(page),
                "invitation_token": _PRIVATE_PROOF,
                "login_handle": "invited.owner",
                "password": _PASSWORD,
            },
        )
        assert result.status_code == 502
        assert "Your account was enrolled" not in result.text
        assert _PASSWORD not in result.text
        assert _PRIVATE_PROOF not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"remaining_codes": -1},
        {"active_webauthn_credentials": -1},
        {"remaining_codes": True},
        {"recovery_state": ""},
        {"recovery_state": None},
    ],
)
async def test_malformed_security_readiness_is_unavailable(invalid: dict[str, Any]) -> None:
    control = EnrollmentControl()
    control.override["/auth/native/sessions/current/recovery-readiness"] = {
        "remaining_codes": 0,
        "active_webauthn_credentials": 1,
        "active_code_set": False,
        "recovery_state": "ready",
        **invalid,
    }
    async with _client(control) as client:
        await client.post("/login", data={"login_handle": "owner", "password": _PASSWORD})
        page = await client.get("/account/security")
        assert page.status_code == 503
        assert "Current recovery preparation" not in page.text
        assert "could not be checked" in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        ("passkey/complete", {}),
        ("passkey/complete", {"credential_id": "bogus"}),
        ("recovery-codes", {"codes": [""]}),
        ("recovery-codes", {"codes": ["   "]}),
        ("recovery-codes", {"codes": ["valid", None]}),
    ],
)
async def test_malformed_private_success_cannot_claim_preparation(
    path: str, payload: dict[str, Any]
) -> None:
    control = EnrollmentControl()
    upstream = "/auth/native/sessions/current/" + (
        "webauthn/registrations" if path == "passkey/complete" else "recovery-codes"
    )
    control.override[upstream] = payload
    async with _client(control) as client:
        await client.post("/login", data={"login_handle": "owner", "password": _PASSWORD})
        page = await client.get("/account/security")
        if path == "passkey/complete":
            result = await client.post(
                "/account/security/" + path,
                json={"csrf_token": _csrf(page), "credential": {"id": _ID}},
            )
        else:
            result = await client.post(
                "/account/security/" + path, data={"csrf_token": _csrf(page)}
            )
        assert result.status_code == 502
        assert "ok" not in result.json()
        assert "Save your recovery codes privately" not in result.text
