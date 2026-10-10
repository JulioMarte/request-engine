import base64
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict

from request_engine.modules.requests.api.definition_models import (
    CreateRequestDefinitionBody,
    PublishRequestDefinitionVersionBody,
    RequestDefinitionPageView,
    RequestDefinitionView,
    RequestInboxItemView,
    RequestInboxPageView,
    SetRequestDefinitionActiveBody,
)
from request_engine.modules.requests.application.commands.manage_definition import (
    CreateRequestDefinitionCommand,
    PublishRequestDefinitionVersionCommand,
    RequestDefinitionCommands,
    SetRequestDefinitionActiveCommand,
)
from request_engine.modules.requests.application.errors import (
    RequestDefinitionNotFound,
    RequestPayloadInvalid,
)
from request_engine.modules.requests.application.queries.admin_reads import (
    RequestAdministrationReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


class RequestReadCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: UUID
    collection: Literal["definitions", "inbox"]
    last_id: UUID
    created_at: AwareDatetime | None = None
    status: Literal["open", "completed", "cancelled", "failed"] | None = None


def _cursor(value: RequestReadCursorParams) -> str:
    return base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()


def _position(
    cursor: str | None,
    organization_id: UUID,
    collection: str,
    status: str | None = None,
) -> RequestReadCursorParams | None:
    if cursor is None:
        return None
    try:
        value = RequestReadCursorParams.model_validate_json(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
    except ValueError:
        raise RequestPayloadInvalid("$.cursor", "invalid cursor") from None
    if (
        value.organization_id != organization_id
        or value.collection != collection
        or value.status != status
        or (collection == "inbox" and value.created_at is None)
    ):
        raise RequestPayloadInvalid("$.cursor", "cursor does not match tenant and filters")
    return value


def _closed_query(request: Request, allowed: set[str]) -> None:
    if set(request.query_params) - allowed:
        raise RequestPayloadInvalid("$", "unsupported query parameter")


def create_administration_router(
    commands: RequestDefinitionCommands,
    reader: RequestAdministrationReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(tags=["requests"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_definition(
        body: CreateRequestDefinitionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RequestDefinitionView:
        require_capability(current, "requests.create_definition")
        state = await commands.create_definition(
            CreateRequestDefinitionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **body.model_dump(),
            )
        )
        return RequestDefinitionView.model_validate(state)

    async def publish_version(
        definition_id: UUID,
        body: PublishRequestDefinitionVersionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RequestDefinitionView:
        require_capability(current, "requests.publish_definition_version")
        state = await commands.publish_version(
            PublishRequestDefinitionVersionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                definition_id=definition_id,
                idempotency_key=key,
                **body.model_dump(),
            )
        )
        return RequestDefinitionView.model_validate(state)

    async def set_active(
        definition_id: UUID,
        body: SetRequestDefinitionActiveBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RequestDefinitionView:
        require_capability(current, "requests.set_definition_active")
        state = await commands.set_active(
            SetRequestDefinitionActiveCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                definition_id=definition_id,
                idempotency_key=key,
                **body.model_dump(),
            )
        )
        return RequestDefinitionView.model_validate(state)

    async def list_definitions(
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> RequestDefinitionPageView:
        require_capability(current, "requests.read_definitions")
        response.headers["Cache-Control"] = "no-store"
        _closed_query(request, {"limit", "cursor"})
        position = _position(cursor, current.organization_id, "definitions")
        rows = await reader.list_definitions(
            current.organization_id,
            principal_id=current.principal_id,
            limit=limit + 1,
            after_id=position.last_id if position else None,
        )
        page = rows[:limit]
        return RequestDefinitionPageView(
            items=tuple(RequestDefinitionView.model_validate(item) for item in page),
            next_cursor=_cursor(
                RequestReadCursorParams(
                    organization_id=current.organization_id,
                    collection="definitions",
                    last_id=page[-1].definition_id,
                )
            )
            if len(rows) > limit
            else None,
        )

    async def read_definition(
        definition_id: UUID,
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
        version: Annotated[int | None, Query(ge=1)] = None,
    ) -> RequestDefinitionView:
        require_capability(current, "requests.read_definitions")
        response.headers["Cache-Control"] = "no-store"
        _closed_query(request, {"version"})
        state = await reader.get_definition(
            current.organization_id, definition_id, version, principal_id=current.principal_id
        )
        if state is None:
            raise RequestDefinitionNotFound(str(definition_id), version)
        return RequestDefinitionView.model_validate(state)

    async def inbox(
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[str | None, Query(max_length=2000)] = None,
        status: Literal["open", "completed", "cancelled", "failed"] | None = None,
    ) -> RequestInboxPageView:
        require_capability(current, "requests.read_inbox")
        response.headers["Cache-Control"] = "no-store"
        _closed_query(request, {"limit", "cursor", "status"})
        position = _position(cursor, current.organization_id, "inbox", status)
        rows = await reader.list_inbox(
            current.organization_id,
            principal_id=current.principal_id,
            limit=limit + 1,
            status=status,
            after_id=position.last_id if position else None,
            after_created_at=position.created_at if position else None,
        )
        page = rows[:limit]
        return RequestInboxPageView(
            items=tuple(RequestInboxItemView.model_validate(item) for item in page),
            next_cursor=_cursor(
                RequestReadCursorParams(
                    organization_id=current.organization_id,
                    collection="inbox",
                    last_id=page[-1].request_id,
                    created_at=page[-1].created_at,
                    status=status,
                )
            )
            if len(rows) > limit
            else None,
        )

    for path, endpoint, method, capability, operation_id, model, code in (
        (
            "/v1/request-definitions",
            create_definition,
            "POST",
            "requests.create_definition",
            "request_definition_create",
            RequestDefinitionView,
            201,
        ),
        (
            "/v1/request-definitions/{definition_id}/versions",
            publish_version,
            "POST",
            "requests.publish_definition_version",
            "request_definition_version_publish",
            RequestDefinitionView,
            201,
        ),
        (
            "/v1/request-definitions/{definition_id}:set-active",
            set_active,
            "POST",
            "requests.set_definition_active",
            "request_definition_set_active",
            RequestDefinitionView,
            200,
        ),
        (
            "/v1/request-definitions",
            list_definitions,
            "GET",
            "requests.read_definitions",
            "request_definitions_list",
            RequestDefinitionPageView,
            200,
        ),
        (
            "/v1/request-definitions/{definition_id}",
            read_definition,
            "GET",
            "requests.read_definitions",
            "request_definition_read",
            RequestDefinitionView,
            200,
        ),
        (
            "/v1/requests",
            inbox,
            "GET",
            "requests.read_inbox",
            "requests_list_inbox",
            RequestInboxPageView,
            200,
        ),
    ):
        responses = {
            422: {"model": ErrorEnvelope, "description": "Invalid input or cursor"},
        }
        if method == "POST":
            responses[409] = {
                "model": ErrorEnvelope,
                "description": "Definition conflict, stale revision or idempotency intent conflict",
            }
        if endpoint in (publish_version, set_active, read_definition):
            responses[404] = {
                "model": ErrorEnvelope,
                "description": "Definition or version not found",
            }
        add_capability_route(
            router,
            path,
            endpoint,
            capability=capability,
            methods=[method],
            operation_id=operation_id,
            response_model=model,
            status_code=code,
            responses=responses,
        )
    return router
