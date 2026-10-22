"""Approvals inbox: suggestions from agents that need a person to decide.

Today this projects staff invitation proposals (ADR 0019): an agent such as the
chief of staff proposes adding someone; a person with team authority approves
(creating the invitation through the owner operation) or rejects. Approval is
the owner's HUMAN, recent-authentication command; the console only carries the
exact proposal revision and a stable intent so a confirmation retry is safe.
"""

from __future__ import annotations

from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_STEP_UP_CODES = frozenset({"recent_authentication_required", "phishing_resistant_auth_required"})
_OPS = {
    "list": "staff_invitation_proposal_list",
    "approve": "staff_invitation_proposal_approve",
    "reject": "staff_invitation_proposal_reject",
}
APPROVAL_OPERATION_IDS = frozenset(_OPS.values())


def _proposer_label(item: dict[str, Any]) -> str:
    for key in ("proposer_display_name", "proposed_by_display_name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    proposer = as_mapping(item.get("proposer"))
    name = proposer.get("display_name")
    if isinstance(name, str) and name:
        return name
    kind = (
        item.get("proposed_by_principal_kind") or item.get("proposer_kind") or proposer.get("kind")
    )
    return "Un asistente" if kind == "agent" else "Un miembro del equipo"


def install_tenant_approval_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _operation(name: str):  # noqa: ANN202
        return (await state.runtime_catalog()).by_id().get(_OPS[name])

    async def inbox(request: Request, organization_id: UUID, done: str = "") -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(
                f"/login?next=/tenants/{organization_id}/approvals", status_code=303
            )
        org = str(organization_id)
        status, items, supported = 0, [], False
        if state.runtime is not None:
            try:
                operation = await _operation("list")
            except Exception:
                operation = None
            supported = operation is not None
            if operation is not None:
                try:
                    response = await state.runtime_request(
                        "GET",
                        operation.path_template,
                        organization_id=org,
                        bearer=session.access_token,
                        params={"status": "pending", "limit": "100"},
                    )
                    status = response.status_code
                    if response.ok:
                        items = [
                            dict(as_mapping(item))
                            for item in as_list(as_mapping(response.payload).get("items"))
                        ]
                except (httpx.HTTPError, RuntimeError):
                    status = 503
        if status == 401:
            redirect = login_redirect(request)
            state.clear_session(redirect, request)
            return redirect
        for item in items:
            item["proposer_label"] = _proposer_label(item)
        return state.templates.TemplateResponse(
            request,
            "resources/approvals.html",
            state.context(
                request,
                organization_id=org,
                supported=supported,
                status=status,
                proposals=items,
                intent=token_urlsafe(16),
                notice={
                    "approve": "Aprobado. Se envió la invitación.",
                    "reject": "Sugerencia rechazada.",
                }.get(done),
            ),
        )

    async def decide(
        request: Request, organization_id: UUID, proposal_id: UUID, decision: str
    ) -> Response:
        if decision not in {"approve", "reject"}:
            return Response(status_code=404)
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        if state.runtime is None:
            return Response("El sistema del negocio no está configurado.", status_code=503)
        org = str(organization_id)
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return Response(
                "El formulario venció. Vuelva a cargar la página e intente de nuevo.",
                status_code=403,
            )
        intent = values.get("intent", "")
        try:
            revision = int(values.get("expected_revision", ""))
        except ValueError:
            revision = 0
        if not 16 <= len(intent) <= 64 or revision < 1:
            return Response(
                "Este formulario venció. Vuelva a cargar las aprobaciones.", status_code=422
            )
        operation = await _operation(decision)
        if operation is None:
            return Response(
                "Las aprobaciones no están disponibles en esta instalación.", status_code=503
            )
        body: dict[str, object] = {
            "expected_revision": revision,
            "provenance_reference": f"admin-console:proposal-{decision}:{intent}",
        }
        if decision == "reject" and values.get("reason", "").strip():
            body["reason"] = values["reason"].strip()[:500]
        path = operation.path_template.replace("{proposal_id}", quote(str(proposal_id), safe=""))
        try:
            response = await state.runtime_request(
                operation.method.upper(),
                path,
                organization_id=org,
                bearer=session.access_token,
                json_body=body,
                extra_headers={"Idempotency-Key": f"{intent}:{decision}"},
            )
            status, payload, code = (
                response.status_code,
                response.payload,
                response.error_code or "",
            )
        except (httpx.HTTPError, RuntimeError):
            status, payload, code = 503, None, "outcome_unknown"
        if 200 <= status < 300:
            return RedirectResponse(f"/tenants/{org}/approvals?done={decision}", status_code=303)
        message = as_mapping(as_mapping(payload).get("error")).get("message")
        return state.templates.TemplateResponse(
            request,
            "resources/approval_failed.html",
            state.context(
                request,
                organization_id=org,
                proposal_id=str(proposal_id),
                decision=decision,
                status=status,
                error_code=code,
                message=message if isinstance(message, str) else "",
                step_up=code in _STEP_UP_CODES,
                retry_values=values,
            ),
            status_code=status if status >= 400 else 502,
        )

    app.add_api_route("/tenants/{organization_id}/approvals", inbox, methods=["GET"])
    app.add_api_route(
        "/tenants/{organization_id}/approvals/{proposal_id}/{decision}", decide, methods=["POST"]
    )


__all__ = ["APPROVAL_OPERATION_IDS", "install_tenant_approval_routes"]
