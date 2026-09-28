"""Operations console: dashboard, catalog listing and generic operation execution.

Every operation is projected from the control-plane OpenAPI document, so the
console can reach the full admin surface without a hand-maintained second
registry. Mutating operations get an idempotency key automatically, and a
recent-authentication failure surfaces a passkey step-up action.
"""

from __future__ import annotations

import json
from secrets import token_urlsafe
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.forms import (
    FormField,
    FormSubmissionError,
    build_fields,
    parse_submission,
    render_path,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_STEP_UP_CODES = frozenset({"phishing_resistant_auth_required", "recent_authentication_required"})


def _result_view(response: Any) -> dict[str, Any]:
    return {
        "status": response.status_code,
        "ok": response.ok,
        "payload_json": json.dumps(response.payload, indent=2, sort_keys=True, default=str),
        "error_code": response.error_code or "",
        "needs_step_up": response.error_code in _STEP_UP_CODES,
        "retry_after": response.retry_after_seconds,
    }


def _local_result(status: int, code: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "ok": False,
        "payload_json": json.dumps({"error": {"code": code, "message": message}}),
        "error_code": code,
        "needs_step_up": False,
        "retry_after": None,
    }


def install_operation_routes(app: FastAPI, state: AdminConsoleState) -> None:
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
        readiness: object = None
        readiness_status = 0
        try:
            response = await state.control_request(
                "GET", "/v1/platform/readiness", bearer=session.access_token
            )
            readiness_status = response.status_code
            readiness = response.payload
        except httpx.HTTPError:
            readiness = {"availability": "control plane unreachable"}
        return state.templates.TemplateResponse(
            request,
            "dashboard.html",
            state.context(
                request,
                operation_count=operation_count,
                platform_operation_count=platform_operation_count,
                group_count=group_count,
                catalog_error=catalog_error,
                readiness=readiness,
                readiness_status=readiness_status,
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
                request, operation=operation, fields=build_fields(operation), result=None
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
        fields = build_fields(operation)
        form = await request.form()
        submitted_csrf = str(form.get("csrf_token", "")) or request.headers.get("x-csrf-token")
        if not state.csrf_matches(submitted_csrf, session.csrf_token):
            return _render_result(
                state,
                request,
                operation,
                fields,
                _local_result(403, "csrf_failed", "CSRF token missing or invalid"),
            )
        try:
            submission = parse_submission(fields, {key: str(value) for key, value in form.items()})
        except FormSubmissionError as exc:
            return _render_result(
                state, request, operation, fields, _local_result(422, "form_error", str(exc))
            )
        path = render_path(operation.path_template, submission.path_params)
        extra_headers = (
            {"idempotency-key": token_urlsafe(24)} if operation.requires_idempotency_key else None
        )
        try:
            response = await state.control_request(
                operation.method,
                path,
                bearer=session.access_token if operation.auth_kind == "bearer" else None,
                json_body=submission.body,
                params=submission.query_params or None,
                extra_headers=extra_headers,
            )
        except httpx.HTTPError as exc:
            return _render_result(
                state,
                request,
                operation,
                fields,
                _local_result(502, "control_unreachable", str(exc)),
            )
        return _render_result(state, request, operation, fields, _result_view(response))

    app.add_api_route("/", dashboard, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/operations", operations, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        "/operations/{operation_id}",
        operation_detail,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route("/operations/{operation_id}", run_operation, methods=["POST"])


def _render_result(
    state: AdminConsoleState,
    request: Request,
    operation: AdminOperation,
    fields: tuple[FormField, ...],
    result: dict[str, Any],
) -> Response:
    partial = request.headers.get("hx-request") == "true"
    template = "partials/result.html" if partial else "operation.html"
    return state.templates.TemplateResponse(
        request,
        template,
        state.context(request, operation=operation, fields=fields, result=result),
    )


__all__ = ["install_operation_routes"]
