"""Platform owner inspection and lifecycle journeys over canonical owner APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.execution import execute_operation, local_error
from request_engine.entrypoints.http.admin_console.forms import render_path
from request_engine.entrypoints.http.admin_console.inputs import build_inputs, summarize_payload
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.resources import (
    OWNER_OPERATION_IDS,
    MissingOperation,
    list_items,
    next_cursor,
    resolve_operation,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_OWNER_ACTIONS = {key: OWNER_OPERATION_IDS[key] for key in ("suspend", "reactivate", "revoke")}
_INVITATION_ACTIONS = {
    "activate": OWNER_OPERATION_IDS["activate_invitation"],
    "revoke": OWNER_OPERATION_IDS["revoke_invitation"],
}


_OWNER_FIELDS = (
    "principal_id",
    "active",
    "authority_revision",
    "binding_id",
    "binding_status",
    "capabilities",
)
_INVITATION_FIELDS = (
    "invitation_id",
    "status",
    "revision",
    "native_identity_id",
    "created_at",
    "expires_at",
    "enrolled_at",
    "consumed_at",
    "revoked_at",
    "expired",
)


def _project_item(value: Any, *, invitation: bool) -> dict[str, Any] | None:
    item = as_mapping(value)
    identifier = item.get("invitation_id" if invitation else "principal_id")
    revision = item.get("revision" if invitation else "authority_revision")
    if not isinstance(identifier, str) or type(revision) is not int or revision < 1:
        return None
    try:
        UUID(identifier)
    except ValueError:
        return None
    if invitation:
        if not isinstance(item.get("status"), str) or type(item.get("expired")) is not bool:
            return None
    elif type(item.get("active")) is not bool or not isinstance(item.get("capabilities"), list):
        return None
    return {
        field: item.get(field) for field in (_INVITATION_FIELDS if invitation else _OWNER_FIELDS)
    }


def _read_error(status: int) -> str:
    return {
        401: "Your session is no longer authorized. Sign in again.",
        403: "You do not have permission to inspect platform owners.",
        404: "This owner resource was not found.",
        502: "The owner service returned an incomplete response. Try again.",
    }.get(status, "Owner information is temporarily unavailable. Try again.")


def install_owner_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def read(request: Request, key: str, *, item_id: UUID | None = None) -> ControlResponse:
        session = state.session(request)
        assert session is not None
        try:
            operation = resolve_operation(await state.catalog(), OWNER_OPERATION_IDS[key])
            assert operation is not None
            path_values = (
                {"invitation_id" if key == "invitation_get" else "principal_id": str(item_id)}
                if item_id is not None
                else {}
            )
            response = await state.control_request(
                operation.method,
                render_path(operation.path_template, path_values),
                bearer=session.access_token,
                params={
                    "limit": request.query_params.get("limit", "50"),
                    **(
                        {"after": request.query_params["after"]}
                        if "after" in request.query_params
                        else {}
                    ),
                }
                if item_id is None
                else None,
            )
        except (httpx.HTTPError, MissingOperation, ValueError):
            return ControlResponse(503, None, {})
        if response.ok:
            payload = as_mapping(response.payload)
            invitation = key.startswith("invitation_")
            if item_id is None:
                raw_items = payload.get("items")
                if not isinstance(raw_items, list):
                    return ControlResponse(502, None, {})
                projected = [
                    _project_item(row, invitation=invitation) for row in as_list(raw_items)
                ]
                if any(row is None for row in projected):
                    return ControlResponse(502, None, {})
                response = ControlResponse(
                    response.status_code,
                    {
                        "items": projected,
                        "next_after": payload.get("next_after"),
                    },
                    response.headers,
                )
            else:
                item = _project_item(payload, invitation=invitation)
                if item is None or item.get(
                    "invitation_id" if invitation else "principal_id"
                ) != str(item_id):
                    return ControlResponse(502, None, {})
                response = ControlResponse(response.status_code, item, response.headers)

        return response

    def action_view(
        request: Request,
        operation: AdminOperation,
        key: str,
        url: str,
        values: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return state.context(
            request,
            inputs=build_inputs(
                operation,
                values=values,
                loaded_revisions=tuple(
                    name
                    for name in (values or {})
                    if name.startswith("expected_") and "revision" in name
                ),
            ),
            form_id=f"owner-{key}",
            action_url=url,
            submit_label={
                "invite": "Create owner invitation",
                "activate": "Activate enrolled owner",
            }.get(key, key.title()),
            danger=key in {"suspend", "revoke"},
            confirm="" if key == "invite" else f"{key.title()} this owner resource?",
        )

    async def forms(
        request: Request,
        operations: dict[str, str],
        base: str,
        values: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        try:
            catalog = await state.catalog()
            resolved = [
                (key, resolve_operation(catalog, operation_id))
                for key, operation_id in operations.items()
            ]
        except (httpx.HTTPError, MissingOperation, ValueError):
            return [], True
        return [
            action_view(request, operation, key, f"{base}/actions/{key}", values)
            for key, operation in resolved
            if operation is not None
        ], False

    async def collection(request: Request, *, invitations: bool) -> Response:
        if state.session(request) is None:
            return RedirectResponse("/login", status_code=303)
        response = await read(request, "invitation_list" if invitations else "list")
        action_forms: list[dict[str, Any]] = []
        drift = False
        if response.ok and invitations:
            action_forms, drift = await forms(
                request, {"invite": OWNER_OPERATION_IDS["invite"]}, "/resources/owners"
            )
        return state.templates.TemplateResponse(
            request,
            "resources/owners.html",
            state.context(
                request,
                invitations=invitations,
                rows=list_items(response.payload) if response.ok else [],
                next_after=next_cursor(response.payload) if response.ok else "",
                page_limit=request.query_params.get("limit", "50"),
                after=request.query_params.get("after", ""),
                read_error="" if response.ok else _read_error(response.status_code),
                forms=action_forms,
                action_drift=drift,
            ),
            status_code=200 if response.ok else response.status_code,
        )

    async def owners(
        request: Request,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        return await collection(request, invitations=False)

    async def invitations(
        request: Request,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        return await collection(request, invitations=True)

    async def detail(request: Request, item_id: UUID, *, invitation: bool) -> Response:
        if state.session(request) is None:
            return RedirectResponse("/login", status_code=303)
        response = await read(request, "invitation_get" if invitation else "get", item_id=item_id)
        item = as_mapping(response.payload) if response.ok else {}
        base = "/resources/owners" + ("/invitations" if invitation else "")
        values = {"invitation_id" if invitation else "principal_id": str(item_id)}
        if not invitation:
            values["expected_revision"] = str(item.get("authority_revision", ""))
        action_forms, drift = (
            await forms(
                request,
                _INVITATION_ACTIONS if invitation else _OWNER_ACTIONS,
                f"{base}/{item_id}",
                values,
            )
            if response.ok
            else ([], False)
        )
        return state.templates.TemplateResponse(
            request,
            "resources/owner_detail.html",
            state.context(
                request,
                invitation=invitation,
                item=item,
                item_id=str(item_id),
                base=base,
                detail=summarize_payload(item),
                forms=action_forms,
                action_drift=drift,
                read_error="" if response.ok else _read_error(response.status_code),
            ),
            status_code=200 if response.ok else response.status_code,
        )

    async def owner_detail(request: Request, principal_id: UUID) -> Response:
        return await detail(request, principal_id, invitation=False)

    async def invitation_detail(request: Request, invitation_id: UUID) -> Response:
        return await detail(request, invitation_id, invitation=True)

    async def run(
        request: Request,
        key: str,
        *,
        item_id: UUID | None = None,
        invitation: bool = False,
    ) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        submitted = await request.form()
        values = {name: str(value) for name, value in submitted.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            outcome = local_error(403, "csrf_failed", "CSRF token missing or invalid")
        else:
            operation_id = (
                OWNER_OPERATION_IDS["invite"]
                if key == "invite" and item_id is None
                else (
                    (_INVITATION_ACTIONS if invitation else _OWNER_ACTIONS).get(key)
                    if item_id is not None
                    else None
                )
            )
            try:
                if operation_id is None:
                    raise MissingOperation(key)
                operation = resolve_operation(await state.catalog(), operation_id)
                assert operation is not None
                if item_id is not None:
                    values["invitation_id" if invitation else "principal_id"] = str(item_id)
                outcome = await execute_operation(
                    state, operation, bearer=session.access_token, form=values
                )
            except (httpx.HTTPError, MissingOperation, ValueError):
                outcome = local_error(503, "operation_unavailable", "Owner action unavailable")
        return state.templates.TemplateResponse(
            request,
            "partials/result.html",
            state.context(
                request,
                result=outcome.to_view(),
                form_id=f"owner-{key}",
            ),
        )

    async def invite(request: Request) -> Response:
        return await run(request, "invite")

    async def owner_action(request: Request, principal_id: UUID, action_key: str) -> Response:
        return await run(request, action_key, item_id=principal_id)

    async def invitation_action(request: Request, invitation_id: UUID, action_key: str) -> Response:
        return await run(request, action_key, item_id=invitation_id, invitation=True)

    for path, endpoint in (
        ("/resources/owners", owners),
        ("/resources/owners/invitations", invitations),
        ("/resources/owners/invitations/{invitation_id}", invitation_detail),
        ("/resources/owners/{principal_id}", owner_detail),
    ):
        app.add_api_route(path, endpoint, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/resources/owners/actions/invite", invite, methods=["POST"])
    app.add_api_route(
        "/resources/owners/invitations/{invitation_id}/actions/{action_key}",
        invitation_action,
        methods=["POST"],
    )
    app.add_api_route(
        "/resources/owners/{principal_id}/actions/{action_key}",
        owner_action,
        methods=["POST"],
    )
