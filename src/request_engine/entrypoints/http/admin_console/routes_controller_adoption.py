"""Consent review and policy adoption through canonical control operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from request_engine.entrypoints.http.admin_console.execution import (
    ExecutionOutcome,
    execute_operation,
    local_error,
)
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.resources import (
    CONTROLLER_ADOPTION_OPERATION_IDS,
    MissingOperation,
    list_items,
    next_cursor,
    resolve_operation,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_ROOT = "/resources/controller-policy-adoptions"


def install_controller_adoption_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def run(request: Request, action: str, values: dict[str, str]) -> ExecutionOutcome:
        session = state.session(request)
        assert session is not None
        try:
            operation = resolve_operation(
                await state.catalog(), CONTROLLER_ADOPTION_OPERATION_IDS[action]
            )
        except MissingOperation:
            return local_error(503, "operation_unavailable", "This operation is unavailable.")
        except (httpx.HTTPError, ValueError):
            return local_error(
                503,
                "catalog_unavailable",
                "The operation catalog is unavailable. Reload before acting.",
            )
        assert operation is not None
        return await execute_operation(state, operation, bearer=session.access_token, form=values)

    async def listing(request: Request) -> Response:
        if state.session(request) is None:
            return login_redirect(request)
        values = {
            key: request.query_params[key]
            for key in ("after", "limit")
            if key in request.query_params
        }
        outcome = await run(request, "list", values)
        payload = as_mapping(json.loads(outcome.payload_json) if outcome.ok else None)
        if outcome.ok and not _valid_page(payload):
            outcome = local_error(
                502,
                "control_response_invalid",
                "The control plane returned an invalid collection. Reload before acting.",
            )
            payload = as_mapping(None)
        cursor = next_cursor(payload)
        pagination = {"after": cursor}
        if values.get("limit"):
            pagination["limit"] = values["limit"]
        return state.templates.TemplateResponse(
            request,
            "resources/controller_adoptions.html",
            state.context(
                request,
                rows=list_items(payload),
                result=None if outcome.ok else outcome.to_view(),
                form_id="adoption-list",
                next_url=f"{_ROOT}?{urlencode(pagination)}" if cursor else "",
            ),
            status_code=200 if outcome.ok else outcome.status,
        )

    async def review(request: Request, request_id: str) -> Response:
        if state.session(request) is None:
            return login_redirect(request)
        outcome = await run(request, "review", {"request_id": request_id})
        item = as_mapping(json.loads(outcome.payload_json)) if outcome.ok else {}
        if outcome.ok and not _valid_review(item, request_id):
            outcome = local_error(
                502,
                "control_response_invalid",
                "The control plane returned an invalid consent review. No action is available.",
            )
            item = as_mapping(None)
        return state.templates.TemplateResponse(
            request,
            "resources/controller_adoption_review.html",
            state.context(
                request,
                item=item,
                request_id=request_id,
                result=None if outcome.ok else outcome.to_view(),
                form_id="adoption-review",
                action_url=f"{_ROOT}/{request_id}/apply",
            ),
            status_code=200 if outcome.ok else outcome.status,
        )

    async def apply(request: Request, request_id: str) -> Response:
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            outcome = local_error(403, "csrf_failed", "CSRF token missing or invalid")
        else:
            # Preserve the reviewed revision and stable intent on retries; never
            # silently refresh consent. The URL, not an editable form, binds the request.
            values["request_id"] = request_id
            outcome = await run(request, "apply", values)
        return state.templates.TemplateResponse(
            request,
            "partials/result.html",
            state.context(request, result=outcome.to_view(), form_id="adoption-apply"),
        )

    app.add_api_route(_ROOT, listing, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        f"{_ROOT}/{{request_id}}", review, methods=["GET"], response_class=HTMLResponse
    )
    app.add_api_route(f"{_ROOT}/{{request_id}}/apply", apply, methods=["POST"])


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _valid_review(item: dict[str, Any], request_id: str) -> bool:
    return (
        _uuid(item.get("request_id")) is not None
        and _uuid(item.get("request_id")) == _uuid(request_id)
        and all(
            _uuid(item.get(key)) is not None
            for key in ("organization_id", "controller_principal_id")
        )
        and all(
            _positive_revision(item.get(key))
            for key in (
                "request_revision",
                "expected_authority_revision",
                "current_authority_revision",
            )
        )
        and all(
            isinstance(item.get(key), str) and item[key].strip()
            for key in ("source_policy_key", "target_policy_key", "reason")
        )
        and _timestamp(item.get("expires_at"))
        and all(
            isinstance(item.get(key), list)
            and all(isinstance(value, str) and value for value in as_list(item[key]))
            for key in ("proposed_capabilities", "revoked_capabilities")
        )
        and type(item.get("proposed_delta_does_not_restore_revoked_capabilities")) is bool
    )


def _positive_revision(value: object) -> bool:
    return type(value) is int and value >= 1


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_page(payload: dict[str, Any]) -> bool:
    items = payload.get("items")
    if not isinstance(items, list) or "next_after" not in payload:
        return False
    cursor = payload.get("next_after")
    if cursor is not None and _uuid(cursor) is None:
        return False
    return all(
        isinstance(item, dict)
        and _uuid(as_mapping(item).get("request_id")) is not None
        and _uuid(as_mapping(item).get("organization_id")) is not None
        and isinstance(as_mapping(item).get("status"), str)
        and bool(as_mapping(item).get("status"))
        and _uuid(as_mapping(item).get("controller_principal_id")) is not None
        and all(
            _positive_revision(as_mapping(item).get(key))
            for key in ("request_revision", "expected_authority_revision")
        )
        and all(
            isinstance(as_mapping(item).get(key), str) and bool(as_mapping(item).get(key))
            for key in ("source_policy_key", "target_policy_key")
        )
        and all(_timestamp(as_mapping(item).get(key)) for key in ("created_at", "expires_at"))
        for item in as_list(items)
    )
