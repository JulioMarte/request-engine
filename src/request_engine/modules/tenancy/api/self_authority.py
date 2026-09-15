from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.queries.self_authority import (
    AuthorityInspectionDenied,
    SelfAuthorityQuery,
    SelfAuthorityReader,
)
from request_engine.modules.tenancy.contracts.authority import AuthorityKind
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class SelfAuthorityParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class CurrentRepresentationView(BaseModel):
    representation_id: UUID
    represented_party_id: UUID
    scope_key: str
    authority_kind: AuthorityKind
    revision: int
    valid_from: datetime
    valid_until: datetime | None


class SelfAuthorityView(BaseModel):
    principal_id: UUID
    authority_revision: int
    observed_at: datetime
    representations: list[CurrentRepresentationView]
    next_after: UUID | None
    requires_owner_validation: Literal[True] = True


async def self_authority_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AuthorityInspectionDenied):
        raise exc
    return JSONResponse(
        status_code=403,
        headers={"Cache-Control": "no-store"},
        content=ErrorEnvelope(
            error=ErrorBody(
                code="authority_inspection_denied",
                message="the current actor may not inspect this authority snapshot",
                resolution=ErrorResolution.REQUEST_AUTHORITY,
            )
        ).model_dump(mode="json"),
    )


def create_self_authority_router(
    *, reader: SelfAuthorityReader, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter(prefix="/v1/me", tags=["authority"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def read_self(
        params: Annotated[SelfAuthorityParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> SelfAuthorityView:
        require_capability(actor, "authority.read_self")
        result = await reader.read_self(actor, SelfAuthorityQuery(params.after, params.limit))
        response.headers["Cache-Control"] = "no-store"
        return SelfAuthorityView(
            principal_id=result.principal_id,
            authority_revision=result.authority_revision,
            observed_at=result.observed_at,
            representations=[
                CurrentRepresentationView(
                    representation_id=item.representation_id,
                    represented_party_id=item.represented_party_id,
                    scope_key=item.scope_key,
                    authority_kind=item.authority_kind,
                    revision=item.revision,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                )
                for item in result.representations
            ],
            next_after=result.next_after,
        )

    add_capability_route(
        router,
        "/authority",
        read_self,
        methods=["GET"],
        capability="authority.read_self",
        operation_id="authority_read_self",
        owner="tenancy",
        response_model=SelfAuthorityView,
    )
    return router
