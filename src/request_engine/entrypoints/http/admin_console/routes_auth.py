"""Console authentication routes: password login, passkey login and step-up.

The console stores the control-plane bearer only in its private session store;
these routes exchange credentials with the control plane and never hand the
bearer to the browser.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.session import (
    AdminSession,
    new_csrf_token,
    session_expiry,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


async def _safe_json(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return {}


def _proxy_json(response: Any) -> JSONResponse:
    status = response.status_code if 200 <= response.status_code < 600 else 502
    return JSONResponse(content=response.payload, status_code=status)


def _login_error(response: Any) -> str:
    body = response.error_body
    if body is not None and isinstance(body.get("message"), str):
        return str(body["message"])
    if response.status_code == 401:
        return "Invalid login or password"
    return f"Control plane rejected the login ({response.status_code})"


def _new_session(
    state: AdminConsoleState, access_token: str, upstream_expiry: object = None
) -> AdminSession:
    return AdminSession(
        access_token=access_token,
        csrf_token=new_csrf_token(),
        expires_at=session_expiry(state.settings.session_ttl_seconds, upstream_expiry),
    )


def _login_next(value: object) -> str:
    return "/staff-invitations/accept" if value == "/staff-invitations/accept" else "/"


def install_auth_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def login_page(request: Request) -> Response:
        # An unexpired local handle is not proof that its upstream bearer remains
        # valid. Always allow explicit reauthentication, including after revocation.
        return state.templates.TemplateResponse(
            request,
            "login.html",
            state.context(
                request,
                error=None,
                notice=None,
                next_url=_login_next(request.query_params.get("next")),
            ),
        )

    async def login(request: Request) -> Response:
        form = await request.form()
        next_url = _login_next(form.get("next"))
        login_handle = str(form.get("login_handle", "")).strip()
        password = str(form.get("password", ""))
        if not login_handle or not password:
            return state.templates.TemplateResponse(
                request,
                "login.html",
                state.context(
                    request, error="Login and password are required", notice=None, next_url=next_url
                ),
                status_code=400,
            )
        response = await state.control_request(
            "POST",
            "/auth/native/sessions",
            json_body={"login_handle": login_handle, "password": password},
        )
        if not response.ok:
            return state.templates.TemplateResponse(
                request,
                "login.html",
                state.context(
                    request, error=_login_error(response), notice=None, next_url=next_url
                ),
                status_code=401,
            )
        access_token = as_mapping(response.payload).get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return state.templates.TemplateResponse(
                request,
                "login.html",
                state.context(
                    request,
                    error="Control plane returned no session token",
                    notice=None,
                    next_url=next_url,
                ),
                status_code=502,
            )
        redirect = RedirectResponse(next_url, status_code=303)
        state.attach_session(
            redirect,
            _new_session(state, access_token, as_mapping(response.payload).get("expires_at")),
        )
        return redirect

    async def logout(request: Request) -> Response:
        session = state.session(request)
        redirect = RedirectResponse("/login", status_code=303)
        # Local logout is unconditional. An unavailable control plane must never
        # leave a browser believing it is still signed in.
        state.clear_session(redirect, request)
        if session is not None:
            with suppress(Exception):
                await state.control_request(
                    "DELETE",
                    "/auth/native/sessions/current",
                    bearer=session.access_token,
                )
        return redirect

    async def webauthn_login_options(request: Request) -> Response:
        body = as_mapping(await _safe_json(request))
        login_handle = str(body.get("login_handle", "")).strip()
        options_body: dict[str, object] = {}
        if login_handle:
            options_body["login_handle"] = login_handle
        response = await state.control_request(
            "POST",
            "/auth/native/webauthn/authentication-options",
            json_body=options_body,
        )
        return _proxy_json(response)

    async def webauthn_login_complete(request: Request) -> Response:
        body = as_mapping(await _safe_json(request))
        login_handle = str(body.get("login_handle", "")).strip()
        credential = body.get("credential")
        if not isinstance(credential, dict):
            return JSONResponse({"error": "credential is required"}, status_code=400)
        session_body: dict[str, object] = {"credential": as_mapping(credential)}
        if login_handle:
            session_body["login_handle"] = login_handle
        response = await state.control_request(
            "POST",
            "/auth/native/webauthn/sessions",
            json_body=session_body,
        )
        if not response.ok:
            return _proxy_json(response)
        access_token = as_mapping(response.payload).get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return JSONResponse(
                {"error": "control plane returned no session token"}, status_code=502
            )
        result = JSONResponse({"ok": True})
        state.attach_session(
            result,
            _new_session(state, access_token, as_mapping(response.payload).get("expires_at")),
        )
        return result

    async def step_up_options(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "authentication required"}, status_code=401)
        response = await state.control_request(
            "POST",
            "/auth/native/sessions/current/webauthn/step-up-options",
            bearer=session.access_token,
        )
        return _proxy_json(response)

    async def step_up_complete(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "authentication required"}, status_code=401)
        body = as_mapping(await _safe_json(request))
        credential = body.get("credential")
        if not isinstance(credential, dict):
            return JSONResponse({"error": "credential is required"}, status_code=400)
        response = await state.control_request(
            "POST",
            "/auth/native/sessions/current/webauthn/step-up",
            bearer=session.access_token,
            json_body={"credential": as_mapping(credential)},
        )
        return _proxy_json(response)

    app.add_api_route("/login", login_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/login", login, methods=["POST"], response_class=HTMLResponse)
    app.add_api_route("/logout", logout, methods=["POST"])
    app.add_api_route("/login/webauthn/options", webauthn_login_options, methods=["POST"])
    app.add_api_route("/login/webauthn/complete", webauthn_login_complete, methods=["POST"])
    app.add_api_route("/step-up/options", step_up_options, methods=["POST"])
    app.add_api_route("/step-up/complete", step_up_complete, methods=["POST"])


__all__ = ["install_auth_routes"]
