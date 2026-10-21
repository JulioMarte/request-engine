"""Owner permission upgrade: a plain page over controller policy adoption.

The owner asks for the newest owner permissions; a platform administrator
approves it in the platform console. The page reads the owner's own current
authority revision and the onboarding readiness instead of asking the person
for internal numbers. It projects the existing owner operations only: the
adoption command decides eligibility, consent rules and the target policy.
"""

from __future__ import annotations

import asyncio
import json
from secrets import token_urlsafe
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.execution import ExecutionOutcome
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    front_desk_action,
    pick,
    runtime_operations,
    runtime_read,
    workspace_unavailable,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

OWNER_PERMISSION_OPERATION_IDS = (
    "authority_read_self",
    "onboarding_read",
    "controller_policy_adoption_request_create",
    "controller_policy_adoption_request_get",
)
_DEFAULT_REASON = "Use the latest owner permissions for this business."


def permissions_path(organization_id: UUID | str) -> str:
    return f"/tenants/{organization_id}/permissions-update"


def _requested_id(outcome: ExecutionOutcome) -> str | None:
    try:
        payload = json.loads(outcome.payload_json)
    except ValueError:
        return None
    request_id = as_mapping(payload).get("request_id")
    try:
        return str(UUID(str(request_id)))
    except ValueError:
        return None


def install_owner_permission_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def page(request: Request, organization_id: UUID, requested: str = "") -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(
                f"/login?next={permissions_path(organization_id)}", status_code=303
            )
        if state.runtime is None:
            return workspace_unavailable(state, request, "Permissions unavailable")
        org = str(organization_id)
        ops = await runtime_operations(state, OWNER_PERMISSION_OPERATION_IDS)
        reads = [
            runtime_read(
                state,
                ops["authority_read_self"],
                organization_id=org,
                bearer=session.access_token,
                params={"limit": "1"},
            ),
            runtime_read(
                state, ops["onboarding_read"], organization_id=org, bearer=session.access_token
            ),
        ]
        request_id = ""
        try:
            request_id = str(UUID(requested)) if requested else ""
        except ValueError:
            request_id = ""
        if request_id:
            reads.append(
                runtime_read(
                    state,
                    ops["controller_policy_adoption_request_get"],
                    organization_id=org,
                    bearer=session.access_token,
                    path_values={"request_id": request_id},
                )
            )
        results = await asyncio.gather(*reads)
        authority, readiness = results[0], results[1]
        pending = results[2] if request_id else None
        control = as_mapping(as_mapping(readiness.payload).get("tenant_control"))
        revision = as_mapping(authority.payload).get("authority_revision")
        return state.templates.TemplateResponse(
            request,
            "resources/owner_permissions.html",
            state.context(
                request,
                organization_id=org,
                readiness_ok=readiness.ok,
                up_to_date=control.get("status") == "ready",
                authority_revision=str(revision) if isinstance(revision, int) else "",
                authority_denied=authority.denied,
                request_id=request_id,
                pending=as_mapping(pending.payload) if pending and pending.ok else None,
                reason=_DEFAULT_REASON,
                intent_id=token_urlsafe(16),
                can_request=ops["controller_policy_adoption_request_create"] is not None,
            ),
        )

    async def request_upgrade(request: Request, organization_id: UUID) -> Response:
        def located(outcome: ExecutionOutcome) -> str | None:
            request_id = _requested_id(outcome)
            if request_id is None:
                return None
            return f"{permissions_path(organization_id)}?requested={request_id}"

        return await front_desk_action(
            state,
            request,
            organization_id,
            "controller_policy_adoption_request_create",
            pick("expected_authority_revision", "reason"),
            done="permissions_requested",
            back=permissions_path(organization_id),
            success_location=located,
        )

    path = "/tenants/{organization_id}/permissions-update"
    app.add_api_route(path, page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(path, request_upgrade, methods=["POST"])
