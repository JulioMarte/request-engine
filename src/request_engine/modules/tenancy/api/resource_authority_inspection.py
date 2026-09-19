from collections.abc import Sequence
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.contracts.resource_authority import (
    ResourceAuthorityInspector,
    ResourceAuthorityOperation,
    ResourceAuthorityQuery,
    ResourceAuthorityTargetNotFound,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

RESOURCE_AUTHORITY_INSPECTION_CAPABILITY = "authority.inspect_resource"


class ResourceAuthorityInspectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(min_length=1, max_length=200)
    subject_party_id: UUID | None = None
    authority_party_id: UUID | None = None


class ResourceAuthorityDecisionView(BaseModel):
    operation: str
    decision: str
    reason_codes: list[str]
    authority_revision: int
    representation_revision: int | None
    requires_owner_validation: Literal[True] = True


class UnsupportedResourceAuthorityOperation(ValueError):
    """The named operation is unknown or no injected owner inspector supports it."""


class ResourceAuthorityInspectionInvalid(ValueError):
    """The typed inspection payload does not match the named operation."""


def create_resource_authority_inspection_router(
    *,
    inspectors: Sequence[ResourceAuthorityInspector],
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/me", tags=["authority"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def inspect_resource(
        body: ResourceAuthorityInspectBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> ResourceAuthorityDecisionView:
        require_capability(actor, RESOURCE_AUTHORITY_INSPECTION_CAPABILITY)
        try:
            operation = ResourceAuthorityOperation(body.operation)
        except ValueError:
            raise UnsupportedResourceAuthorityOperation(body.operation) from None
        inspector = next(
            (item for item in inspectors if operation.value in item.supported_operations),
            None,
        )
        if inspector is None:
            raise UnsupportedResourceAuthorityOperation(operation.value)
        try:
            query = ResourceAuthorityQuery(
                operation=operation,
                subject_party_id=body.subject_party_id,
                authority_party_id=body.authority_party_id,
            )
        except ValueError as exc:
            raise ResourceAuthorityInspectionInvalid(str(exc)) from None
        decision = await inspector.inspect(actor, query)
        response.headers["Cache-Control"] = "no-store"
        return ResourceAuthorityDecisionView(
            operation=operation.value,
            decision=decision.decision.value,
            reason_codes=list(decision.reason_codes),
            authority_revision=decision.authority_revision,
            representation_revision=decision.representation_revision,
        )

    add_capability_route(
        router,
        "/authority:inspect",
        inspect_resource,
        methods=["POST"],
        capability=RESOURCE_AUTHORITY_INSPECTION_CAPABILITY,
        operation_id="authority_inspect_resource",
        owner="tenancy",
        response_model=ResourceAuthorityDecisionView,
    )
    return router


def add_resource_authority_inspection_error_handlers(app: FastAPI) -> None:
    for error_type in (
        ResourceAuthorityTargetNotFound,
        UnsupportedResourceAuthorityOperation,
        ResourceAuthorityInspectionInvalid,
    ):
        app.add_exception_handler(error_type, resource_authority_inspection_error_handler)


async def resource_authority_inspection_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ResourceAuthorityTargetNotFound):
        return _error_response(
            http_status.HTTP_404_NOT_FOUND,
            "authority_inspection_not_found",
            "the target resource is not available in the current tenant",
            ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, UnsupportedResourceAuthorityOperation):
        return _error_response(
            http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            "authority_inspection_unsupported",
            "the requested operation is not a supported resource authority inspection",
            ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, ResourceAuthorityInspectionInvalid):
        return _error_response(
            http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            "authority_inspection_invalid",
            "the resource authority inspection request is invalid",
            ErrorResolution.FIX_REQUEST,
        )
    raise exc


def _error_response(
    status_code: int, code: str, message: str, resolution: ErrorResolution
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(code=code, message=message, resolution=resolution)
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
