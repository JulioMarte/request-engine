"""Recipient enrollment and personal security; neither creates platform authority."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.session import (
    AdminSession,
    FileSessionStore,
    new_csrf_token,
    session_expiry,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_ENROLL_PATH = "/owner-invitations/enroll"
_SECURITY_PATH = "/account/security"


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def install_owner_enrollment_routes(app: FastAPI, state: AdminConsoleState) -> None:
    # Separate private namespace: this anonymous state cannot be read as login or first-run setup.
    anonymous = FileSessionStore(
        state.settings.session_store_directory / "owner-enrollment", state.secret
    )
    cookie_name = state.settings.session_cookie_name + "_owner_enroll"

    def enrollment_page(request: Request, *, error: str = "", status: int = 200) -> Response:
        stored = anonymous.read(request.cookies.get(cookie_name, ""), "setup")
        if stored is None:
            stored = AdminSession(
                "", new_csrf_token(), session_expiry(state.settings.setup_ttl_seconds)
            )
            handle = anonymous.create(stored, "setup")
        else:
            handle = ""
        response = state.templates.TemplateResponse(
            request,
            "owner_enrollment.html",
            state.context(
                request,
                enrollment_csrf=stored.csrf_token,
                error=error,
                enrolled=False,
            ),
            status_code=status,
        )
        if handle:
            response.set_cookie(
                cookie_name,
                handle,
                max_age=state.settings.setup_ttl_seconds,
                httponly=True,
                secure=state.settings.cookie_secure,
                samesite=cast(Literal["lax", "strict", "none"], state.settings.cookie_samesite),
                path=_ENROLL_PATH,
            )
        return response

    async def enrollment_get(request: Request) -> Response:
        return enrollment_page(request)

    async def enrollment_post(request: Request) -> Response:
        if request.headers.get("X-Requested-With") != "fetch":
            return JSONResponse(
                {"error": "Active JavaScript para enviar este formulario privado de forma segura."},
                status_code=400,
            )
        stored = anonymous.read(request.cookies.get(cookie_name, ""), "setup")
        form = await request.form()
        if stored is None or not state.csrf_matches(
            str(form.get("csrf_token", "")), stored.csrf_token
        ):
            return enrollment_page(
                request,
                error="Este formulario de invitación venció. Envíe el formulario nuevo.",
                status=403,
            )
        payload = {
            key: str(form.get(key, "")) for key in ("invitation_token", "login_handle", "password")
        }
        if not all(payload.values()):
            return enrollment_page(
                request,
                error="Debe completar el código de invitación, el usuario y la contraseña.",
                status=422,
            )
        try:
            response = await state.control_request(
                "POST",
                "/v1/platform/owner-invitations:enroll",
                json_body=payload,
            )
        except httpx.TimeoutException:
            return enrollment_page(
                request,
                error=(
                    "No se pudo confirmar el resultado. Intente iniciar sesión con su cuenta "
                    "nueva antes de enviar la invitación otra vez."
                ),
                status=503,
            )
        except httpx.HTTPError:
            return enrollment_page(
                request,
                error="El servicio de inscripción no está disponible. Inténtelo más tarde.",
                status=503,
            )
        if not response.ok:
            return enrollment_page(
                request,
                error=(
                    "No se pudo completar la inscripción con esta invitación. Consulte con el "
                    "dueño que le invitó. No se otorgó ningún permiso en la plataforma."
                ),
                status=response.status_code if response.status_code in (401, 409, 422) else 503,
            )
        body = as_mapping(response.payload)
        if not _uuid(body.get("native_identity_id")) or not _uuid(body.get("invitation_id")):
            return enrollment_page(
                request,
                error=(
                    "El resultado de la inscripción llegó incompleto. Intente iniciar sesión "
                    "antes de enviar la invitación otra vez."
                ),
                status=502,
            )
        anonymous.revoke(request.cookies.get(cookie_name, ""), "setup")
        result = state.templates.TemplateResponse(
            request,
            "owner_enrollment.html",
            state.context(request, enrolled=True, error=""),
        )
        result.delete_cookie(cookie_name, path=_ENROLL_PATH)
        return result

    async def security_get(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login?next=/account/security", status_code=303)
        try:
            response = await state.control_request(
                "GET",
                "/auth/native/sessions/current/recovery-readiness",
                bearer=session.access_token,
            )
        except httpx.HTTPError:
            response = None
        readiness = as_mapping(response.payload) if response is not None and response.ok else {}
        valid = (
            all(
                type(readiness.get(field)) is int and readiness[field] >= 0
                for field in ("remaining_codes", "active_webauthn_credentials")
            )
            and type(readiness.get("active_code_set")) is bool
            and isinstance(readiness.get("recovery_state"), str)
            and bool(readiness["recovery_state"].strip())
        )
        return state.templates.TemplateResponse(
            request,
            "account_security.html",
            state.context(
                request,
                readiness=readiness if valid else {},
                available=valid,
                codes=None,
                error=""
                if valid
                else (
                    "No se pudo verificar la seguridad de su cuenta. Inicie sesión de nuevo "
                    "o inténtelo otra vez."
                ),
            ),
            status_code=200 if valid else 503,
        )

    async def passkey_proxy(request: Request, *, complete: bool) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "Inicie sesión de nuevo."}, status_code=401)
        try:
            body = as_mapping(await request.json())
        except ValueError:
            return JSONResponse({"error": "Solicitud no válida."}, status_code=400)
        if not state.csrf_matches(str(body.get("csrf_token", "")), session.csrf_token):
            return JSONResponse(
                {"error": "El formulario de seguridad venció. Recargue la página."}, status_code=403
            )
        credential = body.get("credential")
        if complete and not isinstance(credential, dict):
            return JSONResponse({"error": "Falta la llave de acceso."}, status_code=422)
        try:
            response = await state.control_request(
                "POST",
                "/auth/native/sessions/current/webauthn/"
                + ("registrations" if complete else "registration-options"),
                bearer=session.access_token,
                json_body={"credential": as_mapping(credential)} if complete else None,
            )
        except httpx.HTTPError:
            return JSONResponse(
                {"error": "El servicio de llaves de acceso no está disponible."}, status_code=503
            )
        if not response.ok:
            return JSONResponse(
                {
                    "error": (
                        "No se pudo registrar la llave de acceso. Inténtelo otra vez o inicie "
                        "sesión de nuevo."
                    )
                },
                status_code=response.status_code,
            )
        if complete:
            if not _uuid(as_mapping(response.payload).get("credential_id")):
                return JSONResponse(
                    {
                        "error": (
                            "El registro de la llave de acceso llegó incompleto. "
                            "Recargue Seguridad de la cuenta."
                        )
                    },
                    status_code=502,
                )
            return JSONResponse({"ok": True})
        public_key = as_mapping(response.payload).get("public_key")
        if not isinstance(public_key, dict):
            return JSONResponse(
                {"error": "Las opciones de la llave de acceso llegaron incompletas."},
                status_code=502,
            )
        return JSONResponse({"public_key": as_mapping(public_key)})

    async def recovery_complete_password(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "Inicie sesión de nuevo."}, status_code=401)
        if not state.csrf_matches(request.headers.get("X-CSRF-Token"), session.csrf_token):
            return JSONResponse(
                {"error": "El formulario de seguridad venció. Recargue la página."}, status_code=403
            )
        try:
            body = as_mapping(await request.json())
        except ValueError:
            return JSONResponse({"error": "Escriba su contraseña actual."}, status_code=422)
        password = body.get("password")
        if set(body) != {"password"} or not isinstance(password, str) or not password:
            return JSONResponse({"error": "Escriba su contraseña actual."}, status_code=422)
        response = await state.control_request(
            "POST",
            "/auth/native/sessions/current/recovery:complete",
            bearer=session.access_token,
            json_body={"password": password},
        )
        if not response.ok:
            return JSONResponse(content=response.payload, status_code=response.status_code)
        result = as_mapping(response.payload)
        if (
            not isinstance(result.get("completed_at"), str)
            or not result["completed_at"]
            or not isinstance(result.get("recovery_state"), str)
            or result["recovery_state"] == "recovery_restricted"
        ):
            return JSONResponse(
                {"error": "La recuperación no se completó del todo."}, status_code=502
            )
        return JSONResponse({"ok": True, "requires_sign_in": True})

    async def passkey_options(request: Request) -> Response:
        return await passkey_proxy(request, complete=False)

    async def passkey_complete(request: Request) -> Response:
        return await passkey_proxy(request, complete=True)

    async def recovery_codes(request: Request) -> Response:
        if request.headers.get("X-Requested-With") != "fetch":
            return JSONResponse(
                {"error": "Active JavaScript para generar los códigos de forma segura."},
                status_code=400,
            )
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login?next=/account/security", status_code=303)
        form = await request.form()
        if not state.csrf_matches(str(form.get("csrf_token", "")), session.csrf_token):
            return JSONResponse(
                {"error": "El formulario de seguridad venció. Recargue la página."}, status_code=403
            )
        try:
            response = await state.control_request(
                "POST",
                "/auth/native/sessions/current/recovery-codes",
                bearer=session.access_token,
            )
        except httpx.HTTPError:
            return JSONResponse(
                {
                    "error": (
                        "No se confirmó si se generaron los códigos. "
                        "Recargue Seguridad de la cuenta antes de intentarlo otra vez."
                    )
                },
                status_code=503,
            )
        if not response.ok:
            return state.templates.TemplateResponse(
                request,
                "account_security.html",
                state.context(
                    request,
                    readiness={},
                    available=False,
                    codes=None,
                    error=(
                        "No se pudieron generar los códigos. Confirme su sesión actual, "
                        "recargue Seguridad de la cuenta e inténtelo otra vez."
                    ),
                ),
                status_code=response.status_code,
            )
        values = as_mapping(response.payload).get("codes")
        codes: list[str] = (
            [str(value) for value in cast(list[Any], values)]
            if isinstance(values, list)
            and all(
                isinstance(value, str) and bool(value.strip()) for value in cast(list[Any], values)
            )
            else []
        )
        if not codes:
            return JSONResponse(
                {
                    "error": (
                        "La generación de códigos llegó incompleta. "
                        "Recargue Seguridad de la cuenta."
                    )
                },
                status_code=502,
            )
        return state.templates.TemplateResponse(
            request,
            "account_security.html",
            state.context(
                request,
                readiness={},
                available=False,
                codes=codes,
                error="",
            ),
        )

    app.add_api_route(_ENROLL_PATH, enrollment_get, methods=["GET"])
    app.add_api_route(_ENROLL_PATH, enrollment_post, methods=["POST"])
    app.add_api_route(_SECURITY_PATH, security_get, methods=["GET"])
    app.add_api_route(_SECURITY_PATH + "/passkey/options", passkey_options, methods=["POST"])
    app.add_api_route(_SECURITY_PATH + "/passkey/complete", passkey_complete, methods=["POST"])
    app.add_api_route(_SECURITY_PATH + "/recovery-codes", recovery_codes, methods=["POST"])
    app.add_api_route(
        _SECURITY_PATH + "/recovery-complete", recovery_complete_password, methods=["POST"]
    )
