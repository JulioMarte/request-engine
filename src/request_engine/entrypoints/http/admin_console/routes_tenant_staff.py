"""Tenant staff workspace projected from the canonical runtime API."""

from typing import Any

from fastapi import FastAPI, Request
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

    async def workspace(request: Request, organization_id: str) -> Response:
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
        catalog = await state.runtime_catalog()
        overview_op = resolve_operation(catalog, _OPS["overview"])
        list_op = resolve_operation(catalog, _OPS["list"])
        invite_op = resolve_operation(catalog, _OPS["invite"])
        assert overview_op and list_op and invite_op
        overview_response = await state.runtime_request(
            overview_op.method,
            overview_op.path_template,
            organization_id=organization_id,
            bearer=session.access_token,
        )
        list_response = await state.runtime_request(
            list_op.method,
            list_op.path_template,
            organization_id=organization_id,
            bearer=session.access_token,
            params={"limit": request.query_params.get("limit", "50")},
        )
        body = as_mapping(list_response.payload)
        items = [as_mapping(item) for item in as_list(body.get("items"))]
        return state.templates.TemplateResponse(
            request,
            "resources/staff.html",
            state.context(
                request,
                organization_id=organization_id,
                overview=as_mapping(overview_response.payload),
                members=items,
                error=""
                if overview_response.ok and list_response.ok
                else "Staff data is unavailable or access was denied.",
                invite_inputs=build_inputs(invite_op),
            ),
        )

    async def detail(request: Request, organization_id: str, membership_id: str) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        catalog = await state.runtime_catalog()
        get_op = resolve_operation(catalog, _OPS["get"])
        assert get_op
        response = await state.runtime_request(
            get_op.method,
            get_op.path_template.replace("{membership_id}", membership_id),
            organization_id=organization_id,
            bearer=session.access_token,
        )
        item = as_mapping(response.payload)
        operations: dict[str, Any] = {}
        for key in ("plan", "authority", "status"):
            operation = resolve_operation(catalog, _OPS[key])
            assert operation is not None
            operations[key] = {
                "operation": operation,
                "inputs": build_inputs(
                    operation,
                    values={
                        "membership_id": membership_id,
                        "expected_authority_revision": str(item.get("authority_revision", "")),
                        "expected_revision": str(item.get("membership_revision", "")),
                    },
                ),
                "url": f"/tenants/{organization_id}/staff/{membership_id}/{key}",
            }
        return state.templates.TemplateResponse(
            request,
            "resources/staff_detail.html",
            state.context(
                request,
                organization_id=organization_id,
                membership_id=membership_id,
                member=item,
                error="" if response.ok else "Membership unavailable or access denied.",
                operations=operations,
            ),
        )

    async def run(
        request: Request,
        organization_id: str,
        membership_id: str | None = None,
        action: str = "invite",
    ) -> Response:
        session = session_or_redirect(request)
        if isinstance(session, RedirectResponse):
            return session
        form = {key: str(value) for key, value in (await request.form()).items()}
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        operation = resolve_operation(await state.runtime_catalog(), _OPS[action])
        assert operation
        if membership_id:
            form["membership_id"] = membership_id
        outcome = await execute_operation(
            state,
            operation,
            bearer=session.access_token,
            form=form,
            surface="runtime",
            organization_id=organization_id,
        )
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
