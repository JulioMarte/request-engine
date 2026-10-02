"""Email invitations projected through Tenancy's canonical HTTP operations."""

import hashlib
import hmac
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.execution import execute_operation
from request_engine.entrypoints.http.admin_console.inputs import build_inputs
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


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
            return Response("CSRF token missing or invalid", status_code=403)
        if state.runtime is None:
            return Response("Native enrollment unavailable", status_code=503)
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
                "Enrollment result not confirmed. Try signing in before enrolling again.",
                status_code=503,
            )
        if not result.ok:
            return state.templates.TemplateResponse(
                request,
                "resources/invitation_enroll.html",
                state.context(
                    request,
                    enrollment_csrf=cookie,
                    error="Account could not be created. Check details or sign in if it exists.",
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
            return RedirectResponse("/login", status_code=303)
        try:
            catalog = (await state.runtime_catalog()).by_id()
            operation = catalog.get("staff_invitation_list")
            create = catalog.get("staff_invitation_create")
            if operation is None or create is None:
                return Response("Invitation API unavailable", status_code=503)
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
            return Response("Invitation service unavailable", status_code=503)
        body = as_mapping(result.payload)
        rows: list[dict[str, Any]] = []
        if result.ok:
            for value in as_list(body.get("items")):
                item = as_mapping(value)
                try:
                    invitation_id = str(UUID(str(item["invitation_id"])))
                    revision = int(item["revision"])
                except (KeyError, ValueError, TypeError):
                    return Response("Invalid invitation API response", status_code=502)
                if revision < 1:
                    return Response("Invalid invitation API revision", status_code=502)
                if item.get("membership_id") is not None:
                    try:
                        item["membership_id"] = str(UUID(str(item["membership_id"])))
                    except ValueError:
                        return Response("Invalid invitation membership", status_code=502)
                delivery_labels = {
                    "delivered": "Accepted by mail server (inbox not confirmed)",
                    "pending": "Queued for email delivery",
                    "attempting": "Email submission in progress",
                    "retryable_failure": "Delivery retry pending",
                    "unknown": "Delivery outcome unknown — do not assume receipt",
                    "terminal_failure": "Email delivery failed",
                    "failed": "Email delivery failed",
                    "cancelled": "Delivery cancelled",
                    "expired": "Delivery expired before confirmation",
                }
                item["delivery_label"] = delivery_labels.get(
                    str(item.get("delivery_status")), "Delivery not confirmed"
                )
                rows.append(
                    {
                        **item,
                        "invitation_id": invitation_id,
                        "revision": revision,
                        "intent_id": token_urlsafe(24),
                    }
                )
        next_after = body.get("next_after") if result.ok else None
        if next_after is not None:
            try:
                next_after = str(UUID(str(next_after)))
            except ValueError:
                return Response("Invalid invitation pagination", status_code=502)
        return state.templates.TemplateResponse(
            request,
            "resources/staff_invitations.html",
            state.context(
                request,
                organization_id=str(organization_id),
                invitations=rows,
                next_after=next_after,
                page_limit=limit,
                loaded=result.ok,
                error=""
                if result.ok
                else "Invitations unavailable. Check your session and permissions, then reload.",
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
            return RedirectResponse("/login", status_code=303)
        if action not in ({"create"} if invitation_id is None else {"resend", "revoke"}):
            return Response("Unknown invitation action", status_code=404)
        form = {key: str(value) for key, value in (await request.form()).items()}
        if not state.csrf_matches(form.get("csrf_token"), session.csrf_token):
            return Response("CSRF token missing or invalid", status_code=403)
        try:
            operation = (await state.runtime_catalog()).by_id().get(f"staff_invitation_{action}")
        except (httpx.HTTPError, RuntimeError, ValueError):
            return Response("Invitation API unavailable", status_code=503)
        if operation is None:
            return Response("Invitation operation unavailable", status_code=503)
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
            return JSONResponse({"error": "Sign in before accepting."}, status_code=401)
        form = await request.form()
        if not state.csrf_matches(str(form.get("csrf_token", "")), session.csrf_token):
            return JSONResponse({"error": "CSRF token missing or invalid"}, status_code=403)
        token = str(form.get("token", ""))
        try:
            invitation_id = str(UUID(token.split(".", 1)[0]))
        except ValueError:
            return JSONResponse({"error": "Invalid invitation link."}, status_code=422)
        if not 40 <= len(token) <= 200 or "." not in token:
            return JSONResponse({"error": "Invalid invitation link."}, status_code=422)
        try:
            operation = (await state.runtime_catalog()).by_id().get("staff_invitation_accept")
            if state.runtime is None or operation is None or operation.method.upper() != "POST":
                return JSONResponse({"error": "Invitation service unavailable."}, status_code=503)
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
                {"error": "Result not confirmed. Retry this same link."}, status_code=503
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
                    "error": "This account already has an organization link. Ask an administrator "
                    "to review your existing membership and permissions; another invitation "
                    "will not restore access."
                },
                status_code=409,
            )
        messages = {
            401: "Sign in again, then reopen this page.",
            403: "This account cannot accept this invitation.",
            404: "This invitation link is invalid or unavailable.",
            409: "This invitation changed, expired or was revoked. Ask for a new invitation.",
        }
        return JSONResponse(
            {"error": messages.get(result.status_code, "Invitation could not be accepted.")},
            status_code=result.status_code,
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
    app.add_api_route("/staff-invitations/{invitation_id}/accept", accept_page, methods=["GET"])
    app.add_api_route("/staff-invitations/enroll", enroll_page, methods=["GET"])
    app.add_api_route("/staff-invitations/enroll", enroll, methods=["POST"])
