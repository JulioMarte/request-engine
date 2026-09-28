"""First-run instance setup and claim wizard.

Projects the control-plane ``/v1/setup`` ceremony. The short-lived setup bearer is
held only in a signed HttpOnly cookie and never reaches browser JavaScript.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote_plus

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


async def _safe_json(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return {}


def _idempotency_key(token: str) -> str:
    return "admin-console-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _error_text(response: Any) -> str:
    body = response.error_body
    if body is not None and isinstance(body.get("code"), str):
        return str(body["code"])
    return f"control_error_{response.status_code}"


def install_setup_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def discovery() -> dict[str, Any]:
        try:
            response = await state.control_request("GET", "/v1/setup")
        except httpx.HTTPError:
            return {
                "initialized": False,
                "setup_required": False,
                "detail": "control plane unreachable",
            }
        if response.status_code == 503:
            return {
                "initialized": False,
                "setup_required": False,
                "detail": "instance not initialized",
            }
        if not response.ok:
            return {
                "initialized": False,
                "setup_required": False,
                "detail": f"discovery failed ({response.status_code})",
            }
        return {
            "initialized": True,
            "setup_required": as_mapping(response.payload).get("setup_required") is True,
            "detail": "",
        }

    async def setup_page(request: Request, step: str = "start") -> Response:
        info = await discovery()
        setup = state.setup(request)
        return state.templates.TemplateResponse(
            request,
            "setup.html",
            state.context(
                request,
                step=step,
                initialized=info["initialized"],
                setup_required=info["setup_required"],
                discovery_detail=info["detail"],
                has_setup_session=setup is not None,
                setup_csrf=setup.csrf if setup is not None else "",
                error=request.query_params.get("error"),
                notice=request.query_params.get("notice"),
                codes=None,
                claim=None,
            ),
        )

    async def create_setup_session() -> Response:
        response = await state.control_request("POST", "/v1/setup/sessions")
        if not response.ok:
            return RedirectResponse(
                f"/setup?error={quote_plus(_error_text(response))}", status_code=303
            )
        token = as_mapping(response.payload).get("token")
        if not isinstance(token, str) or not token:
            return RedirectResponse("/setup?error=setup+session+had+no+token", status_code=303)
        redirect = RedirectResponse("/setup?step=identity", status_code=303)
        state.attach_setup(redirect, token)
        return redirect

    async def set_identity(request: Request) -> Response:
        setup = state.setup(request)
        form = await request.form()
        if setup is None or not state.csrf_matches(str(form.get("csrf_token", "")), setup.csrf):
            return RedirectResponse("/setup?error=setup+session+expired", status_code=303)
        login_handle = str(form.get("login_handle", "")).strip()
        password = str(form.get("password", ""))
        response = await state.control_request(
            "POST",
            "/v1/setup/native-identity",
            setup_bearer=setup.token,
            json_body={"login_handle": login_handle, "password": password},
        )
        if not response.ok:
            return RedirectResponse(
                f"/setup?error={quote_plus(_error_text(response))}", status_code=303
            )
        return RedirectResponse("/setup?step=passkey", status_code=303)

    async def setup_webauthn_options(request: Request) -> Response:
        setup = state.setup(request)
        if setup is None:
            return JSONResponse({"error": "setup session expired"}, status_code=401)
        response = await state.control_request(
            "POST",
            "/v1/setup/webauthn/registration-options",
            setup_bearer=setup.token,
        )
        return JSONResponse(content=response.payload, status_code=response.status_code)

    async def setup_webauthn_complete(request: Request) -> Response:
        setup = state.setup(request)
        if setup is None:
            return JSONResponse({"error": "setup session expired"}, status_code=401)
        body = as_mapping(await _safe_json(request))
        credential = body.get("credential")
        if not isinstance(credential, dict):
            return JSONResponse({"error": "credential is required"}, status_code=400)
        response = await state.control_request(
            "POST",
            "/v1/setup/webauthn/registrations",
            setup_bearer=setup.token,
            json_body={"credential": as_mapping(credential)},
        )
        if not response.ok:
            return JSONResponse(content=response.payload, status_code=response.status_code)
        return JSONResponse({"ok": True})

    async def issue_recovery_codes(request: Request) -> Response:
        setup = state.setup(request)
        if setup is None:
            return RedirectResponse("/setup?error=setup+session+expired", status_code=303)
        response = await state.control_request(
            "POST",
            "/v1/setup/recovery-codes",
            setup_bearer=setup.token,
        )
        if not response.ok:
            return RedirectResponse(
                f"/setup?error={quote_plus(_error_text(response))}", status_code=303
            )
        codes = [str(item) for item in as_list(as_mapping(response.payload).get("codes"))]
        info = await discovery()
        return state.templates.TemplateResponse(
            request,
            "setup.html",
            state.context(
                request,
                step="recovery",
                initialized=info["initialized"],
                setup_required=info["setup_required"],
                discovery_detail=info["detail"],
                has_setup_session=True,
                setup_csrf=setup.csrf,
                error=None,
                notice="Store these recovery codes now. They are shown once.",
                codes=codes,
                claim=None,
            ),
        )

    async def finalize(request: Request) -> Response:
        setup = state.setup(request)
        form = await request.form()
        if setup is None or not state.csrf_matches(str(form.get("csrf_token", "")), setup.csrf):
            return RedirectResponse("/setup?error=setup+session+expired", status_code=303)
        claim_provenance = str(form.get("claim_provenance", "")).strip()
        response = await state.control_request(
            "POST",
            "/v1/setup:finalize",
            setup_bearer=setup.token,
            json_body={"claim_provenance": claim_provenance},
            extra_headers={"idempotency-key": _idempotency_key(setup.token)},
        )
        if not response.ok:
            return RedirectResponse(
                f"/setup?error={quote_plus(_error_text(response))}", status_code=303
            )
        result = state.templates.TemplateResponse(
            request,
            "setup.html",
            state.context(
                request,
                step="done",
                initialized=True,
                setup_required=False,
                discovery_detail="",
                has_setup_session=False,
                setup_csrf="",
                error=None,
                notice="Instance claimed. Sign in with the new Platform Owner credentials.",
                codes=None,
                claim=as_mapping(response.payload),
            ),
        )
        state.clear_setup(result)
        return result

    app.add_api_route("/setup", setup_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/setup/session", create_setup_session, methods=["POST"])
    app.add_api_route("/setup/identity", set_identity, methods=["POST"])
    app.add_api_route("/setup/webauthn/options", setup_webauthn_options, methods=["POST"])
    app.add_api_route("/setup/webauthn/complete", setup_webauthn_complete, methods=["POST"])
    app.add_api_route(
        "/setup/recovery-codes",
        issue_recovery_codes,
        methods=["POST"],
        response_class=HTMLResponse,
    )
    app.add_api_route("/setup/finalize", finalize, methods=["POST"], response_class=HTMLResponse)


__all__ = ["install_setup_routes"]
