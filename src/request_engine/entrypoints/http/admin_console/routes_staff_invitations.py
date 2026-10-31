"""Email invitations projected through Tenancy's canonical HTTP operations."""

import hashlib
import hmac
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import AwareDatetime, BaseModel, Field, StrictStr, ValidationError

from request_engine.entrypoints.http.admin_console.execution import execute_operation
from request_engine.entrypoints.http.admin_console.inputs import build_inputs
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.navigation import login_redirect
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


class _InvitationView(BaseModel):
    invitation_id: UUID
    organization_id: UUID
    email: StrictStr = Field(min_length=1)
    status: StrictStr = Field(min_length=1)
    generation: int = Field(strict=True, ge=1)
    revision: int = Field(strict=True, ge=1)
    expires_at: AwareDatetime
    created_at: AwareDatetime
    membership_id: UUID | None
    principal_id: UUID | None
    binding_id: UUID | None
    delivery_status: StrictStr | None


class _InvitationPage(BaseModel):
    items: list[_InvitationView] = Field(strict=True, max_length=100)
    next_after: UUID | None


def install_staff_invitation_routes(app: FastAPI, state: AdminConsoleState) -> None:
    def enrollment_csrf() -> str:
        nonce = token_urlsafe(24)
        return nonce + "." + hmac.new(state.secret, nonce.encode(), hashlib.sha256).hexdigest()

    async def enroll_page(request: Request) -> Response:
        csrf = enrollment_csrf()
        response = state.templates.TemplateResponse(
            request,
            "resources/invitation_enroll.html",
            state.context(request, enrollment_csrf=csrf),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
        response.set_cookie(
            "staff_enrollment_csrf",
            csrf,
            max_age=600,
            httponly=True,
            secure=state.settings.cookie_secure,
            samesite="strict",
            path="/staff-invitations/enroll",
        )
        return response

    async def enroll(request: Request) -> Response:
        form = await request.form()
        submitted = str(form.get("csrf_token", ""))
        cookie = request.cookies.get("staff_enrollment_csrf", "")
        nonce, _, signature = cookie.partition(".")
        expected = hmac.new(state.secret, nonce.encode(), hashlib.sha256).hexdigest()
        if not state.csrf_matches(submitted, cookie) or not hmac.compare_digest(
            signature, expected
        ):
            return Response(
                "El formulario venció. Recargue la página e inténtelo de nuevo.", status_code=403
            )
        if state.runtime is None:
            return Response("La creación de cuentas no está disponible", status_code=503)
        try:
            # Credentials are forwarded only to the canonical native auth owner.
            # Never echo them, attach organization context or create local identity.
            result = await state.runtime.request(
                "POST",
                "/auth/native/identities",
                json_body={
                    "login_handle": str(form.get("login_handle", "")),
                    "password": str(form.get("password", "")),
                },
            )
        except httpx.HTTPError:
            return Response(
                "No se confirmó si se creó la cuenta. "
                "Intente iniciar sesión antes de crearla otra vez.",
                status_code=503,
            )
        if not result.ok:
            return state.templates.TemplateResponse(
                request,
                "resources/invitation_enroll.html",
                state.context(
                    request,
                    enrollment_csrf=cookie,
                    error=(
                        "No se pudo crear la cuenta. "
                        "Revise los datos o inicie sesión si ya la tiene."
                    ),
                ),
                status_code=result.status_code,
            )
        response = RedirectResponse("/login?next=/staff-invitations/accept", status_code=303)
        response.delete_cookie("staff_enrollment_csrf", path="/staff-invitations/enroll")
        return response

    async def workspace(
        request: Request,
        organization_id: UUID,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        try:
            catalog = (await state.runtime_catalog()).by_id()
            operation = catalog.get("staff_invitation_list")
            create = catalog.get("staff_invitation_create")
            if operation is None or create is None:
                return Response("El servicio de invitaciones no está disponible", status_code=503)
            params = {"limit": str(limit)}
            if after:
                params["after"] = str(after)
            result = await state.runtime_request(
                operation.method,
                operation.path_template,
                organization_id=str(organization_id),
                bearer=session.access_token,
                params=params,
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            return Response("El servicio de invitaciones no está disponible", status_code=503)
        body = as_mapping(result.payload)
        rows: list[dict[str, Any]] = []
        if result.ok:
            try:
                page = _InvitationPage.model_validate(result.payload)
                if len(page.items) > limit or any(
                    item.organization_id != organization_id for item in page.items
                ):
                    raise ValueError("invitation page scope or size mismatch")
                body = page.model_dump(mode="json")
            except (ValidationError, ValueError):
                return Response(
                    "El servicio de invitaciones devolvió una respuesta no válida", status_code=502
                )
            for item in (as_mapping(value) for value in as_list(body["items"])):
                delivery_labels = {
                    "delivered": (
                        "Aceptado por el servidor de correo (no se confirmó que llegó a la bandeja)"
                    ),
                    "pending": "En cola para enviarse por correo",
                    "attempting": "Enviando el correo",
                    "retryable_failure": "Reintento de envío pendiente",
                    "unknown": "Resultado del envío desconocido; no dé por hecho que llegó",
                    "terminal_failure": "No se pudo enviar el correo",
                    "failed": "No se pudo enviar el correo",
                    "cancelled": "Envío cancelado",
                    "expired": "El envío venció antes de confirmarse",
                }
                item["delivery_label"] = delivery_labels.get(
                    str(item.get("delivery_status")), "Envío sin confirmar"
                )
                rows.append(
                    {
                        **item,
                        "intent_id": token_urlsafe(24),
                    }
                )
        next_after = body.get("next_after") if result.ok else None
        if next_after is not None:
            try:
                next_after = str(UUID(str(next_after)))
            except ValueError:
                return Response("La paginación de invitaciones no es válida", status_code=502)
        return state.templates.TemplateResponse(
            request,
            "resources/staff_invitations.html",
            state.context(
                request,
                organization_id=str(organization_id),
                invitations=rows,
                next_after=next_after,
                page_limit=limit,
                after=after,
                loaded=result.ok,
                error=""
                if result.ok
                else (
                    "Las invitaciones no están disponibles. "
                    "Revise su sesión y sus permisos, y luego recargue."
                ),
                create_inputs=build_inputs(create) if result.ok else [],
                create_intent=token_urlsafe(24),
            ),
            status_code=200 if result.ok else result.status_code,
        )

    async def mutate(
        request: Request,
        organization_id: UUID,
        invitation_id: UUID | None = None,
        action: str = "create",
    ) -> Response:
        session = state.session(request)
        if session is None:
            return login_redirect(request)
        if action not in ({"create"} if invitation_id is None else {"resend", "revoke"}):
            return Response("Acción de invitación desconocida", status_code=404)
        form = {key: str(value) for key, value in (await request.form()).items()}
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            return Response(
                "El formulario venció. Recargue la página e inténtelo de nuevo.", status_code=403
            )
        try:
            operation = (await state.runtime_catalog()).by_id().get(f"staff_invitation_{action}")
        except (httpx.HTTPError, RuntimeError, ValueError):
            return Response("El servicio de invitaciones no está disponible", status_code=503)
        if operation is None:
            return Response("La operación de invitación no está disponible", status_code=503)
        if invitation_id:
            form["invitation_id"] = str(invitation_id)
        outcome = await execute_operation(
            state,
            operation,
            bearer=session.access_token,
            form=form,
            surface="runtime",
            organization_id=str(organization_id),
        )
        if outcome.ok:
            return RedirectResponse(
                f"/tenants/{organization_id}/staff-invitations", status_code=303
            )
        return state.templates.TemplateResponse(
            request,
            "resources/invitation_failure.html",
            state.context(
                request,
                organization_id=str(organization_id),
                result=outcome.to_view(),
                retry_url=request.url.path,
                retry_form=form,
            ),
            status_code=outcome.status,
        )

    async def accept_page(request: Request, invitation_id: UUID | None = None) -> Response:
        # No query token is accepted or echoed: recipient secrets live only in the
        # browser fragment/tab storage until a CSRF-protected same-origin POST.
        return state.templates.TemplateResponse(
            request,
            "resources/invitation_accept.html",
            state.context(request),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def accept(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "Inicie sesión antes de aceptar."}, status_code=401)
        form = await request.form()
        if not state.csrf_matches(str(form.get("csrf_token", "")), session.csrf_token):
            return JSONResponse(
                {"error": "El formulario venció. Recargue la página e inténtelo de nuevo."},
                status_code=403,
            )
        token = str(form.get("token", ""))
        try:
            invitation_id = str(UUID(token.split(".", 1)[0]))
        except ValueError:
            return JSONResponse({"error": "El enlace de invitación no es válido."}, status_code=422)
        if not 40 <= len(token) <= 200 or "." not in token:
            return JSONResponse({"error": "El enlace de invitación no es válido."}, status_code=422)
        try:
            operation = (await state.runtime_catalog()).by_id().get("staff_invitation_accept")
            if state.runtime is None or operation is None or operation.method.upper() != "POST":
                return JSONResponse(
                    {"error": "El servicio de invitaciones no está disponible."}, status_code=503
                )
            # Acceptance precedes tenant membership. Deliberately bypass the
            # tenant-forwarding helper; neither actor nor tenant comes from form.
            result = await state.runtime.request(
                "POST",
                operation.path_template.replace("{invitation_id}", invitation_id),
                bearer=session.access_token,
                json_body={"token": token},
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            return JSONResponse(
                {
                    "error": (
                        "No se confirmó el resultado. Vuelva a intentarlo con este mismo enlace."
                    )
                },
                status_code=503,
            )
        if result.ok:
            return JSONResponse({"ok": True, "next": "/my-organizations"})
        error = as_mapping(as_mapping(result.payload).get("error"))
        if (
            result.status_code == 409
            and error.get("code") == "staff_invitation_identity_already_linked"
        ):
            return JSONResponse(
                {
                    "error": "Esta cuenta ya está vinculada a un negocio. Pida a un administrador "
                    "que revise su membresía y sus permisos actuales; otra invitación no le "
                    "devolverá el acceso."
                },
                status_code=409,
            )
        messages = {
            401: "Inicie sesión de nuevo y vuelva a abrir esta página.",
            403: "Esta cuenta no puede aceptar esta invitación.",
            404: "Este enlace de invitación no es válido o ya no está disponible.",
            409: "Esta invitación cambió, venció o fue revocada. Pida una invitación nueva.",
        }
        return JSONResponse(
            {"error": messages.get(result.status_code, "No se pudo aceptar la invitación.")},
            status_code=result.status_code,
        )

    async def preview(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse(
                {"error": "Inicie sesión para revisar esta invitación."}, status_code=401
            )
        form = await request.form()
        if not state.csrf_matches(str(form.get("csrf_token", "")), session.csrf_token):
            return JSONResponse(
                {"error": "El formulario venció. Recargue la página e inténtelo de nuevo."},
                status_code=403,
            )
        token = str(form.get("token", ""))
        try:
            invitation_id = str(UUID(token.split(".", 1)[0]))
        except ValueError:
            return JSONResponse({"error": "El enlace de invitación no es válido."}, status_code=422)
        if not 40 <= len(token) <= 200 or "." not in token:
            return JSONResponse({"error": "El enlace de invitación no es válido."}, status_code=422)
        try:
            operation = (await state.runtime_catalog()).by_id().get("staff_invitation_preview")
            if state.runtime is None or operation is None or operation.method.upper() != "POST":
                return JSONResponse(
                    {"error": "La vista previa de la invitación no está disponible."},
                    status_code=503,
                )
            result = await state.runtime.request(
                "POST",
                operation.path_template.replace("{invitation_id}", invitation_id),
                bearer=session.access_token,
                json_body={"token": token},
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            return JSONResponse(
                {"error": "No se pudo verificar la invitación. Inténtelo más tarde."},
                status_code=503,
            )
        body = as_mapping(result.payload)
        if not result.ok:
            return JSONResponse(
                {
                    "error": (
                        "La invitación no está disponible. "
                        "Inicie sesión de nuevo o pida un enlace nuevo."
                    )
                },
                status_code=result.status_code,
            )
        name = body.get("organization_display_name")
        expiry = body.get("expires_at")
        if not isinstance(name, str) or not name or not isinstance(expiry, str) or not expiry:
            return JSONResponse(
                {"error": "La vista previa de la invitación llegó incompleta."}, status_code=502
            )
        # Only the supported recipient projection crosses back to the browser.
        return JSONResponse(
            {"ok": True, "organization_display_name": name, "expires_at": expiry},
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route("/tenants/{organization_id}/staff-invitations", workspace, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/staff-invitations", mutate, methods=["POST"])
    app.add_api_route(
        "/tenants/{organization_id}/staff-invitations/{invitation_id}/{action}",
        mutate,
        methods=["POST"],
    )
    app.add_api_route("/staff-invitations/accept", accept_page, methods=["GET"])
    app.add_api_route("/staff-invitations/accept", accept, methods=["POST"])
    app.add_api_route("/staff-invitations/preview", preview, methods=["POST"])
    app.add_api_route("/staff-invitations/{invitation_id}/accept", accept_page, methods=["GET"])
    app.add_api_route("/staff-invitations/enroll", enroll_page, methods=["GET"])
    app.add_api_route("/staff-invitations/enroll", enroll, methods=["POST"])
