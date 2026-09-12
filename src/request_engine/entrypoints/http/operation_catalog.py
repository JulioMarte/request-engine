from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


class AuthorizedOperationView(BaseModel):
    """One mounted canonical HTTP operation visible to the current actor."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    owner: str
    capability: str
    kind: str
    exposure: str
    idempotency: str
    expected_revision: str
    method: str
    path_template: str
    tool_name: str | None = None
    tool_audiences: tuple[str, ...] = ()


class AuthorizedOperationCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: tuple[AuthorizedOperationView, ...]


def authorized_operations(
    openapi: dict[str, object],
    actor: ActorContext,
) -> tuple[AuthorizedOperationView, ...]:
    """Project canonical OpenAPI operations that the current actor may invoke."""

    paths_value = openapi.get("paths", {})
    if not isinstance(paths_value, dict):
        return ()

    operations: list[AuthorizedOperationView] = []
    for path_template, path_item_value in cast(dict[str, object], paths_value).items():
        if not isinstance(path_item_value, dict):
            continue
        path_item = cast(dict[str, object], path_item_value)
        for method, operation_value in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation_value, dict):
                continue
            operation = cast(dict[str, object], operation_value)
            capability = operation.get("x-request-engine-capability")
            owner = operation.get("x-request-engine-owner")
            operation_id = operation.get("x-request-engine-operation-id")
            kind = operation.get("x-request-engine-kind")
            exposure = operation.get("x-request-engine-exposure")
            idempotency = operation.get("x-request-engine-idempotency")
            revision = operation.get("x-request-engine-expected-revision")
            if not all(
                isinstance(value, str)
                for value in (
                    capability,
                    owner,
                    operation_id,
                    kind,
                    exposure,
                    idempotency,
                    revision,
                )
            ):
                continue
            if not actor.allows(cast(str, capability)):
                continue

            tool_name = operation.get("x-request-engine-tool-name")
            audiences_value = operation.get("x-request-engine-tool-audiences", [])
            if isinstance(audiences_value, list):
                audience_items = cast(list[object], audiences_value)
                audiences = tuple(item for item in audience_items if isinstance(item, str))
            else:
                audiences = ()
            operations.append(
                AuthorizedOperationView(
                    operation_id=cast(str, operation_id),
                    owner=cast(str, owner),
                    capability=cast(str, capability),
                    kind=cast(str, kind),
                    exposure=cast(str, exposure),
                    idempotency=cast(str, idempotency),
                    expected_revision=cast(str, revision),
                    method=method.upper(),
                    path_template=path_template,
                    tool_name=tool_name if isinstance(tool_name, str) else None,
                    tool_audiences=audiences,
                )
            )

    return tuple(sorted(operations, key=lambda item: item.operation_id))


def create_operation_catalog_router(*, actor_resolver: ActorResolver) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["operations-discovery"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def catalog(
        request: Request,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AuthorizedOperationCatalogView:
        openapi = cast(dict[str, object], request.app.openapi())
        return AuthorizedOperationCatalogView(
            operations=authorized_operations(openapi, current),
        )

    router.add_api_route(
        "/operation-catalog",
        catalog,
        methods=["GET"],
        response_model=AuthorizedOperationCatalogView,
        operation_id="operation_catalog_list_authorized",
        openapi_extra={"x-request-engine-discovery": True},
    )
    return router


__all__ = [
    "AuthorizedOperationCatalogView",
    "AuthorizedOperationView",
    "authorized_operations",
    "create_operation_catalog_router",
]
