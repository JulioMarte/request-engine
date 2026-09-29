"""Operations console: dashboard, catalog listing and generic operation execution.

Every operation is projected from the control-plane OpenAPI document, so the
console can reach the full admin surface without a hand-maintained second
registry. Mutating operations get an idempotency key automatically, and a
recent-authentication failure surfaces a passkey step-up that retries the exact
form. Execution is delegated to the shared ``execution.execute_operation`` path.
"""

from __future__ import annotations

from asyncio import gather
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
from request_engine.entrypoints.http.admin_console.resources import RESOURCE_SPECS, WORKSPACE_SPECS
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_FORM_ID = "operation-form"

_GOOD_STATES = frozenset({"active", "available", "configured", "healthy", "ok", "ready"})


def _probe_view(
    title: str,
    status: int,
    payload: dict[str, Any],
    error: str,
    href: str,
    healthy_override: bool | None = None,
) -> dict[str, str]:
    raw_state = payload.get("status", payload.get("state"))
    state = str(raw_state).lower() if raw_state is not None else ""
    healthy = (
        200 <= status < 300 and state in (_GOOD_STATES | {"in_sync"})
        if healthy_override is None
        else healthy_override
    )
    if status == 0:
        label = "Unavailable"
    elif not 200 <= status < 300:
        label = f"HTTP {status}"
    elif state:
        label = state.replace("_", " ").title()
    else:
        label = "Available"
    return {
        "title": title,
        "label": label,
        "tone": "ok" if healthy else ("neutral" if 200 <= status < 300 else "warn"),
        "detail": error
        or (
            "Responding normally"
            if healthy
            else "Data available"
            if status == 200
            else "Review current state"
        ),
        "href": href,
    }


def _attention_items(
    readiness_status: int,
    readiness: dict[str, Any],
    readiness_error: str,
    observability_status: int,
    observability: dict[str, Any],
    observability_error: str,
    deployment_status: int,
    deployment: dict[str, Any],
    deployment_error: str,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    dependencies = (
        (readiness_status, readiness_error, "Platform readiness", "/diagnostics"),
        (observability_status, observability_error, "Operational telemetry", "/diagnostics"),
        (
            deployment_status,
            deployment_error,
            "Deployment recovery",
            "/resources/deployment-recovery",
        ),
    )
    for status, error, title, href in dependencies:
        if not 200 <= status < 300:
            items.append(
                {
                    "title": title,
                    "detail": error or f"The control plane returned HTTP {status}.",
                    "href": href,
                    "action": "Review",
                }
            )
    for alert in observability.get("alerts", []):
        alert_body = as_mapping(alert)
        code = str(alert_body.get("code") or "Operational alert")
        metric = str(alert_body.get("metric") or "A monitored threshold was crossed")
        items.append(
            {
                "title": code.replace("_", " ").title(),
                "detail": metric.replace("_", " "),
                "href": "/diagnostics",
                "action": "Inspect diagnostics",
            }
        )
    readiness_checks = (
        ("secret_store", "Secret store", "/resources/secrets"),
        ("recovery_delivery_source", "Recovery delivery", "/resources/configurations"),
        ("restore_drill", "Restore drill", "/resources/deployment-recovery"),
    )
    for field, title, href in readiness_checks:
        value = readiness.get(field)
        if value is None:
            continue
        normalized = str(value).lower()
        if normalized in _GOOD_STATES or normalized in {"managed", "bootstrap", "current"}:
            continue
        items.append(
            {
                "title": title,
                "detail": f"Current reported state: {str(value).replace('_', ' ')}.",
                "href": href,
                "action": "Review",
            }
        )
    deployment_state = str(deployment.get("state", "")).lower()
    if 200 <= deployment_status < 300 and deployment_state not in {"", "in_sync"}:
        items.append(
            {
                "title": "Deployment binding",
                "detail": (
                    "The recovery binding is "
                    f"{deployment_state.replace('_', ' ')} and needs review."
                ),
                "href": "/resources/deployment-recovery",
                "action": "Review binding",
            }
        )
    return items


def install_operation_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _probe(session: Any, method: str, path: str) -> tuple[int, dict[str, Any], str]:
        try:
            response = await state.control_request(method, path, bearer=session.access_token)
        except httpx.HTTPError:
            return 0, {}, "control plane unreachable"
        return response.status_code, as_mapping(response.payload), ""

    async def dashboard(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        catalog_error: str | None = None
        try:
            await state.catalog()
        except Exception:
            catalog_error = "control plane unreachable"
        (
            (readiness_status, readiness, readiness_error),
            (observability_status, observability, observability_error),
            (deployment_status, deployment, deployment_error),
        ) = await gather(
            _probe(session, "GET", "/v1/platform/readiness"),
            _probe(session, "GET", "/v1/platform/observability"),
            _probe(session, "GET", "/v1/platform/deployment-recovery:plan"),
        )
        attention = _attention_items(
            readiness_status,
            readiness,
            readiness_error,
            observability_status,
            observability,
            observability_error,
            deployment_status,
            deployment,
            deployment_error,
        )
        readiness_fields = ("secret_store", "recovery_delivery_source", "restore_drill")
        readiness_good = readiness_status in range(200, 300) and (
            str(readiness.get("status", "")).lower() in _GOOD_STATES
            or all(
                field in readiness
                and str(readiness[field]).lower()
                in (_GOOD_STATES | {"managed", "bootstrap", "current"})
                for field in readiness_fields
            )
        )
        observability_good = observability_status in range(200, 300) and not observability.get(
            "alerts", []
        )
        deployment_good = (
            deployment_status in range(200, 300)
            and str(deployment.get("state", "")).lower() == "in_sync"
        )
        services = (
            _probe_view(
                "Control plane",
                readiness_status,
                readiness,
                readiness_error,
                "/diagnostics",
                readiness_good,
            ),
            _probe_view(
                "Observability",
                observability_status,
                observability,
                observability_error,
                "/diagnostics",
                observability_good,
            ),
            _probe_view(
                "Recovery binding",
                deployment_status,
                deployment,
                deployment_error,
                "/resources/deployment-recovery",
                deployment_good,
            ),
        )
        overall_state = (
            "attention"
            if attention
            else "healthy"
            if all(service["tone"] == "ok" for service in services)
            else "incomplete"
        )
        return state.templates.TemplateResponse(
            request,
            "dashboard.html",
            state.context(
                request,
                catalog_error=catalog_error,
                services=services,
                attention=attention,
                overall_state=overall_state,
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

    async def operations(
        request: Request, group: str | None = None, q: str | None = None
    ) -> Response:
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
        query = (q or "").strip().lower()
        if selected is not None:
            visible: tuple[AdminOperation, ...] = groups[selected]
        else:
            visible = tuple(operation for items in groups.values() for operation in items)
        if query:
            visible = tuple(
                operation
                for operation in visible
                if query
                in " ".join(
                    (
                        operation.operation_id,
                        operation.summary,
                        operation.description,
                        operation.path_template,
                        operation.owner or "",
                        operation.capability or "",
                    )
                ).lower()
            )
        workspaces = tuple(
            item
            for item in (*RESOURCE_SPECS, *WORKSPACE_SPECS)
            if query and query in f"{item.title} {item.summary} {item.owner}".lower()
        )
        return state.templates.TemplateResponse(
            request,
            "operations.html",
            state.context(
                request,
                groups=groups,
                selected_group=selected,
                query=q or "",
                matching_workspaces=workspaces,
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
