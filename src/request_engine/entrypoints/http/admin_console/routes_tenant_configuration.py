"""Tenant setup tasks projected onto the existing runtime owner operations."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, AdminOperation
from request_engine.entrypoints.http.admin_console.execution import execute_operation, local_error
from request_engine.entrypoints.http.admin_console.inputs import (
    build_inputs,
    scalar_columns,
    summarize_payload,
)
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.presentation import (
    TENANT_CONFIGURATION_OPERATION_IDS,
    TENANT_CONFIGURATION_SECTIONS,
)
from request_engine.entrypoints.http.admin_console.resources import list_items
from request_engine.entrypoints.http.admin_console.routes_clinic_setup import (
    resolve_business_party,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState
from request_engine.entrypoints.http.admin_console.tenant_configuration import (
    inventory_read_valid,
    read_action_links,
)

_FORM_ID = "tenant-configuration-operation"
_SELECTOR_READS = {
    "location_id": "catalog_location_configuration_list",
    "offering_id": "catalog_offering_configuration_list",
    "queue_id": "queue_service_queue_configuration_list",
    "definition_id": "request_definitions_list",
}


def install_tenant_configuration_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def catalog_or_error(request: Request) -> AdminCatalog | Response:
        if state.session(request) is None:
            return login_redirect(request)
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
        # Advanced tasks are prefilled with the business Party the signed-in owner
        # represents, read from the owner; nobody is asked to type its identifier.
        party_id = request.query_params.get("authority_party_id", "") or (
            await resolve_business_party(state, str(organization_id), session.access_token) or ""
        )
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
                authority_party_id=party_id,
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
        inputs, guidance, blocked = await guided_inputs(
            request, organization_id, catalog, operation, values
        )
        party_query = urlencode({"authority_party_id": values.get("authority_party_id", "")})
        return state.templates.TemplateResponse(
            request,
            "resources/tenant_configuration_operation.html",
            state.context(
                request,
                organization_id=str(organization_id),
                root=f"/tenants/{organization_id}/configuration",
                operation=operation,
                inputs=inputs,
                selection_inputs=[
                    item
                    for item in inputs
                    if item["name"]
                    in {"authority_party_id", "offering_version_id", *_SELECTOR_READS}
                ],
                inventory_links=[
                    {
                        "label": f"Browse {field.removesuffix('_id').replace('_', ' ')} inventory",
                        "href": (
                            f"/tenants/{organization_id}/configuration/{read_id}?" + party_query
                        ),
                    }
                    for field, read_id in _SELECTOR_READS.items()
                    if read_id in catalog.by_id() and any(item["name"] == field for item in inputs)
                ],
                guidance=guidance,
                blocked=blocked,
                change_selection_url=(
                    f"/tenants/{organization_id}/configuration/{operation_id}?{party_query}"
                    if any(
                        item["name"] in _SELECTOR_READS and item.get("hidden") for item in inputs
                    )
                    else ""
                ),
                form_id=_FORM_ID,
            ),
        )

    async def guided_inputs(
        request: Request,
        organization_id: UUID,
        catalog: AdminCatalog,
        operation: AdminOperation,
        values: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[str], bool]:
        """Resolve choices and edit revisions through authenticated owner queries."""
        session = state.session(request)
        assert session is not None
        guidance: list[str] = []
        blocked = False
        choices: dict[str, list[dict[str, str]]] = {}
        read_bound: set[str] = set()
        root = f"/tenants/{organization_id}/configuration"
        for field, list_id in _SELECTOR_READS.items():
            names = {item.name for item in operation.parameters}
            names.update(as_mapping(as_mapping(operation.body_schema).get("properties")))
            if field not in names:
                continue
            inventory = catalog.by_id().get(list_id)
            if inventory is None:
                continue
            inventory_names = {item.name for item in inventory.parameters}
            if "authority_party_id" in inventory_names and not values.get("authority_party_id"):
                continue
            outcome = await execute_operation(
                state,
                inventory,
                bearer=session.access_token,
                form={"authority_party_id": values.get("authority_party_id", ""), "limit": "100"},
                surface="runtime",
                organization_id=str(organization_id),
            )
            payload = as_mapping(json.loads(outcome.payload_json))
            if not outcome.ok or not inventory_read_valid(list_id, payload):
                guidance.append(
                    "Current choices could not be verified. Reload after restoring access."
                )
                blocked = True
                continue
            choices[field] = [
                {
                    "value": row[field],
                    "label": f"{row['display_name']} ({'active' if row['active'] else 'inactive'})",
                }
                for row in list_items(payload)
            ]
            if payload.get("next_cursor"):
                guidance.append(
                    "This picker shows the first 100 items. Use the inventory to find later items."
                )
            if values.get(field) and values[field] not in {row["value"] for row in choices[field]}:
                selected_read = catalog.by_id().get(
                    "request_definition_read"
                    if list_id == "request_definitions_list"
                    else list_id.removesuffix("_list") + "_read"
                )
                selected = {}
                if selected_read is not None:
                    outcome = await execute_operation(
                        state,
                        selected_read,
                        bearer=session.access_token,
                        form=values,
                        surface="runtime",
                        organization_id=str(organization_id),
                    )
                    candidate = as_mapping(json.loads(outcome.payload_json))
                    if (
                        outcome.ok
                        and inventory_read_valid(selected_read.operation_id, candidate)
                        and candidate.get(field) == values[field]
                    ):
                        selected = candidate
                if selected:
                    choices[field].append(
                        {
                            "value": selected[field],
                            "label": (
                                f"{selected['display_name']} "
                                f"({'active' if selected['active'] else 'inactive'})"
                            ),
                        }
                    )
                else:
                    values.pop(field)
                    guidance.append(
                        "The previous selection could not be verified; choose a listed item."
                    )
        read_id = {
            "catalog_location_update": "catalog_location_configuration_read",
            "catalog_location_hours_replace": "catalog_location_configuration_read",
            "catalog_location_contacts_update": "catalog_location_configuration_read",
            "catalog_location_hours_exception_upsert": "catalog_location_configuration_read",
            "request_definition_version_publish": "request_definition_read",
            "request_definition_set_active": "request_definition_read",
            "catalog_manage_offering_version_booking_policy": (
                "catalog_offering_version_configuration_read"
            ),
        }.get(operation.operation_id)
        owner_read = catalog.by_id().get(read_id or "")
        if owner_read is not None:
            required = [
                item.name
                for item in owner_read.parameters
                if item.required and item.location in {"path", "query"}
            ]
            if all(values.get(name) for name in required):
                outcome = await execute_operation(
                    state,
                    owner_read,
                    bearer=session.access_token,
                    form=values,
                    surface="runtime",
                    organization_id=str(organization_id),
                )
                payload = as_mapping(json.loads(outcome.payload_json))
                identity_fields = [
                    name
                    for name in required
                    if name.endswith("_id") and name != "authority_party_id"
                ]
                valid = outcome.ok and inventory_read_valid(owner_read.operation_id, payload)
                valid = valid and all(payload.get(name) == values[name] for name in identity_fields)
                links = (
                    read_action_links(
                        owner_read.operation_id, payload, values=values, catalog=catalog, root=root
                    )
                    if valid
                    else []
                )
                target_link = next(
                    (
                        link
                        for link in links
                        if urlsplit(link["href"]).path == f"{root}/{operation.operation_id}"
                    ),
                    None,
                )
                if target_link is None:
                    guidance.append(
                        "The selected item's current configuration could not be verified. "
                        "No change can be submitted."
                    )
                    blocked = True
                else:
                    prefill = {
                        key: entries[0]
                        for key, entries in parse_qs(
                            urlsplit(target_link["href"]).query, keep_blank_values=True
                        ).items()
                    }
                    values.update(prefill)
                    read_bound.update(name for name in prefill if "revision" in name)
                    read_bound.update(identity_fields)
                    if payload.get("display_name"):
                        guidance.append(f"Editing: {payload['display_name']}")
                    if operation.operation_id == "catalog_location_hours_replace":
                        guidance.append(
                            "Current opening hours and their revision were loaded. Review the "
                            "complete schedule before replacing it. An empty schedule removes "
                            "every opening window."
                        )
                    elif operation.operation_id == "catalog_location_hours_exception_upsert":
                        guidance.append(
                            "The current location revision was loaded. "
                            "Enter the new hours exception."
                        )
                    else:
                        guidance.append(
                            "Current settings were loaded automatically. "
                            "Review your changes before applying them."
                        )
            else:
                guidance.append("Choose an item, then load its current settings before editing.")
                blocked = True
        inputs = build_inputs(operation, values=values, loaded_revisions=tuple(read_bound))
        for item in inputs:
            if item["name"] == "organization_id":
                item["hidden"] = True
            if item["name"] in choices:
                item["enum_options"] = choices[item["name"]]
                item["label"] = item["name"].removesuffix("_id").replace("_", " ").title()
            if item["name"] in read_bound:
                item["hidden"] = True
        return inputs, guidance, blocked

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
        elif (
            operation_id == "catalog_location_hours_replace"
            and values.get("_confirm_replacement") != "true"
        ):
            outcome = local_error(
                422,
                "replacement_confirmation_required",
                "Confirm that this complete schedule replaces all existing opening hours.",
            )
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
        "/tenants/{organization_id}/configuration/setup",
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
