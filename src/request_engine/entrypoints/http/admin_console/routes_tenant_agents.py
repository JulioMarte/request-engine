"""Agents and API access for a business, projected from the owner agent operations.

Creating an agent is the owner's documented sequence, executed step by step
through the canonical runtime operations (provision -> activate -> authority ->
policy). Each step carries its own Idempotency-Key derived from one form
intent, so resubmitting the same form safely replays finished steps and
continues the rest. The one-time key is shown only in the response that
created or rotated it; it is never stored by the console.

Which capabilities are offered to an agent is read from the canonical
capability registry (operational plane, classified risk). This only filters
the form; the owner API still decides every grant and denies anything else.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    CHIEF_OF_STAFF_PURPOSE_PREFIX,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.operation_risk import OperationRiskClass

_STEP_UP_CODES = frozenset({"recent_authentication_required", "phishing_resistant_auth_required"})
_RISK_CHOICES: tuple[tuple[str, str], ...] = (
    ("read", "Only look things up"),
    ("low_impact_write", "Small changes, such as registering customers and check-ins"),
    ("reversible_write", "Changes that can be undone, such as rescheduling"),
    ("external_commitment", "Commitments to customers, such as booking appointments"),
)
_RISK_VALUES = frozenset(value for value, _ in _RISK_CHOICES)
_EXPIRY_CHOICES = (30, 90, 180, 365)
# Responses that may contain a one-time agent key.
_SECRET_PAGE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
CHIEF_OF_STAFF_PURPOSE = (
    f"{CHIEF_OF_STAFF_PURPOSE_PREFIX}: carries out what the business owner asks by text or voice "
    "from Claude. Books and manages appointments, finds and registers customers, checks people "
    "in, answers questions about today, and suggests new team members for owner approval."
)
# Setup powers a chief of staff does not get unless the owner ticks them.
_CHIEF_OPT_IN = frozenset(
    {
        "requests.create_definition",
        "requests.publish_definition_version",
        "requests.set_definition_active",
    }
)
_AGENT_OPS = (
    "authority_read_self",
    "staff_overview_get",
    "agent_list",
    "agent_get",
    "agent_provision",
    "agent_suspend",
    "agent_manage_authority",
    "agent_policy_read",
    "agent_policy_replace",
    "agent_credential_rotate",
)


def agent_usable(key: str) -> bool:
    """True when the registry says an agent may ever hold and use this capability."""

    definition = capability_definition(key)
    if definition is None or definition.authority_plane is not AuthorityPlane.OPERATIONAL:
        return False
    risk = definition.effective_risk_class
    return risk is not None and risk is not OperationRiskClass.AUTHORITY_CHANGE


def agent_risk(key: str) -> str | None:
    definition = capability_definition(key)
    risk = definition.effective_risk_class if definition is not None else None
    return risk.value if risk is not None else None


@dataclass
class _Step:
    name: str
    label: str
    status: str = "pending"  # pending | done | failed
    message: str = ""


def _connection(state: AdminConsoleState, organization_id: str) -> dict[str, str]:
    base = (
        state.settings.public_runtime_api_base_url
        or state.settings.runtime_api_base_url
        or "https://your-request-engine.example"
    )
    mcp_url = f"{base}/mcp/organizations/{organization_id}"
    return {
        "api_base": base,
        "mcp_url": mcp_url,
        "claude_code": (
            f'claude mcp add --transport http request-engine "{mcp_url}" '
            '--header "Authorization: Bearer $REQUEST_ENGINE_AGENT_KEY"'
        ),
        "claude_desktop": json.dumps(
            {
                "mcpServers": {
                    "request-engine": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote",
                            mcp_url,
                            "--header",
                            "Authorization:${AUTH_HEADER}",
                        ],
                        "env": {"AUTH_HEADER": "Bearer paste-the-agent-key-here"},
                    }
                }
            },
            indent=2,
        ),
        "curl": (
            f'curl -H "Authorization: Bearer $REQUEST_ENGINE_AGENT_KEY" '
            f'-H "X-RE-Organization-ID: {organization_id}" {base}/v1/operation-catalog'
        ),
    }


def install_tenant_agent_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _ops() -> dict[str, AdminOperation | None]:
        catalog = (await state.runtime_catalog()).by_id()
        return {name: catalog.get(name) for name in _AGENT_OPS}

    async def _call(
        operation: AdminOperation | None,
        *,
        organization_id: str,
        bearer: str,
        path_values: Mapping[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: object | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, Any, str]:
        if operation is None:
            return 503, None, "operation_unavailable"
        path = operation.path_template
        for name, value in (path_values or {}).items():
            path = path.replace("{" + name + "}", quote(value, safe=""))
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        try:
            response = await state.runtime_request(
                operation.method.upper(),
                path,
                organization_id=organization_id,
                bearer=bearer,
                json_body=body,
                params=params,
                extra_headers=headers,
            )
        except (httpx.HTTPError, RuntimeError):
            return 503, None, "outcome_unknown" if body is not None else "runtime_unreachable"
        return response.status_code, response.payload, response.error_code or ""

    def _signed_in(request: Request):  # noqa: ANN202
        session = state.session(request)
        return session if session is not None else login_redirect(request)

    def _unavailable(request: Request) -> Response:
        return state.templates.TemplateResponse(
            request,
            "unavailable.html",
            state.context(
                request,
                title="Agents unavailable",
                message="Configure the runtime API URL to manage agents for this business.",
            ),
            status_code=503,
        )

    async def listing(request: Request, organization_id: UUID) -> Response:
        session = _signed_in(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return _unavailable(request)
        org = str(organization_id)
        ops = await _ops()
        status, payload, _ = await _call(
            ops["agent_list"],
            organization_id=org,
            bearer=session.access_token,
            params={"limit": "100"},
        )
        if status == 401:
            response = login_redirect(request)
            state.clear_session(response, request)
            return response
        items = [dict(as_mapping(item)) for item in as_list(as_mapping(payload).get("items"))]
        for item in items:
            item["chief"] = str(item.get("purpose") or "").startswith(CHIEF_OF_STAFF_PURPOSE_PREFIX)
        return state.templates.TemplateResponse(
            request,
            "resources/agents.html",
            state.context(
                request,
                organization_id=org,
                agents=items if 200 <= status < 300 else None,
                agents_status=status,
                has_chief=any(item["chief"] and item.get("status") != "revoked" for item in items),
                connection=_connection(state, org),
            ),
        )

    async def _form_context(
        request: Request, organization_id: str, bearer: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        ops = await _ops()
        status, payload, _ = await _call(
            ops["staff_overview_get"], organization_id=organization_id, bearer=bearer
        )
        ceiling = [
            str(key)
            for key in as_list(as_mapping(payload).get("delegable_ceiling"))
            if isinstance(key, str)
        ]
        usable = sorted(key for key in ceiling if agent_usable(key))
        return {
            "organization_id": organization_id,
            "usable_capabilities": usable,
            "capability_risk": {key: agent_risk(key) for key in usable},
            "ceiling_status": status,
            "risk_choices": _RISK_CHOICES,
            "expiry_choices": _EXPIRY_CHOICES,
            "values": values,
            "needs_authority_field": state.settings.workload_authority_id is None,
        }

    async def new_agent(request: Request, organization_id: UUID, template: str = "") -> Response:
        session = _signed_in(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return _unavailable(request)
        org = str(organization_id)
        chief = template == "chief-of-staff"
        context = await _form_context(request, org, session.access_token, {})
        selected = (
            [key for key in context["usable_capabilities"] if key not in _CHIEF_OPT_IN]
            if chief
            else [
                key
                for key in context["usable_capabilities"]
                if context["capability_risk"][key] == "read"
            ]
        )
        values = {
            "template": "chief-of-staff" if chief else "custom",
            "display_name": "Chief of Staff" if chief else "",
            "purpose": CHIEF_OF_STAFF_PURPOSE if chief else "",
            "operating_mode": "assisted" if chief else "autonomous",
            "capabilities": selected,
            "risk_ceiling": "external_commitment" if chief else "read",
            "max_mutations_per_minute": "30",
            "expires_days": "90",
            "intent": token_urlsafe(16),
        }
        context["values"] = values
        return state.templates.TemplateResponse(
            request, "resources/agent_new.html", state.context(request, **context)
        )

    async def create_agent(request: Request, organization_id: UUID) -> Response:
        session = _signed_in(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return _unavailable(request)
        org = str(organization_id)
        form = await request.form()
        values: dict[str, Any] = {key: str(value) for key, value in form.items()}
        values["capabilities"] = [str(value) for value in form.getlist("capabilities")]
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        context = await _form_context(request, org, session.access_token, values)
        errors: list[str] = []
        display_name = str(values.get("display_name", "")).strip()
        purpose = str(values.get("purpose", "")).strip()
        intent = str(values.get("intent", "")).strip()
        capabilities = [
            key for key in values["capabilities"] if key in context["usable_capabilities"]
        ]
        risk_ceiling = str(values.get("risk_ceiling", ""))
        try:
            max_per_minute = int(str(values.get("max_mutations_per_minute", "")))
            expires_days = int(str(values.get("expires_days", "")))
        except ValueError:
            max_per_minute, expires_days = 0, 0
        authority_id = (
            str(state.settings.workload_authority_id)
            if state.settings.workload_authority_id is not None
            else str(values.get("identity_authority_id", "")).strip()
        )
        if not 1 <= len(display_name) <= 200:
            errors.append("Give the agent a name of up to 200 characters.")
        if not 1 <= len(purpose) <= 2000:
            errors.append("Describe what the agent does in up to 2000 characters.")
        if not capabilities:
            errors.append("Choose at least one thing the agent may do.")
        if risk_ceiling not in _RISK_VALUES:
            errors.append("Choose how far the agent may go.")
        if not 1 <= max_per_minute <= 600:
            errors.append("Changes per minute must be between 1 and 600.")
        if expires_days not in _EXPIRY_CHOICES:
            errors.append("Choose when the agent key expires.")
        if values.get("operating_mode") not in {"assisted", "autonomous"}:
            errors.append("Choose how the agent works.")
        if len(intent) < 16 or len(intent) > 64:
            errors.append("This form expired. Reload the page and try again.")
        try:
            UUID(authority_id)
        except ValueError:
            errors.append("Enter the workload identity authority from the installation receipt.")
        if errors:
            return state.templates.TemplateResponse(
                request,
                "resources/agent_new.html",
                state.context(request, form_errors=errors, **context),
                status_code=422,
            )
        ops = await _ops()
        bearer = session.access_token
        steps = [
            _Step("provision", "Create the agent and its key"),
            _Step("activate", "Turn the agent on"),
            _Step("authority", "Give it the chosen permissions"),
            _Step("policy", "Set its safety limits"),
        ]
        token: str | None = None
        principal_id: str | None = None
        profile_revision = 1
        step_up = False

        def fail(step: _Step, code: str, payload: object) -> None:
            nonlocal step_up
            step.status = "failed"
            message = as_mapping(as_mapping(payload).get("error")).get("message")
            step.message = message if isinstance(message, str) else code or "The step failed."
            step_up = step_up or code in _STEP_UP_CODES

        provenance = f"admin-console:agent:{intent}"
        me_status, me, me_code = await _call(
            ops["authority_read_self"], organization_id=org, bearer=bearer
        )
        sponsor = as_mapping(me).get("principal_id")
        if not (200 <= me_status < 300 and isinstance(sponsor, str)):
            fail(steps[0], me_code or "authority_unavailable", me)
        else:
            expires = (datetime.now(UTC) + timedelta(days=expires_days)).isoformat()
            status, payload, code = await _call(
                ops["agent_provision"],
                organization_id=org,
                bearer=bearer,
                body={
                    "identity_authority_id": authority_id,
                    "display_name": display_name,
                    "purpose": purpose,
                    "sponsor_principal_id": sponsor,
                    "operating_mode": values["operating_mode"],
                    "credential_expires_at": expires,
                    "provenance_reference": provenance,
                },
                idempotency_key=f"{intent}:provision",
            )
            created = as_mapping(payload)
            if 200 <= status < 300 and isinstance(created.get("principal_id"), str):
                steps[0].status = "done"
                principal_id = str(created["principal_id"])
                if isinstance(created.get("profile_revision"), int):
                    profile_revision = int(created["profile_revision"])
                raw_token = created.get("workload_token")
                token = raw_token if isinstance(raw_token, str) else None
            else:
                fail(steps[0], code, payload)
        if principal_id is not None:
            path = {"agent_principal_id": principal_id}
            status, payload, code = await _call(
                ops["agent_suspend"],
                organization_id=org,
                bearer=bearer,
                path_values=path,
                body={
                    "expected_revision": profile_revision,
                    "target_status": "active",
                    "provenance_reference": provenance,
                },
                idempotency_key=f"{intent}:activate",
            )
            if 200 <= status < 300:
                steps[1].status = "done"
            else:
                fail(steps[1], code, payload)
            if steps[1].status == "done":
                read_status, current, read_code = await _call(
                    ops["agent_get"], organization_id=org, bearer=bearer, path_values=path
                )
                revision = as_mapping(current).get("authority_revision")
                if 200 <= read_status < 300 and isinstance(revision, int):
                    status, payload, code = await _call(
                        ops["agent_manage_authority"],
                        organization_id=org,
                        bearer=bearer,
                        path_values=path,
                        body={
                            "expected_authority_revision": revision,
                            "desired_capabilities": capabilities,
                            "provenance_reference": provenance,
                        },
                        idempotency_key=f"{intent}:authority",
                    )
                    if 200 <= status < 300:
                        steps[2].status = "done"
                    else:
                        fail(steps[2], code, payload)
                else:
                    fail(steps[2], read_code or "agent_unreadable", current)
            if steps[2].status == "done":
                status, payload, code = await _call(
                    ops["agent_policy_replace"],
                    organization_id=org,
                    bearer=bearer,
                    path_values=path,
                    body={
                        "allowed_capabilities": capabilities,
                        "denied_capabilities": [],
                        "risk_ceiling": risk_ceiling,
                        "max_mutations_per_minute": max_per_minute,
                        "provenance_reference": provenance,
                    },
                    idempotency_key=f"{intent}:policy",
                )
                if 200 <= status < 300:
                    steps[3].status = "done"
                else:
                    fail(steps[3], code, payload)
        complete = all(step.status == "done" for step in steps)
        return state.templates.TemplateResponse(
            request,
            "resources/agent_created.html",
            state.context(
                request,
                organization_id=org,
                steps=steps,
                complete=complete,
                token=token,
                principal_id=principal_id,
                display_name=display_name,
                step_up=step_up,
                retry_values=values,
                connection=_connection(state, org),
                is_chief=values.get("template") == "chief-of-staff",
            ),
            status_code=200 if complete else 409 if principal_id else 422,
            headers=_SECRET_PAGE_HEADERS,
        )

    async def detail(request: Request, organization_id: UUID, principal_id: UUID) -> Response:
        session = _signed_in(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return _unavailable(request)
        org = str(organization_id)
        ops = await _ops()
        path = {"agent_principal_id": str(principal_id)}
        (status, agent, _), (policy_status, policy, _) = (
            await _call(
                ops["agent_get"], organization_id=org, bearer=session.access_token, path_values=path
            ),
            await _call(
                ops["agent_policy_read"],
                organization_id=org,
                bearer=session.access_token,
                path_values=path,
            ),
        )
        if status == 401:
            response = login_redirect(request)
            state.clear_session(response, request)
            return response
        info = dict(as_mapping(agent)) if 200 <= status < 300 else None
        if info is not None:
            info["chief"] = str(info.get("purpose") or "").startswith(CHIEF_OF_STAFF_PURPOSE_PREFIX)
        return state.templates.TemplateResponse(
            request,
            "resources/agent_detail.html",
            state.context(
                request,
                organization_id=org,
                agent=info,
                agent_status=status,
                policy=as_mapping(policy) if 200 <= policy_status < 300 else None,
                policy_status=policy_status,
                connection=_connection(state, org),
                intent=token_urlsafe(16),
                expiry_choices=_EXPIRY_CHOICES,
            ),
            status_code=200 if info is not None else status if status >= 400 else 502,
        )

    async def _agent_action(
        request: Request, organization_id: UUID, principal_id: UUID, action: str
    ) -> Response:
        session = _signed_in(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return _unavailable(request)
        org = str(organization_id)
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        intent = values.get("intent", "")
        if not 16 <= len(intent) <= 64:
            return Response("This form expired. Reload the page.", status_code=422)
        ops = await _ops()
        path = {"agent_principal_id": str(principal_id)}
        provenance = f"admin-console:agent-{action}:{intent}"
        token: str | None = None
        try:
            if action == "rotate":
                days = int(values.get("expires_days", "90"))
                if days not in _EXPIRY_CHOICES:
                    raise ValueError
                body: dict[str, object] = {
                    "expected_authority_revision": int(values["expected_authority_revision"]),
                    "credential_expires_at": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
                    "provenance_reference": provenance,
                }
                operation = ops["agent_credential_rotate"]
            else:
                target = {"pause": "suspended", "resume": "active", "revoke": "revoked"}[action]
                body = {
                    "expected_revision": int(values["expected_revision"]),
                    "target_status": target,
                    "provenance_reference": provenance,
                }
                operation = ops["agent_suspend"]
        except (KeyError, ValueError):
            return Response(
                "The form is incomplete. Reload the agent and try again.", status_code=422
            )
        status, payload, code = await _call(
            operation,
            organization_id=org,
            bearer=session.access_token,
            path_values=path,
            body=body,
            idempotency_key=f"{intent}:{action}",
        )
        ok = 200 <= status < 300
        if ok and action == "rotate":
            raw = as_mapping(payload).get("workload_token")
            token = raw if isinstance(raw, str) else None
        if ok and action != "rotate":
            return RedirectResponse(
                f"/tenants/{org}/agents/{principal_id}?done={action}", status_code=303
            )
        message = as_mapping(as_mapping(payload).get("error")).get("message")
        return state.templates.TemplateResponse(
            request,
            "resources/agent_action.html",
            state.context(
                request,
                organization_id=org,
                principal_id=str(principal_id),
                ok=ok,
                action=action,
                token=token,
                status=status,
                error_code=code,
                message=message if isinstance(message, str) else "",
                step_up=code in _STEP_UP_CODES,
                retry_values=values,
                connection=_connection(state, org),
            ),
            status_code=200 if ok else status if status >= 400 else 502,
            headers=_SECRET_PAGE_HEADERS,
        )

    async def rotate(request: Request, organization_id: UUID, principal_id: UUID) -> Response:
        return await _agent_action(request, organization_id, principal_id, "rotate")

    async def change_status(
        request: Request, organization_id: UUID, principal_id: UUID, action: str
    ) -> Response:
        if action not in {"pause", "resume", "revoke"}:
            return Response(status_code=404)
        return await _agent_action(request, organization_id, principal_id, action)

    app.add_api_route("/tenants/{organization_id}/agents", listing, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/agents", create_agent, methods=["POST"])
    app.add_api_route("/tenants/{organization_id}/agents/new", new_agent, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/agents/{principal_id}", detail, methods=["GET"])
    app.add_api_route(
        "/tenants/{organization_id}/agents/{principal_id}/rotate", rotate, methods=["POST"]
    )
    app.add_api_route(
        "/tenants/{organization_id}/agents/{principal_id}/status/{action}",
        change_status,
        methods=["POST"],
    )


__all__ = [
    "CHIEF_OF_STAFF_PURPOSE",
    "agent_risk",
    "agent_usable",
    "install_tenant_agent_routes",
]
