"""Business workspace: role-aware navigation, home, Today, agents and approvals.

These execute the real console ASGI app, templates, session store, CSRF/origin
checks and executor against controlled upstream responses. They prove request
projection and UI behaviour, not runtime authorization (owner tests do that).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.capability_labels import (
    capability_label,
    grouped_capabilities,
)
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

pytestmark = [pytest.mark.unit]
ORG = "11111111-1111-4111-8111-111111111111"
PRINCIPAL = "22222222-2222-4222-8222-222222222222"
AGENT = "33333333-3333-4333-8333-333333333333"
QUEUE = "44444444-4444-4444-8444-444444444444"
ENTRY = "55555555-5555-4555-8555-555555555555"
PROPOSAL = "66666666-6666-4666-8666-666666666666"
WORKLOAD_AUTHORITY = "77777777-7777-4777-8777-777777777777"

_RUNTIME_OPERATIONS = {
    "self_organization_list": ("get", "/v1/me/organizations"),
    "business_get_info": ("get", "/v1/business"),
    "onboarding_read": ("get", "/v1/onboarding/readiness"),
    "staff_overview_get": ("get", "/v1/staff/overview"),
    "authority_read_self": ("get", "/v1/me/authority"),
    "agent_list": ("get", "/v1/agents"),
    "agent_get": ("get", "/v1/agents/{agent_principal_id}"),
    "agent_provision": ("post", "/v1/agents"),
    "agent_suspend": ("put", "/v1/agents/{agent_principal_id}/status"),
    "agent_manage_authority": ("put", "/v1/agents/{agent_principal_id}/authority"),
    "agent_policy_read": ("get", "/v1/agents/{agent_principal_id}/policy"),
    "agent_policy_replace": ("put", "/v1/agents/{agent_principal_id}/policy"),
    "agent_credential_rotate": ("post", "/v1/agents/{agent_principal_id}/credentials:rotate"),
    "queue_list": ("get", "/v1/queues"),
    "queue_staff_read": ("get", "/v1/queues/{queue_id}/staff"),
    "queue_call_next": ("post", "/v1/queues/{queue_id}/call-next"),
    "queue_mark_no_show": ("post", "/v1/queue-entries/{queue_entry_id}/no-show"),
    "appointments_day_board": ("get", "/v1/appointments/day-board"),
    "staff_invitation_proposal_list": ("get", "/v1/staff/invitation-proposals"),
    "staff_invitation_proposal_approve": (
        "post",
        "/v1/staff/invitation-proposals/{proposal_id}:approve",
    ),
}
_BODIES = {
    "MarkNoShowBody": {
        "type": "object",
        "properties": {"expected_revision": {"type": "integer"}},
        "required": ["expected_revision"],
    }
}


def _openapi(missing: frozenset[str] = frozenset()) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for operation_id, (method, path) in _RUNTIME_OPERATIONS.items():
        if operation_id in missing:
            continue
        operation: dict[str, Any] = {
            "operationId": operation_id,
            "x-request-engine-capability": operation_id.replace("_", "."),
        }
        parameters = [
            {"name": name.strip("{}"), "in": "path", "required": True, "schema": {"type": "string"}}
            for name in path.split("/")
            if name.startswith("{")
        ]
        if "{proposal_id}" in path:
            parameters = [
                {
                    "name": "proposal_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ]
        if method in {"post", "put"}:
            parameters = [
                *parameters,
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ]
        if parameters:
            operation["parameters"] = parameters
        if operation_id == "queue_mark_no_show":
            operation["requestBody"] = {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/MarkNoShowBody"}}
                }
            }
        paths.setdefault(path, {})[method] = operation
    return {"paths": paths, "components": {"schemas": _BODIES}}


class _Upstream:
    def __init__(self, routes: dict[tuple[str, str], ControlResponse] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.missing: frozenset[str] = frozenset()

    async def openapi(self) -> dict[str, Any]:
        return _openapi(self.missing)

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "verified-token"}, {})
        return self.routes.get(
            (method, path), ControlResponse(404, {"error": {"code": "not_found"}}, {})
        )

    async def aclose(self) -> None:
        pass


def _ok(payload: object) -> ControlResponse:
    return ControlResponse(200, payload, {})


def _error(status: int, code: str, message: str = "") -> ControlResponse:
    return ControlResponse(status, {"error": {"code": code, "message": message}}, {})


def _console(
    tmp_path: Path, control: _Upstream, runtime: _Upstream, *, workload: bool = True
) -> FastAPI:
    settings = AdminConsoleSettings(
        session_store_directory=tmp_path / "sessions",
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        public_runtime_api_base_url="https://api.example.test",
        workload_authority_id=UUID(WORKLOAD_AUTHORITY) if workload else None,
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )
    return create_admin_console_app(settings, client=control, runtime_client=runtime)


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


_ONE_ORG = _ok(
    {
        "items": [
            {
                "organization_id": ORG,
                "display_name": "Barbería Central",
                "principal_id": PRINCIPAL,
                "membership_id": PRINCIPAL,
            }
        ],
        "next_after": None,
        "requires_owner_validation": True,
    }
)


@pytest.mark.asyncio
async def test_business_staff_land_in_their_business_with_business_only_navigation(
    tmp_path: Path,
) -> None:
    control = _Upstream(
        {
            ("GET", "/v1/platform/readiness"): _error(403, "capability_required"),
            ("GET", "/v1/platform/observability"): _error(403, "capability_required"),
        }
    )
    runtime = _Upstream({("GET", "/v1/me/organizations"): _ONE_ORG})
    async with _signed_in(_console(tmp_path, control, runtime)) as client:
        home = await client.get("/")
        assert home.status_code == 303
        assert home.headers["location"] == "/my-organizations?home=1"
        chosen = await client.get(home.headers["location"])
        assert chosen.status_code == 303
        assert chosen.headers["location"] == f"/tenants/{ORG}"
        page = await client.get(f"/tenants/{ORG}/approvals")
    # The rail now offers the business and hides platform administration.
    assert f'href="/tenants/{ORG}/today"' in page.text
    assert f'href="/tenants/{ORG}/agents"' in page.text
    assert "Barbería Central" in page.text
    assert 'href="/resources/owners"' not in page.text
    assert 'id="global-search"' not in page.text
    # Discovery never attached a tenant header or a browser identity.
    discovery = [call for call in runtime.calls if call[1] == "/v1/me/organizations"]
    assert "extra_headers" not in discovery[0][2] or not discovery[0][2]["extra_headers"]


@pytest.mark.asyncio
async def test_platform_owner_keeps_platform_navigation(tmp_path: Path) -> None:
    control = _Upstream(
        {
            ("GET", "/v1/platform/readiness"): _ok({"overall_state": "healthy"}),
            ("GET", "/v1/platform/observability"): _ok({"alerts": []}),
        }
    )
    async with _signed_in(_console(tmp_path, control, _Upstream())) as client:
        page = await client.get("/")
    assert page.status_code == 200
    assert 'href="/resources/owners"' in page.text
    assert page.text.count(">Account security<") == 1


@pytest.mark.asyncio
async def test_business_home_shows_setup_team_and_chief_of_staff_invitation(
    tmp_path: Path,
) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/business"): _ok({"display_name": "Barbería Central", "locations": []}),
            ("GET", "/v1/onboarding/readiness"): _ok(
                {
                    "locations": {"status": "ready", "ready": True, "blockers": []},
                    "walk_in_queue": {
                        "status": "blocked",
                        "ready": False,
                        "blockers": [{"resolution_hint": "Create an active service queue."}],
                    },
                }
            ),
            ("GET", "/v1/staff/overview"): _ok(
                {"total": 3, "active": 2, "invited": 1, "suspended": 0, "revoked": 0}
            ),
            ("GET", "/v1/agents"): _ok({"items": [], "next_after": None}),
            ("GET", "/v1/staff/invitation-proposals"): _ok({"items": []}),
        }
    )
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        page = await client.get(f"/tenants/{ORG}")
    assert page.status_code == 200
    assert "1 de 2 áreas listas" in page.text
    # Owner-facing guidance replaces the integration-facing API hint.
    assert "Cree una fila de espera para los pacientes que llegan sin cita." in page.text
    assert "Create an active service queue." not in page.text
    assert f'href="/tenants/{ORG}/agents/new?template=chief-of-staff"' in page.text
    reads = {call[1]: call[2] for call in runtime.calls if call[0] == "GET"}
    assert reads["/v1/business"]["extra_headers"]["X-RE-Organization-ID"] == ORG


@pytest.mark.asyncio
async def test_business_home_reports_chief_of_staff_suggestions(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/business"): _ok({"display_name": "Barbería Central"}),
            ("GET", "/v1/onboarding/readiness"): _error(503, "unavailable"),
            ("GET", "/v1/staff/overview"): _error(403, "capability_required"),
            ("GET", "/v1/agents"): _ok(
                {
                    "items": [
                        {
                            "principal_id": AGENT,
                            "display_name": "Chief of Staff",
                            "purpose": "Chief of staff: carries out what the owner asks.",
                            "status": "active",
                            "standing_capabilities": ["parties.lookup"],
                        }
                    ]
                }
            ),
            ("GET", "/v1/staff/invitation-proposals"): _ok(
                {"items": [{"proposal_id": PROPOSAL}, {"proposal_id": ENTRY}]}
            ),
        }
    )
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        page = await client.get(f"/tenants/{ORG}")
    assert "2 sugerencias esperan su aprobación." in page.text
    assert f'href="/tenants/{ORG}/agents/{AGENT}"' in page.text
    # A failed read is never shown as ready or as an empty team.
    assert "No se pudo revisar el avance de la configuración" in page.text
    assert "Usted no tiene acceso a la información del equipo." in page.text


@pytest.mark.asyncio
async def test_today_uses_business_time_and_reports_denied_queues_honestly(
    tmp_path: Path,
) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/business"): _ok(
                {
                    "display_name": "Barbería Central",
                    "default_timezone": None,
                    "locations": [{"timezone": "America/Santo_Domingo"}],
                }
            ),
            ("GET", "/v1/queues"): _error(403, "capability_required"),
            ("GET", "/v1/appointments/day-board"): _ok(
                [
                    {
                        "subject_display_name": "María Pérez",
                        "start_at": "2026-10-20T14:00:00Z",
                        "end_at": "2026-10-20T14:30:00Z",
                        "status": "confirmed",
                        "checked_in_at": "2026-10-20T13:55:00Z",
                    }
                ]
            ),
        }
    )
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/today")
    assert page.status_code == 200
    assert "hora de Santo Domingo" in page.text
    assert "Usted no tiene acceso a las filas de espera" in page.text
    # 14:00 UTC is 10:00 in Santo Domingo (UTC-4).
    assert "10:00–10:30" in page.text
    assert "María Pérez" in page.text
    board = next(call for call in runtime.calls if call[1] == "/v1/appointments/day-board")
    window = board[2]["params"]
    assert window["window_start"].endswith("+00:00") and window["window_end"].endswith("+00:00")


@pytest.mark.asyncio
async def test_today_actions_execute_owner_commands_with_stable_intent(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/business"): _ok({"display_name": "Barbería Central", "locations": []}),
            ("GET", "/v1/queues"): _ok([{"id": QUEUE, "display_name": "Walk-ins", "active": True}]),
            ("GET", f"/v1/queues/{QUEUE}/staff"): _ok(
                [
                    {
                        "queue_entry_id": ENTRY,
                        "subject_display_name": "Luis Rojas",
                        "status": "waiting",
                        "admitted_at": "2026-10-20T13:00:00Z",
                        "queue_revision": 4,
                    }
                ]
            ),
            ("GET", "/v1/appointments/day-board"): _ok([]),
            ("POST", f"/v1/queue-entries/{ENTRY}/no-show"): _ok({"status": "no_show"}),
            ("POST", f"/v1/queues/{QUEUE}/call-next"): _error(409, "queue_empty", "Nobody waits"),
        }
    )
    app = _console(tmp_path, _Upstream(), runtime)
    async with _signed_in(app) as client:
        today = await client.get(f"/tenants/{ORG}/today")
        assert "Luis Rojas" in today.text
        csrf = _csrf(today.text)
        done = await client.post(
            f"/tenants/{ORG}/today/entries/{ENTRY}/no-show",
            data={
                "csrf_token": csrf,
                "_intent_id": "intent-no-show-0001",
                "expected_revision": "4",
            },
        )
        assert done.status_code == 303
        assert done.headers["location"] == f"/tenants/{ORG}/today?done=no_show"
        failed = await client.post(
            f"/tenants/{ORG}/today/queues/{QUEUE}/call-next",
            data={"csrf_token": csrf, "_intent_id": "intent-call-next-01"},
        )
        forged = await client.post(
            f"/tenants/{ORG}/today/queues/{QUEUE}/call-next",
            data={"csrf_token": "wrong", "_intent_id": "intent-call-next-02"},
        )
    no_show = next(call for call in runtime.calls if call[1].endswith("/no-show"))
    assert no_show[2]["json_body"] == {"expected_revision": 4}
    assert no_show[2]["extra_headers"]["idempotency-key"] == "intent-no-show-0001"
    assert no_show[2]["extra_headers"]["X-RE-Organization-ID"] == ORG
    assert failed.status_code == 409
    assert "Nobody waits" in failed.text
    # A forged form never reaches the owner API.
    assert forged.status_code == 303
    assert sum(1 for call in runtime.calls if call[1].endswith("/call-next")) == 1


def _agent_routes() -> dict[tuple[str, str], ControlResponse]:
    return {
        ("GET", "/v1/staff/overview"): _ok(
            {
                "total": 1,
                "active": 1,
                "invited": 0,
                "suspended": 0,
                "revoked": 0,
                "effective_capabilities": [],
                "delegable_ceiling": [
                    "appointments.book",
                    "parties.lookup",
                    "staff.invite",
                    "queue.call_next",
                    "requests.create_definition",
                ],
            }
        ),
        ("GET", "/v1/me/authority"): _ok({"principal_id": PRINCIPAL}),
        ("POST", "/v1/agents"): ControlResponse(
            201,
            {
                "principal_id": AGENT,
                "profile_revision": 1,
                "authority_revision": 1,
                "workload_token": "cred.one-time-secret-value",
            },
            {},
        ),
        ("PUT", f"/v1/agents/{AGENT}/status"): _ok({"status": "active"}),
        ("GET", f"/v1/agents/{AGENT}"): _ok({"principal_id": AGENT, "authority_revision": 2}),
        ("PUT", f"/v1/agents/{AGENT}/authority"): _ok({"authority_revision": 3}),
        ("PUT", f"/v1/agents/{AGENT}/policy"): _ok({"policy_revision": 1}),
    }


@pytest.mark.asyncio
async def test_chief_of_staff_setup_runs_owner_steps_and_reveals_key_once(
    tmp_path: Path,
) -> None:
    runtime = _Upstream(_agent_routes())
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        form = await client.get(f"/tenants/{ORG}/agents/new?template=chief-of-staff")
        assert form.status_code == 200
        # Only capabilities an agent may ever use are offered.
        assert 'value="appointments.book" checked' in form.text
        assert 'value="parties.lookup" checked' in form.text
        assert 'value="staff.invite"' not in form.text
        assert 'value="queue.call_next"' not in form.text
        assert 'value="requests.create_definition" checked' not in form.text
        assert 'name="identity_authority_id"' not in form.text
        csrf = _csrf(form.text)
        created = await client.post(
            f"/tenants/{ORG}/agents",
            data={
                "csrf_token": csrf,
                "intent": "chief-intent-0000000001",
                "template": "chief-of-staff",
                "display_name": "Chief of Staff",
                "purpose": "Chief of staff: carries out what the owner asks.",
                "operating_mode": "assisted",
                "capabilities": ["appointments.book", "parties.lookup", "staff.invite"],
                "risk_ceiling": "external_commitment",
                "max_mutations_per_minute": "30",
                "expires_days": "90",
            },
        )
        listing = await client.get(f"/tenants/{ORG}/agents")
    assert created.status_code == 200
    assert "cred.one-time-secret-value" in created.text
    assert created.headers["referrer-policy"] == "no-referrer"
    assert created.headers["cache-control"] == "no-store"
    assert f"https://api.example.test/mcp/organizations/{ORG}" in created.text
    assert "cred.one-time-secret-value" not in listing.text
    writes = [(call[0], call[1], call[2]) for call in runtime.calls if call[0] in {"POST", "PUT"}]
    assert [(method, path) for method, path, _ in writes] == [
        ("POST", "/v1/agents"),
        ("PUT", f"/v1/agents/{AGENT}/status"),
        ("PUT", f"/v1/agents/{AGENT}/authority"),
        ("PUT", f"/v1/agents/{AGENT}/policy"),
    ]
    keys = [kwargs["extra_headers"]["Idempotency-Key"] for _, _, kwargs in writes]
    assert keys == [
        f"chief-intent-0000000001:{step}"
        for step in ("provision", "activate", "authority", "policy")
    ]
    provision = writes[0][2]["json_body"]
    assert provision["identity_authority_id"] == WORKLOAD_AUTHORITY
    assert provision["sponsor_principal_id"] == PRINCIPAL
    assert provision["operating_mode"] == "assisted"
    # A submitted authority-change capability is dropped before the owner call.
    assert writes[2][2]["json_body"]["desired_capabilities"] == [
        "appointments.book",
        "parties.lookup",
    ]
    assert writes[2][2]["json_body"]["expected_authority_revision"] == 2
    assert writes[3][2]["json_body"]["risk_ceiling"] == "external_commitment"


@pytest.mark.asyncio
async def test_agent_setup_asks_for_confirmation_and_stops_without_side_effects(
    tmp_path: Path,
) -> None:
    routes = _agent_routes()
    routes[("POST", "/v1/agents")] = _error(403, "recent_authentication_required", "Confirm")
    runtime = _Upstream(routes)
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        form = await client.get(f"/tenants/{ORG}/agents/new?template=chief-of-staff")
        page = await client.post(
            f"/tenants/{ORG}/agents",
            data={
                "csrf_token": _csrf(form.text),
                "intent": "chief-intent-0000000002",
                "template": "chief-of-staff",
                "display_name": "Chief of Staff",
                "purpose": "Chief of staff: carries out what the owner asks.",
                "operating_mode": "assisted",
                "capabilities": ["parties.lookup"],
                "risk_ceiling": "read",
                "max_mutations_per_minute": "30",
                "expires_days": "90",
            },
        )
    assert page.status_code == 422
    assert 'data-retry-form="agent-retry"' in page.text
    assert 'name="intent" value="chief-intent-0000000002"' in page.text
    assert [call[1] for call in runtime.calls if call[0] in {"POST", "PUT"}] == ["/v1/agents"]


@pytest.mark.asyncio
async def test_agent_setup_without_configured_authority_asks_for_it(tmp_path: Path) -> None:
    runtime = _Upstream(_agent_routes())
    app = _console(tmp_path, _Upstream(), runtime, workload=False)
    async with _signed_in(app) as client:
        form = await client.get(f"/tenants/{ORG}/agents/new")
        rejected = await client.post(
            f"/tenants/{ORG}/agents",
            data={
                "csrf_token": _csrf(form.text),
                "intent": "custom-intent-00000001",
                "display_name": "Bot",
                "purpose": "Answers customers",
                "operating_mode": "autonomous",
                "capabilities": ["parties.lookup"],
                "risk_ceiling": "read",
                "max_mutations_per_minute": "10",
                "expires_days": "30",
            },
        )
    assert 'name="identity_authority_id"' in form.text
    assert rejected.status_code == 422
    assert "autoridad de identidad de servicio" in rejected.text
    assert not [call for call in runtime.calls if call[0] in {"POST", "PUT"}]


@pytest.mark.asyncio
async def test_approvals_list_and_approve_exact_revision(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/staff/invitation-proposals"): _ok(
                {
                    "items": [
                        {
                            "proposal_id": PROPOSAL,
                            "email": "pedro@example.test",
                            "display_name": "Pedro Gómez",
                            "note": "New barber starting Monday",
                            "proposer_kind": "agent",
                            "proposer_display_name": "Chief of Staff",
                            "status": "pending",
                            "revision": 3,
                            "created_at": "2026-10-20T12:00:00Z",
                        }
                    ]
                }
            ),
            ("POST", f"/v1/staff/invitation-proposals/{PROPOSAL}:approve"): _ok({}),
        }
    )
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/approvals")
        approved = await client.post(
            f"/tenants/{ORG}/approvals/{PROPOSAL}/approve",
            data={
                "csrf_token": _csrf(page.text),
                "intent": "approve-intent-000001",
                "expected_revision": "3",
            },
        )
    assert "Invitar a Pedro Gómez (pedro@example.test)" in page.text
    assert "Sugerido por Chief of Staff" in page.text
    assert approved.status_code == 303
    call = next(call for call in runtime.calls if call[0] == "POST" and "approve" in call[1])
    assert call[2]["json_body"]["expected_revision"] == 3
    assert call[2]["extra_headers"]["Idempotency-Key"] == "approve-intent-000001:approve"


@pytest.mark.asyncio
async def test_approvals_degrade_when_the_installation_lacks_proposals(tmp_path: Path) -> None:
    runtime = _Upstream()
    runtime.missing = frozenset(
        {"staff_invitation_proposal_list", "staff_invitation_proposal_approve"}
    )
    async with _signed_in(_console(tmp_path, _Upstream(), runtime)) as client:
        page = await client.get(f"/tenants/{ORG}/approvals")
    assert page.status_code == 200
    assert "Las aprobaciones todavía no están disponibles en esta instalación" in page.text


@pytest.mark.asyncio
async def test_security_headers_allow_self_fonts_and_same_origin_referrer(tmp_path: Path) -> None:
    async with _signed_in(_console(tmp_path, _Upstream(), _Upstream())) as client:
        page = await client.get("/login")
    assert "font-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "same-origin"


def test_capability_labels_are_plain_language_and_never_hide_unknown_keys() -> None:
    assert capability_label("staff.manage_authority").label == "Cambiar permisos del equipo"
    unknown = capability_label("future.capability_key")
    assert unknown.group == "Otros" and unknown.key == "future.capability_key"
    groups = dict(grouped_capabilities(["parties.lookup", "appointments.book", "future.x"]))
    assert [item.key for item in groups["Citas"]] == ["appointments.book"]
    assert [item.key for item in groups["Otros"]] == ["future.x"]
