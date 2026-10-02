"""Self-only context discovery through the runtime API, never a platform directory."""

from typing import Literal
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError

from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


class _OrganizationChoice(BaseModel):
    organization_id: UUID
    display_name: str = Field(min_length=1)
    principal_id: UUID
    membership_id: UUID


class _OrganizationPage(BaseModel):
    items: list[_OrganizationChoice] = Field(max_length=100)
    next_after: UUID | None
    requires_owner_validation: Literal[True]


def install_my_organization_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def workspace(
        request: Request,
        after: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        page: _OrganizationPage | None = None
        status = 503
        error = "Your organizations are temporarily unavailable. Try again shortly."
        if state.runtime is not None:
            try:
                operation = (await state.runtime_catalog()).by_id().get("self_organization_list")
                if operation is not None and operation.method.upper() == "GET":
                    params = {"limit": str(limit)}
                    if after is not None:
                        params["after"] = str(after)
                    # Discovery precedes selection: do not attach a tenant header
                    # or forward any browser-supplied identity/authority inputs.
                    result = await state.runtime.request(
                        "GET", operation.path_template, bearer=session.access_token, params=params
                    )
                    if result.ok:
                        page = _OrganizationPage.model_validate(result.payload)
                        status, error = 200, ""
                    elif result.status_code == 401:
                        status, error = 401, "Your session is no longer valid. Sign in again."
                    elif result.status_code == 403:
                        status, error = 403, "This session cannot list organizations."
            except (httpx.HTTPError, ValidationError, ValueError, RuntimeError):
                pass
        return state.templates.TemplateResponse(
            request,
            "resources/my_organizations.html",
            state.context(
                request,
                organizations=page.items if page is not None else [],
                next_after=page.next_after if page is not None else None,
                after=after,
                page_limit=limit,
                error=error,
                loaded=page is not None,
            ),
            status_code=status,
        )

    app.add_api_route("/my-organizations", workspace, methods=["GET"])
