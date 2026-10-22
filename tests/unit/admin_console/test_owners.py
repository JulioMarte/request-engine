"""BFF owner journey proof: HTTP projection, not database authority certification."""

import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app

_OWNER = "11111111-1111-4111-8111-111111111111"
_INVITATION = "22222222-2222-4222-8222-222222222222"
_NEXT = "33333333-3333-4333-8333-333333333333"
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


class OwnerControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.failure: int | None = None
        self.malformed = False
        self.empty = False
        self.step_up = False
        self.missing_operation = False
        self.partial_revision = False
        self.include_private = False
        self.unreachable = False

    async def openapi(self) -> dict[str, Any]:
        app = create_platform_control_app(
            auth_session_factory=cast(Any, object()),
            platform_read_session_factory=cast(Any, object()),
            platform_write_session_factory=cast(Any, object()),
            native_authority_id=UUID(_OWNER),
            webauthn_decoy_key=b"owner-console-contract-32-byte-key",
        )
        schema = app.openapi()
        if self.missing_operation:
            del schema["paths"]["/v1/platform/owners"]["get"]
        return schema

    async def aclose(self) -> None:
        pass

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "owner-test-bearer"}, {})
        if self.unreachable:
            raise httpx.ConnectError("upstream unavailable")
        if self.failure is not None:
            return ControlResponse(self.failure, {"private": "must-never-render"}, {})
        if self.malformed:
            return ControlResponse(200, {"unexpected": "must-never-render"}, {})
        if method == "POST":
            if self.step_up:
                return ControlResponse(
                    403, {"error": {"code": "recent_authentication_required"}}, {}
                )
            return ControlResponse(200, {"action": "completed"}, {})
        owner = {
            "principal_id": _OWNER,
            "active": True,
            "authority_revision": 7,
            "binding_id": None,
            "binding_status": "active",
            "capabilities": ["platform.owner.read"],
        }
        invitation = {
            "invitation_id": _INVITATION,
            "status": "enrolled",
            "revision": 4,
            "native_identity_id": _NEXT,
            "created_at": "2026-10-11T10:00:00Z",
            "expires_at": "2026-10-12T10:00:00Z",
            "enrolled_at": "2026-10-11T10:30:00Z",
            "consumed_at": None,
            "revoked_at": None,
            "expired": False,
        }
        item = invitation if "owner-invitations" in path else owner
        if self.partial_revision:
            del item["revision" if "owner-invitations" in path else "authority_revision"]
        if self.include_private:
            item["invitation_token"] = "must-never-render"
            item["private_unrecognized_field"] = "must-never-render"
        if path.endswith(_OWNER) or path.endswith(_INVITATION):
            return ControlResponse(200, item, {})
        return ControlResponse(
            200, {"items": [] if self.empty else [item], "next_after": _NEXT}, {}
        )


def _client(control: OwnerControl) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        control_api_base_url="http://control:8001",
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        session_secret=SecretStr("owner-console-unit-session-secret-40-chars"),
        cookie_secure=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_admin_console_app(settings, client=control)),
        base_url="http://console",
        headers={"Origin": "http://console"},
    )


async def _login(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
    ).status_code == 303


@pytest.mark.asyncio
@pytest.mark.parametrize("invitations", [False, True])
async def test_owner_collections_project_canonical_http_and_pagination(invitations: bool) -> None:
    control = OwnerControl()
    console_path = "/resources/owners" + ("/invitations" if invitations else "")
    api_path = "/v1/platform/owner-invitations" if invitations else "/v1/platform/owners"
    async with _client(control) as client:
        await _login(client)
        page = await client.get(console_path, params={"limit": "3", "after": _OWNER})
        assert page.status_code == 200
        assert (_INVITATION if invitations else _OWNER) in page.text
        assert f"after={_NEXT}&amp;limit=3" in page.text
        assert "Primera página" in page.text
        assert "no owner enumeration operation" not in page.text
        call = next(call for call in control.calls if call[1] == api_path)
        assert call[0] == "GET"
        assert call[2]["bearer"] == "owner-test-bearer"
        assert call[2]["params"] == {"after": _OWNER, "limit": "3"}
        control.calls.clear()
        invalid = await client.get(console_path, params={"limit": "101"})
        assert invalid.status_code == 422
        assert not control.calls


@pytest.mark.asyncio
async def test_owner_detail_prefills_real_authority_revision_and_route_identity() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        page = await client.get(f"/resources/owners/{_OWNER}")
        assert page.status_code == 200
        assert 'name="expected_revision"' in page.text
        assert 'value="7"' in page.text
        csrf = _CSRF.search(page.text)
        assert csrf is not None
        data = {
            "csrf_token": csrf.group(1),
            "_intent_id": "reviewed-owner-intent",
            "principal_id": _NEXT,
            "expected_revision": "7",
            "reason_code": "access_review",
        }
        result = await client.post(f"/resources/owners/{_OWNER}/actions/suspend", data=data)
        assert "Acción completada" in result.text
        call = control.calls[-1]
        assert call[1] == f"/v1/platform/owners/{_OWNER}:suspend"
        assert call[2]["json_body"] == {"expected_revision": 7, "reason_code": "access_review"}
        assert call[2]["extra_headers"] == {"idempotency-key": "reviewed-owner-intent"}
        count = len(control.calls)
        data["csrf_token"] = "wrong"
        denied = await client.post(f"/resources/owners/{_OWNER}/actions/suspend", data=data)
        assert "csrf_failed" in denied.text
        assert len(control.calls) == count


@pytest.mark.asyncio
async def test_owner_invitation_detail_and_activate_use_invitation_identity() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        page = await client.get(f"/resources/owners/invitations/{_INVITATION}")
        assert page.status_code == 200
        assert "enrolled" in page.text
        assert "Activar dueño inscrito" in page.text
        assert "solo indica que pasó la fecha" in page.text
        csrf = _CSRF.search(page.text)
        assert csrf is not None
        result = await client.post(
            f"/resources/owners/invitations/{_INVITATION}/actions/activate",
            data={
                "csrf_token": csrf.group(1),
                "_intent_id": "activate-once",
                "invitation_id": _NEXT,
            },
        )
        assert "Acción completada" in result.text
        assert control.calls[-1][1] == f"/v1/platform/owner-invitations/{_INVITATION}:activate"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 503])
@pytest.mark.parametrize("path", ["/resources/owners", f"/resources/owners/{_OWNER}"])
async def test_owner_read_failure_hides_information_and_actions(status: int, path: str) -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        control.failure = status
        page = await client.get(path)
        assert page.status_code == status
        assert "must-never-render" not in page.text
        assert "No se muestran datos de dueños ni formularios de acción" in page.text
        assert "owner-suspend" not in page.text
        assert "owner-invite" not in page.text
        assert "Iniciar sesión de nuevo" in page.text


@pytest.mark.asyncio
async def test_owner_malformed_success_is_incomplete_not_empty_or_healthy() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        control.malformed = True
        page = await client.get("/resources/owners")
        assert page.status_code == 502
        assert "respuesta incompleta" in page.text
        assert "must-never-render" not in page.text
        assert "No hay dueños ni invitaciones" not in page.text


@pytest.mark.asyncio
async def test_owner_step_up_preserves_form_and_intent() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        page = await client.get(f"/resources/owners/{_OWNER}")
        csrf = _CSRF.search(page.text)
        assert csrf is not None
        control.step_up = True
        result = await client.post(
            f"/resources/owners/{_OWNER}/actions/revoke",
            data={
                "csrf_token": csrf.group(1),
                "expected_revision": "7",
                "reason_code": "access_review",
                "_intent_id": "original-intent",
            },
        )
        assert 'data-retry-form="owner-revoke"' in result.text
        assert "original-intent" in result.text
        assert control.calls[-1][2]["extra_headers"]["idempotency-key"] == "original-intent"


@pytest.mark.asyncio
async def test_owner_missing_read_operation_fails_closed_and_anonymous_reads_redirect() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        page = await client.get("/resources/owners")
        assert page.status_code == 303
        assert not control.calls
        await _login(client)
        control.missing_operation = True
        control.calls.clear()
        page = await client.get("/resources/owners")
        assert page.status_code == 503
        assert not control.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("invitations", [False, True])
async def test_owner_partial_detail_never_offers_actions_and_unknown_fields_are_hidden(
    invitations: bool,
) -> None:
    control = OwnerControl()
    path = (
        f"/resources/owners/invitations/{_INVITATION}"
        if invitations
        else f"/resources/owners/{_OWNER}"
    )
    async with _client(control) as client:
        await _login(client)
        control.include_private = True
        page = await client.get(path)
        assert page.status_code == 200
        assert "must-never-render" not in page.text
        control.partial_revision = True
        page = await client.get(path)
        assert page.status_code == 502
        assert "No se muestran datos de dueños ni formularios de acción" in page.text
        assert 'class="stack action-form"' not in page.text


@pytest.mark.asyncio
async def test_owner_empty_success_and_network_failure_are_distinct() -> None:
    control = OwnerControl()
    async with _client(control) as client:
        await _login(client)
        control.empty = True
        page = await client.get("/resources/owners")
        assert page.status_code == 200
        assert "servicio de dueños devolvió una página vacía" in page.text
        control.unreachable = True
        page = await client.get("/resources/owners")
        assert page.status_code == 503
        assert "no está disponible por el momento" in page.text
        assert "servicio de dueños devolvió una página vacía" not in page.text


class _InvitingControl(OwnerControl):
    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if method == "POST" and path == "/v1/platform/owner-invitations":
            self.calls.append((method, path, kwargs))
            return ControlResponse(
                201,
                {
                    "invitation_id": _NEXT,
                    "invitation_token": "one-time-handoff-code",
                    "token_available": True,
                    "expires_at": "2026-10-12T10:00:00Z",
                },
                {},
            )
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_created_invitation_code_is_shown_once_as_the_handoff_value() -> None:
    control = _InvitingControl()
    async with _client(control) as client:
        await _login(client)
        page = await client.get("/resources/owners/invitations")
        csrf = _CSRF.search(page.text)
        assert csrf is not None
        assert "one-time-handoff-code" not in page.text
        result = await client.post(
            "/resources/owners/actions/invite",
            data={
                "csrf_token": csrf.group(1),
                "provenance_reference": "second owner",
                "_intent_id": "invite-intent",
            },
        )
        reread = await client.get("/resources/owners/invitations")
    assert "Entregue este código de invitación al nuevo dueño" in result.text
    # Exactly once: in the handoff box, not repeated in raw technical JSON.
    assert result.text.count("one-time-handoff-code") == 1
    assert "one-time-handoff-code" not in reread.text
