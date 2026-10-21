"""First-business journey over canonical platform provisioning operations."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from request_engine.entrypoints.http.admin_console.execution import execute_operation, local_error
from request_engine.entrypoints.http.admin_console.inputs import build_inputs
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.resources import pagination_params
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


def install_business_setup_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def start(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        catalog = (await state.catalog()).by_id()
        create = catalog.get("platform_native_organization_create")
        read = catalog.get("platform_native_identity_list")
        choices: list[dict[str, str]] = []
        error = ""
        cursor = ""
        if create is None or read is None:
            error = "The platform does not expose the operations needed for guided creation."
        else:
            result = await state.control_request(
                read.method,
                read.path_template,
                bearer=session.access_token,
                params=pagination_params(read, request.query_params) or None,
            )
            body = as_mapping(result.payload)
            try:
                if not result.ok or not isinstance(body.get("items"), list):
                    raise ValueError
                rows = body["items"]
                if len(rows) > 100 or "next_cursor" not in body:
                    raise ValueError
                if body["next_cursor"] is not None:
                    cursor = str(UUID(body["next_cursor"]))
                for row in rows:
                    item = as_mapping(row)
                    identity = str(UUID(item["native_identity_id"]))
                    handle = item.get("login_handle")
                    if not isinstance(handle, str) or not handle.strip():
                        raise ValueError
                    if item.get("status") not in {"active", "disabled"}:
                        raise ValueError
                    if item["status"] == "active":
                        choices.append({"value": identity, "label": handle})
            except (ValueError, TypeError, KeyError, AttributeError):
                choices = []
                cursor = ""
                error = "Could not load named accounts. No administrator choice is being assumed."
        inputs = build_inputs(create) if create is not None else []
        for field in inputs:
            if field["name"] == "controller_native_identity_id":
                field["choices"] = choices
                field["label"] = "Who will administer this business?"
            elif field["name"] == "organization_key":
                field["label"] = "Short business name (for example, central-clinic)"
            elif field["name"] == "display_name":
                field["label"] = "Business name"
            elif field["name"] == "provenance_reference":
                field["label"] = "Reason for creating this business"
        return state.templates.TemplateResponse(
            request,
            "resources/business_setup.html",
            state.context(
                request, inputs=inputs, choices=choices, setup_error=error, next_cursor=cursor
            ),
        )

    async def create_business(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        form = {key: str(value) for key, value in (await request.form()).items()}
        operation = (await state.catalog()).by_id().get("platform_native_organization_create")
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            outcome = local_error(403, "csrf_failed", "Invalid form token")
        elif operation is None:
            outcome = local_error(503, "operation_unavailable", "Business creation is unavailable")
        else:
            outcome = await execute_operation(
                state, operation, bearer=session.access_token, form=form
            )
        setup_url = ""
        if outcome.ok:
            try:
                payload = as_mapping(json.loads(outcome.payload_json))
                organization = str(UUID(payload["organization_id"]))
                party = str(UUID(payload["organization_party_id"]))
                query = urlencode({"authority_party_id": party})
                setup_url = f"/tenants/{organization}/configuration/setup?{query}"
            except (ValueError, TypeError, KeyError, AttributeError):
                outcome = local_error(
                    502,
                    "incomplete_creation_result",
                    "The platform accepted creation but returned incomplete details. "
                    "Inspect the business list before creating another business.",
                    idempotency_key=outcome.idempotency_key,
                )
        return state.templates.TemplateResponse(
            request,
            "partials/business_setup_result.html",
            state.context(
                request, result=outcome.to_view(), form_id="create-business", setup_url=setup_url
            ),
        )

    app.add_api_route(
        "/resources/business-setup", start, methods=["GET"], response_class=HTMLResponse
    )
    app.add_api_route(
        "/resources/business-setup", create_business, methods=["POST"], response_class=HTMLResponse
    )
