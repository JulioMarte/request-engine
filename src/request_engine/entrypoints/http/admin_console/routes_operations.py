"""Operations console: dashboard, catalog listing and generic operation execution.

Every operation is projected from the control-plane OpenAPI document, so the
console can reach the full admin surface without a hand-maintained second
registry. Mutating operations get an idempotency key automatically, and a
recent-authentication failure surfaces a passkey step-up that retries the exact
form. Execution is delegated to the shared ``execution.execute_operation`` path.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.execution import (
    execute_operation,
    local_error,
)
from request_engine.entrypoints.http.admin_console.inputs import build_inputs, summarize_payload
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_FORM_ID = "operation-form"


def install_operation_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _probe(session: Any, method: str, path: str) -> tuple[int, dict[str, Any], str]:
        """Fetch one dashboard fact without letting one bad probe take down the page.

        The control plane normally returns JSON objects, but reverse proxies and
        unhandled 5xx responses can legally arrive as text, lists, or an empty
        body. The dashboard is an observability surface, so those responses must
        be rendered as degraded facts rather than raising while coercing them to
        a mapping.
        """

        try:
            response = await state.control_request(method, path, bearer=session.access_token)
        except httpx.HTTPError:
            return 0, {}, "control plane unreachable"

        payload = response.payload
        if isinstance(payload, dict):
            detail = as_mapping(payload)
        elif payload is None:
            detail = {}
        else:
            detail = {"response": payload}

        error = ""
        if response.status_code >= 500:
            error = f"control plane returned HTTP {response.status_code}"
        return response.status_code, detail, error

    async def dashboard(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        operation_count = 0
        platform_operation_count = 0
        group_count = 0
        catalog_error: str | None = None
        try:
            catalog = await state.catalog()
            operation_count = len(catalog.operations)
            platform_operation_count = len(catalog.platform_operations())
            group_count = len(catalog.groups())
        except Exception:
            catalog_error = "control plane unreachable"
        readiness_status, readiness, readiness_error = await _probe(
            session, "GET", "/v1/platform/readiness"
        )
        observability_status, observability, observability_error = await _probe(
            session, "GET", "/v1/platform/observability"
        )
        deployment_status = readiness_status
        deployment = {
            key: readiness[key]
            for key in (
                "backup_evidence",
                "restore_drill",
                "clone_fence",
                "secret_store",
                "recovery_delivery_source",
            )
            if key in readiness
        }
        deployment_error = readiness_error
        return state.templates.TemplateResponse(
            request,
            "dashboard.html",
            state.context(
                request,
                operation_count=operation_count,
                platform_operation_count=platform_operation_count,
                group_count=group_count,
                catalog_error=catalog_error,
                readiness_status=readiness_status,
                readiness_detail=summarize_payload(readiness) if readiness else ([], []),
                readiness_error=readiness_error,
                observability_status=observability_status,
                observability_detail=summarize_payload(observability)
                if observability
                else ([], []),
                observability_error=observability_error,
                deployment_status=deployment_status,
                deployment_detail=summarize_payload(deployment) if deployment else ([], []),
                deployment_error=deployment_error,
            ),
        )

    async def operations(request: Request, group: str | None = None) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        try:
            catalog = await state.catalog()
        except Exception:
            return state.templates.TemplateResponse(
                request,
                "operations.html",
                state.context(
                    request,
                    groups={},
                    selected_group=None,
                    visible_operations=(),
                    catalog_error="control plane unreachable",
                ),
            )
        groups = catalog.groups()
        selected = group if group in groups else None
        if selected is not None:
            visible: tuple[AdminOperation, ...] = groups[selected]
        else:
            visible = tuple(operation for items in groups.values() for operation in items)
        return state.templates.TemplateResponse(
            request,
            "operations.html",
            state.context(
                request,
                groups=groups,
                selected_group=selected,
                visible_operations=visible,
                catalog_error=None,
            ),
        )

    async def operation_detail(request: Request, operation_id: str) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await state.catalog()
        operation = catalog.by_id().get(operation_id)
        if operation is None:
            return JSONResponse({"error": f"unknown operation {operation_id}"}, status_code=404)
        return state.templates.TemplateResponse(
            request,
            "operation.html",
            state.context(
                request,
                operation=operation,
                inputs=build_inputs(operation),
                result=None,
            ),
        )

    async def run_operation(request: Request, operation_id: str) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await state.catalog()
        operation = catalog.by_id().get(operation_id)
        if operation is None:
            return JSONResponse({"error": f"unknown operation {operation_id}"}, status_code=404)
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return state.templates.TemplateResponse(
                request,
                "partials/result.html",
                state.context(
                    request,
                    result=local_error(
                        403, "csrf_failed", "CSRF token missing or invalid"
                    ).to_view(),
                    form_id=_FORM_ID,
                ),
            )
        outcome = await execute_operation(
            state, operation, bearer=session.access_token, form=values
        )
        return state.templates.TemplateResponse(
            request,
            "partials/result.html",
            state.context(request, result=outcome.to_view(), form_id=_FORM_ID),
        )

    app.add_api_route("/", dashboard, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/operations", operations, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        "/operations/{operation_id}",
        operation_detail,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route("/operations/{operation_id}", run_operation, methods=["POST"])


__all__ = ["install_operation_routes"]
