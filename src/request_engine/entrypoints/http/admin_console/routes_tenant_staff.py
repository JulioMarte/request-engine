"""Tenant staff workspace projected from the canonical runtime API."""

import json
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.execution import execute_operation
from request_engine.entrypoints.http.admin_console.inputs import build_inputs
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.resources import resolve_operation
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_OPS = {
    "overview": "staff_overview_get",
    "list": "staff_list",
    "get": "staff_get",
    "invite": "staff_invite",
    "plan": "staff_authority_plan",
    "authority": "staff_manage_authority",
    "status": "staff_manage_membership",
}


def install_tenant_staff_routes(app: FastAPI, state: AdminConsoleState) -> None:
    def session_or_redirect(request: Request):  # noqa: ANN202
        session = state.session(request)
        return session if session is not None else RedirectResponse("/login", status_code=303)

    async def workspace(
        request: Request,
        organization_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return state.templates.TemplateResponse(
                request,
                "unavailable.html",
                state.context(
                    request,
                    title="People workspace unavailable",
                    message="Configure the runtime API URL to manage this organization's staff.",
                ),
                status_code=503,
            )
        try:
            catalog = await state.runtime_catalog()
        except Exception:
            return Response("Staff operation catalog unavailable", status_code=503)
        overview_op = resolve_operation(catalog, _OPS["overview"])
        list_op = resolve_operation(catalog, _OPS["list"])
        invite_op = resolve_operation(catalog, _OPS["invite"])
        if overview_op is None or list_op is None or invite_op is None:
            return Response("Staff operation catalog incomplete", status_code=503)
        overview_response = await state.runtime_request(
            overview_op.method,
            overview_op.path_template,
            organization_id=str(organization_id),
            bearer=session.access_token,
        )
        params: dict[str, str] = {"limit": str(limit)}
        if after is not None:
            params["after"] = str(after)
        list_response = await state.runtime_request(
            list_op.method,
            list_op.path_template,
            organization_id=str(organization_id),
            bearer=session.access_token,
            params=params,
        )
        body = as_mapping(list_response.payload)
        items = [as_mapping(item) for item in as_list(body.get("items"))]
        return state.templates.TemplateResponse(
            request,
            "resources/staff.html",
            state.context(
                request,
                organization_id=str(organization_id),
                overview=as_mapping(overview_response.payload),
                members=items,
                next_cursor=body.get("next_cursor"),
                page_limit=str(limit),
                error=""
                if overview_response.ok and list_response.ok
                else "Staff data is unavailable or access was denied.",
                invite_inputs=build_inputs(invite_op),
                invite_intent_id=token_urlsafe(24),
            ),
        )

    async def detail(request: Request, organization_id: UUID, membership_id: UUID) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return Response("Runtime API unavailable", status_code=503)
        try:
            catalog = await state.runtime_catalog()
        except Exception:
            return Response("Staff operation catalog unavailable", status_code=503)
        get_op = resolve_operation(catalog, _OPS["get"])
        if get_op is None:
            return Response("Staff operation unavailable", status_code=503)
        response = await state.runtime_request(
            get_op.method,
            get_op.path_template.replace("{membership_id}", str(membership_id)),
            organization_id=str(organization_id),
            bearer=session.access_token,
        )
        item = as_mapping(response.payload)
        operations: dict[str, Any] = {}
        if response.ok:
            visible_capabilities = [
                str(grant.get("capability"))
                for grant in (as_mapping(value) for value in as_list(item.get("standing_grants")))
                if grant.get("capability")
            ]
            authority_draft = json.dumps(sorted(visible_capabilities))
            for key in ("plan", "authority", "status"):
                operation = resolve_operation(catalog, _OPS[key])
                if operation is None:
                    return Response("Staff operation catalog incomplete", status_code=503)
                operations[key] = {
                    "operation": operation,
                    "inputs": build_inputs(
                        operation,
                        values={
                            "membership_id": str(membership_id),
                            "expected_authority_revision": str(item.get("authority_revision", "")),
                            "expected_revision": str(item.get("membership_revision", "")),
                            "desired_capabilities": authority_draft,
                        },
                    ),
                    "url": f"/tenants/{organization_id}/staff/{membership_id}/{key}",
                    "intent_id": token_urlsafe(24),
                }
        return state.templates.TemplateResponse(
            request,
            "resources/staff_detail.html",
            state.context(
                request,
                organization_id=str(organization_id),
                membership_id=membership_id,
                member=item,
                error="" if response.ok else "Membership unavailable or access denied.",
                operations=operations,
            ),
            status_code=200 if response.ok else response.status_code,
        )

    async def run(
        request: Request,
        organization_id: UUID,
        membership_id: UUID | None = None,
        action: str = "invite",
    ) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return Response("Runtime API unavailable", status_code=503)
        allowed_actions = {"invite"} if membership_id is None else {"plan", "authority", "status"}
        if action not in allowed_actions:
            return Response("Unknown staff action", status_code=404)
        form = {key: str(value) for key, value in (await request.form()).items()}
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        try:
            catalog = await state.runtime_catalog()
        except Exception:
            return Response("Staff operation catalog unavailable", status_code=503)
        operation = resolve_operation(catalog, _OPS[action])
        if operation is None:
            return Response("Staff operation unavailable", status_code=503)
        if membership_id:
            form["membership_id"] = str(membership_id)
        outcome = await execute_operation(
            state,
            operation,
            bearer=session.access_token,
            form=form,
            surface="runtime",
            organization_id=str(organization_id),
        )
        if outcome.ok and action == "plan":
            view = outcome.to_view()
            payload = as_mapping(view.get("payload"))
            if payload.get("can_apply") is True:
                view["reviewed_draft"] = {
                    "desired_capabilities": form.get("desired_capabilities", ""),
                    "expected_authority_revision": form.get("expected_authority_revision", ""),
                    "provenance_reference": form.get("provenance_reference", ""),
                    "_intent_id": token_urlsafe(24),
                }
            return state.templates.TemplateResponse(
                request,
                "partials/result.html",
                state.context(request, result=view, form_id="staff-plan"),
            )
        if outcome.ok and action in {"invite", "authority", "status"}:
            location = (
                f"/tenants/{organization_id}/staff/{membership_id}"
                if membership_id is not None
                else f"/tenants/{organization_id}/staff"
            )
            if request.headers.get("HX-Request", "").lower() == "true":
                return Response(status_code=204, headers={"HX-Redirect": location})
            return RedirectResponse(location, status_code=303)
        return state.templates.TemplateResponse(
            request,
            "partials/result.html",
            state.context(request, result=outcome.to_view(), form_id=f"staff-{action}"),
        )

    app.add_api_route("/tenants/{organization_id}/staff", workspace, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/staff", run, methods=["POST"])
    app.add_api_route("/tenants/{organization_id}/staff/{membership_id}", detail, methods=["GET"])
    app.add_api_route(
        "/tenants/{organization_id}/staff/{membership_id}/{action}", run, methods=["POST"]
    )
