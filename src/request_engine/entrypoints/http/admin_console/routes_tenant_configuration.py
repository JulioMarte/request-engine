"""Tenant setup tasks projected onto the existing runtime owner operations."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, AdminOperation
from request_engine.entrypoints.http.admin_console.execution import execute_operation, local_error
from request_engine.entrypoints.http.admin_console.inputs import (
    build_inputs,
    scalar_columns,
    summarize_payload,
)
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.presentation import (
    TENANT_CONFIGURATION_OPERATION_IDS,
    TENANT_CONFIGURATION_SECTIONS,
)
from request_engine.entrypoints.http.admin_console.resources import list_items
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState
from request_engine.entrypoints.http.admin_console.tenant_configuration import (
    inventory_read_valid,
    read_action_links,
)

_FORM_ID = "tenant-configuration-operation"


def install_tenant_configuration_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def catalog_or_error(request: Request) -> AdminCatalog | Response:
        if state.session(request) is None:
            return RedirectResponse("/login", status_code=303)
        if state.runtime is None:
            return Response(
                "Configure the runtime API to manage tenant configuration.", status_code=503
            )
        try:
            return await state.runtime_catalog()
        except Exception:
            return Response("Tenant operation catalog unavailable.", status_code=503)

    async def workspace(request: Request, organization_id: UUID) -> Response:
        catalog = await catalog_or_error(request)
        if isinstance(catalog, Response):
            return catalog
        root = f"/tenants/{organization_id}/configuration"
        search = request.query_params.get("q", "").strip()[:100]
        sections: list[dict[str, Any]] = [
            {
                "title": title,
                "operations": [
                    catalog.by_id()[key] for key in operation_ids if key in catalog.by_id()
                ],
            }
            for title, operation_ids in TENANT_CONFIGURATION_SECTIONS
        ]
        if search:
            needle = search.casefold()
            for section in sections:
                section["operations"] = [
                    operation
                    for operation in section["operations"]
                    if needle
                    in f"{section['title']} {operation.operation_id} {operation.summary}".casefold()
                ]
            sections = [section for section in sections if section["operations"]]
        session = state.session(request)
        assert session is not None
        readiness = catalog.by_id().get("onboarding_read")
        readiness_result = None
        readiness_sections: list[dict[str, Any]] = []
        if readiness is not None:
            outcome = await execute_operation(
                state,
                readiness,
                bearer=session.access_token,
                form={},
                surface="runtime",
                organization_id=str(organization_id),
            )
            if outcome.ok:
                payload = as_mapping(json.loads(outcome.payload_json))
                for key, value in payload.items():
                    section = as_mapping(value)
                    status = section.get("status")
                    if (
                        isinstance(status, str)
                        and status in {"ready", "blocked", "unknown"}
                        and type(section.get("ready")) is bool
                        and section["ready"] is (status == "ready")
                        and isinstance(section.get("blockers"), list)
                    ):
                        readiness_sections.append(
                            {"title": key.replace("_", " ").title(), **section}
                        )
                if not readiness_sections:
                    readiness_result = local_error(
                        502,
                        "invalid_owner_response",
                        "Setup readiness is incomplete. No ready status is being assumed.",
                    ).to_view()
            else:
                readiness_result = outcome.to_view()
        return state.templates.TemplateResponse(
            request,
            "resources/tenant_configuration.html",
            state.context(
                request,
                root=root,
                organization_id=str(organization_id),
                sections=sections,
                search=search,
                readiness_sections=readiness_sections,
                readiness_result=readiness_result,
                readiness_available=readiness is not None,
                supported=TENANT_CONFIGURATION_OPERATION_IDS,
                form_id="tenant-readiness",
            ),
        )

    async def operation_page(
        request: Request, organization_id: UUID, operation_id: str
    ) -> Response:
        catalog = await catalog_or_error(request)
        if isinstance(catalog, Response):
            return catalog
        operation = catalog.by_id().get(operation_id)
        if operation_id not in TENANT_CONFIGURATION_OPERATION_IDS or operation is None:
            return Response("Tenant configuration operation unavailable.", status_code=404)
        values = dict(request.query_params)
        _bind_tenant(operation, values, organization_id)
        return state.templates.TemplateResponse(
            request,
            "resources/tenant_configuration_operation.html",
            state.context(
                request,
                organization_id=str(organization_id),
                root=f"/tenants/{organization_id}/configuration",
                operation=operation,
                inputs=build_inputs(operation, values=values),
                form_id=_FORM_ID,
            ),
        )

    async def execute(request: Request, organization_id: UUID, operation_id: str) -> Response:
        catalog = await catalog_or_error(request)
        if isinstance(catalog, Response):
            return catalog
        operation = catalog.by_id().get(operation_id)
        if operation_id not in TENANT_CONFIGURATION_OPERATION_IDS or operation is None:
            return Response("Tenant configuration operation unavailable.", status_code=404)
        session = state.session(request)
        assert session is not None
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        _bind_tenant(operation, values, organization_id)
        links: list[dict[str, str]] = []
        detail: tuple[list[tuple[str, str]], list[tuple[str, str]]] = ([], [])
        next_url = ""
        columns: tuple[str, ...] = ()
        rows: list[list[str]] = []
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            outcome = local_error(403, "csrf_failed", "CSRF token missing or invalid")
        else:
            outcome = await execute_operation(
                state,
                operation,
                bearer=session.access_token,
                form=values,
                surface="runtime",
                organization_id=str(organization_id),
            )
            if outcome.ok and not operation.is_mutating:
                payload = as_mapping(json.loads(outcome.payload_json))
                if not inventory_read_valid(operation_id, payload):
                    outcome = local_error(
                        502,
                        "invalid_owner_response",
                        "Owner inventory response is incomplete or invalid",
                    )
                else:
                    detail = summarize_payload(payload)
                items = list_items(payload) if outcome.ok else []
                if items:
                    columns = tuple(
                        key
                        for key, value in items[0].items()
                        if not isinstance(value, (list, dict))
                    )
                    rows = [scalar_columns(item, columns) for item in items]
                    detail = ([entry for entry in detail[0] if entry[0] != "items"], detail[1])
                root = f"/tenants/{organization_id}/configuration"
                links = read_action_links(
                    operation_id, payload, values=values, catalog=catalog, root=root
                )
                cursor = (
                    payload.get("next_cursor", payload.get("next_after")) if outcome.ok else None
                )
                pagination_name = next(
                    (
                        parameter.name
                        for parameter in operation.parameters
                        if parameter.location == "query" and parameter.name in {"cursor", "after"}
                    ),
                    None,
                )
                if cursor and pagination_name:
                    declared = {
                        parameter.name
                        for parameter in operation.parameters
                        if parameter.location in {"query", "path"}
                    }
                    params = {key: value for key, value in values.items() if key in declared}
                    params[pagination_name] = str(cursor)
                    next_url = f"{root}/{operation_id}?{urlencode(params)}"
        return state.templates.TemplateResponse(
            request,
            "partials/tenant_configuration_result.html",
            state.context(
                request,
                result=outcome.to_view(),
                form_id=_FORM_ID,
                links=links,
                detail=detail,
                next_url=next_url,
                columns=columns,
                rows=rows,
            ),
        )

    app.add_api_route(
        "/tenants/{organization_id}/configuration",
        workspace,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/tenants/{organization_id}/configuration/{operation_id}",
        operation_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/tenants/{organization_id}/configuration/{operation_id}", execute, methods=["POST"]
    )


def _bind_tenant(operation: AdminOperation, values: dict[str, str], organization_id: UUID) -> None:
    # URL selection is the sole tenant context. Never let an editable form or
    # supplied header pick a different tenant; owner operations still authorize it.
    names = {parameter.name for parameter in operation.parameters}
    names.update(as_mapping(as_mapping(operation.body_schema).get("properties")))
    if "organization_id" in names:
        values["organization_id"] = str(organization_id)


__all__ = ["install_tenant_configuration_routes"]
