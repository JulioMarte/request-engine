"""Tenant staff workspace projected from the canonical runtime API."""

import json
from secrets import token_urlsafe
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.execution import execute_operation
from request_engine.entrypoints.http.admin_console.inputs import build_inputs
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


def _read_error(status_code: int) -> str:
    if status_code == 401:
        return "Your session is no longer authorized. Sign in again."
    if status_code == 403:
        return "You do not have permission to view this staff resource."
    if status_code == 404:
        return "The requested staff resource was not found."
    if status_code == 503:
        return "The staff service is temporarily unavailable."
    return "Staff data is unavailable."


_OPS = {
    "overview": "staff_overview_get",
    "list": "staff_list",
    "get": "staff_get",
    "invite": "staff_invite",
    "plan": "staff_authority_plan",
    "authority": "staff_manage_authority",
    "status": "staff_manage_membership",
    "profile": "staff_profile_update",
    "history": "staff_history_list",
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
        trail: str = Query(default="", max_length=2048),
        status: Literal["", "invited", "active", "suspended", "revoked"] | None = None,
        search: str = Query(default="", max_length=100),
    ) -> Response:
        status = status or None
        search = search.strip()
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
        overview_op = catalog.by_id().get(_OPS["overview"])
        list_op = catalog.by_id().get(_OPS["list"])
        invite_op = catalog.by_id().get(_OPS["invite"])
        if overview_op is None or list_op is None or invite_op is None:
            return Response("Staff operation catalog incomplete", status_code=503)
        trail_parts = [part for part in trail.split(",") if part]
        if len(trail_parts) > 100:
            return Response("Pagination trail is too long", status_code=422)
        try:
            for part in trail_parts:
                if part != "root":
                    UUID(part)
        except ValueError:
            return Response("Pagination trail is invalid", status_code=422)
        previous_url = ""
        if after is not None and trail_parts:
            previous = trail_parts[-1]
            previous_trail = ",".join(trail_parts[:-1])
            previous_url = f"/tenants/{organization_id}/staff?limit={limit}"
            if status is not None:
                previous_url += f"&status={status}"
            if search:
                previous_url += f"&search={quote(search, safe='')}"
            if previous != "root":
                previous_url += f"&after={previous}"
            if previous_trail:
                previous_url += f"&trail={previous_trail}"
        next_trail = ",".join([*trail_parts, "root" if after is None else str(after)])
        params: dict[str, str] = {"limit": str(limit)}
        if after is not None:
            params["after"] = str(after)
        if status is not None:
            params["status"] = status
        if search:
            params["search"] = search
        try:
            overview_response = await state.runtime_request(
                overview_op.method,
                overview_op.path_template,
                organization_id=str(organization_id),
                bearer=session.access_token,
            )
            list_response = await state.runtime_request(
                list_op.method,
                list_op.path_template,
                organization_id=str(organization_id),
                bearer=session.access_token,
                params=params,
            )
        except httpx.HTTPError:
            return Response("Staff service temporarily unavailable", status_code=503)
        reads_ok = overview_response.ok and list_response.ok
        body = as_mapping(list_response.payload) if list_response.ok else {}
        items = [as_mapping(item) for item in as_list(body.get("items"))] if reads_ok else []
        failed_status = (
            overview_response.status_code if not overview_response.ok else list_response.status_code
        )
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
                selected_status=status or "",
                selected_search=search,
                previous_url=previous_url,
                next_trail=next_trail,
                error="" if reads_ok else _read_error(failed_status),
                can_mutate=reads_ok,
                invite_inputs=build_inputs(invite_op) if reads_ok else [],
                invite_intent_id=token_urlsafe(24) if reads_ok else "",
            ),
            status_code=200 if reads_ok else failed_status,
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
        get_op = catalog.by_id().get(_OPS["get"])
        if get_op is None:
            return Response("Staff operation unavailable", status_code=503)
        try:
            response = await state.runtime_request(
                get_op.method,
                get_op.path_template.replace("{membership_id}", str(membership_id)),
                organization_id=str(organization_id),
                bearer=session.access_token,
            )
        except httpx.HTTPError:
            return Response("Staff service temporarily unavailable", status_code=503)
        item = as_mapping(response.payload)
        operations: dict[str, Any] = {}
        permission_choices: list[str] = []
        selected_permissions: list[str] = []
        if response.ok:
            overview_op = catalog.by_id().get(_OPS["overview"])
            if overview_op is None:
                return Response("Staff operation catalog incomplete", status_code=503)
            try:
                overview = await state.runtime_request(
                    overview_op.method,
                    overview_op.path_template,
                    organization_id=str(organization_id),
                    bearer=session.access_token,
                )
            except httpx.HTTPError:
                return Response("Staff service temporarily unavailable", status_code=503)
            if not overview.ok:
                return Response(_read_error(overview.status_code), status_code=overview.status_code)
            permission_choices = sorted(
                str(value)
                for value in as_list(as_mapping(overview.payload).get("delegable_ceiling"))
            )
            visible_capabilities = [
                str(grant.get("capability"))
                for grant in (as_mapping(value) for value in as_list(item.get("standing_grants")))
                if grant.get("capability")
            ]
            selected_permissions = sorted(set(visible_capabilities) & set(permission_choices))
            authority_draft = json.dumps(selected_permissions)
            for key in ("plan", "authority", "status"):
                operation = catalog.by_id().get(_OPS[key])
                if operation is None:
                    return Response("Staff operation catalog incomplete", status_code=503)
                operations[key] = {
                    "operation": operation,
                    "inputs": build_inputs(
                        catalog.by_id().get(_OPS["authority"], operation)
                        if key == "plan"
                        else operation,
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
            profile_op = catalog.by_id().get(_OPS["profile"])
            if profile_op is not None:
                operations["profile"] = {
                    "inputs": build_inputs(
                        profile_op,
                        values={
                            "membership_id": str(membership_id),
                            "expected_profile_revision": str(item.get("profile_revision", 0)),
                            "display_name": str(item.get("display_name") or ""),
                        },
                    ),
                    "url": f"/tenants/{organization_id}/staff/{membership_id}/profile",
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
                error="" if response.ok else _read_error(response.status_code),
                operations=operations,
                permission_choices=permission_choices,
                selected_permissions=selected_permissions,
            ),
            status_code=200 if response.ok else response.status_code,
        )

    async def history(
        request: Request,
        organization_id: UUID,
        membership_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        if state.runtime is None:
            return Response("Runtime API unavailable", status_code=503)
        try:
            catalog = await state.runtime_catalog()
        except Exception:
            return Response("Staff operation catalog unavailable", status_code=503)
        operation = catalog.by_id().get(_OPS["history"])
        if operation is None:
            return Response("Staff history operation unavailable", status_code=503)
        params = {"limit": str(limit)}
        if after is not None:
            params["after"] = str(after)
        try:
            response = await state.runtime_request(
                operation.method,
                operation.path_template.replace("{membership_id}", str(membership_id)),
                organization_id=str(organization_id),
                bearer=session.access_token,
                params=params,
            )
        except httpx.HTTPError:
            return Response("Staff service temporarily unavailable", status_code=503)
        body = as_mapping(response.payload) if response.ok else {}
        return state.templates.TemplateResponse(
            request,
            "resources/staff_history.html",
            state.context(
                request,
                organization_id=str(organization_id),
                membership_id=str(membership_id),
                entries=[as_mapping(item) for item in as_list(body.get("items"))],
                next_cursor=body.get("next_cursor"),
                page_limit=limit,
                after=after,
                error=(
                    "History cursor is invalid. Return to the newest events."
                    if response.status_code == 422
                    else ""
                    if response.ok
                    else _read_error(response.status_code)
                ),
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
        allowed_actions = (
            {"invite"} if membership_id is None else {"plan", "authority", "status", "profile"}
        )
        if action not in allowed_actions:
            return Response("Unknown staff action", status_code=404)
        submitted = await request.form()
        form = {key: str(value) for key, value in submitted.items()}
        if action == "plan" and form.get("_permission_picker") == "1":
            form["desired_capabilities"] = json.dumps(
                sorted({str(value) for value in submitted.getlist("selected_capabilities")})
            )
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        try:
            catalog = await state.runtime_catalog()
        except Exception:
            return Response("Staff operation catalog unavailable", status_code=503)
        operation = catalog.by_id().get(_OPS[action])
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
            payload = as_mapping(json.loads(outcome.payload_json))
            view["authority_plan"] = payload
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
        if outcome.ok and action in {"invite", "authority", "status", "profile"}:
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
            state.context(
                request,
                result=outcome.to_view(),
                form_id="staff-authority-reviewed" if action == "authority" else f"staff-{action}",
            ),
        )

    app.add_api_route("/tenants/{organization_id}/staff", workspace, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/staff", run, methods=["POST"])
    app.add_api_route("/tenants/{organization_id}/staff/{membership_id}", detail, methods=["GET"])
    app.add_api_route(
        "/tenants/{organization_id}/staff/{membership_id}/history", history, methods=["GET"]
    )
    app.add_api_route(
        "/tenants/{organization_id}/staff/{membership_id}/{action}", run, methods=["POST"]
    )
