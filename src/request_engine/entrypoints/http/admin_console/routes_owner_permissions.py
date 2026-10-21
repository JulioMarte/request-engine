"""Owner permission upgrade: a plain page over controller policy adoption.

The owner asks for the newest owner permissions; a platform administrator
approves it in the platform console. The page reads the owner's own current
authority revision instead of asking the person for internal numbers. It
projects the existing owner operations only: the adoption command decides
eligibility, the target policy and whether anything newer exists, so the page
never claims the business is up to date on its own.
"""

from __future__ import annotations

import asyncio
import json
from secrets import token_urlsafe
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.execution import (
    ExecutionOutcome,
    execute_operation,
)
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    FrontDeskPost,
    front_desk_post,
    runtime_operations,
    runtime_read,
    workspace_unavailable,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

OWNER_PERMISSION_OPERATION_IDS = (
    "authority_read_self",
    "controller_policy_adoption_request_create",
    "controller_policy_adoption_request_get",
)
_CREATE = "controller_policy_adoption_request_create"
_DEFAULT_REASON = "Use the latest owner permissions for this business."
# The owner's refusal, said as what it means for the person and what to do next.
_REFUSALS = {
    "controller_policy_adoption_conflict": (
        "Nothing new to request right now. Your business already has the newest owner "
        "permissions, or a request is already waiting for approval."
    ),
    "controller_policy_adoption_forbidden": "Only the business owner can request this.",
    "controller_policy_adoption_consent_invalidated": (
        "Your account was recovered after this request started. Request it again."
    ),
}


def permissions_path(organization_id: UUID | str) -> str:
    return f"/tenants/{organization_id}/permissions-update"


def _requested_id(outcome: ExecutionOutcome) -> str | None:
    try:
        payload = json.loads(outcome.payload_json)
    except ValueError:
        return None
    try:
        return str(UUID(str(as_mapping(payload).get("request_id"))))
    except ValueError:
        return None


def _refusal(outcome: ExecutionOutcome) -> str:
    if outcome.needs_step_up:
        return "Sign in again to confirm it's you, then request the upgrade."
    return _REFUSALS.get(outcome.error_code) or (
        outcome.message or "The request was not sent. Reload the page and try again."
    )


def install_owner_permission_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def render(
        request: Request, organization_id: UUID, *, requested: str = "", refusal: str = ""
    ) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(
                f"/login?next={permissions_path(organization_id)}", status_code=303
            )
        if state.runtime is None:
            return workspace_unavailable(state, request, "Permissions unavailable")
        org = str(organization_id)
        ops = await runtime_operations(state, OWNER_PERMISSION_OPERATION_IDS)
        try:
            request_id = str(UUID(requested)) if requested else ""
        except ValueError:
            request_id = ""
        authority_read = runtime_read(
            state,
            ops["authority_read_self"],
            organization_id=org,
            bearer=session.access_token,
            params={"limit": "1"},
        )
        if request_id:
            authority, pending = await asyncio.gather(
                authority_read,
                runtime_read(
                    state,
                    ops["controller_policy_adoption_request_get"],
                    organization_id=org,
                    bearer=session.access_token,
                    path_values={"request_id": request_id},
                ),
            )
        else:
            authority, pending = await authority_read, None
        revision = as_mapping(authority.payload).get("authority_revision")
        return state.templates.TemplateResponse(
            request,
            "resources/owner_permissions.html",
            state.context(
                request,
                organization_id=org,
                authority_revision=str(revision) if isinstance(revision, int) else "",
                pending=as_mapping(pending.payload) if pending and pending.ok else None,
                refusal=refusal,
                reason=_DEFAULT_REASON,
                intent_id=token_urlsafe(16),
                can_request=ops[_CREATE] is not None,
            ),
            status_code=409 if refusal else 200,
        )

    async def page(request: Request, organization_id: UUID, requested: str = "") -> Response:
        return await render(request, organization_id, requested=requested)

    async def request_upgrade(request: Request, organization_id: UUID) -> Response:
        post = await front_desk_post(state, request, organization_id)
        if not isinstance(post, FrontDeskPost):
            return post
        operation = (await runtime_operations(state, (_CREATE,)))[_CREATE]
        if operation is None:
            return Response("This action is not available on this installation", status_code=503)
        outcome = await execute_operation(
            state,
            operation,
            bearer=post.session.access_token,
            form={
                "expected_authority_revision": post.values.get("expected_authority_revision", ""),
                "reason": post.values.get("reason", ""),
                "_intent_id": post.values.get("_intent_id", ""),
            },
            surface="runtime",
            organization_id=str(organization_id),
        )
        request_id = _requested_id(outcome) if outcome.ok else None
        if request_id is None:
            return await render(
                request, organization_id, refusal=_refusal(outcome) if not outcome.ok else ""
            )
        return RedirectResponse(
            f"{permissions_path(organization_id)}?requested={request_id}", status_code=303
        )

    path = "/tenants/{organization_id}/permissions-update"
    app.add_api_route(path, page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(path, request_upgrade, methods=["POST"])
