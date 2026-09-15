from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import ActorResolver
from request_engine.platform.security.operation_risk import agent_risk_permitted

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
    openapi_pointer: str
    party_scope: str | None = None
    override_capability: str | None = None
    tool_name: str | None = None
    tool_audiences: tuple[str, ...] = ()


class AuthorizedOperationCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: tuple[AuthorizedOperationView, ...]
    openapi_url: str | None = None
    requires_owner_validation: Literal[True] = True
    agent_policy_revision: int | None = None


def authorized_operations(
    openapi: dict[str, object],
    actor: ActorContext,
) -> tuple[AuthorizedOperationView, ...]:
    """Prefilter mounted operations; owner/Party/resource checks still apply."""

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
            definition = capability_definition(cast(str, capability))
            if definition is None or not definition.runtime_available:
                continue
            if actor.principal_kind is PrincipalKind.AGENT:
                policy = actor.agent_policy
                if (
                    policy is None
                    or definition.key not in policy.allowed_capabilities
                    or definition.key in policy.denied_capabilities
                    or not agent_risk_permitted(
                        definition.effective_risk_class, policy.risk_ceiling
                    )
                ):
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
                    openapi_pointer=(
                        "/paths/"
                        + path_template.replace("~", "~0").replace("/", "~1")
                        + "/"
                        + method
                    ),
                    party_scope=definition.party_scope,
                    override_capability=definition.override_capability,
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
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AuthorizedOperationCatalogView:
        openapi = cast(dict[str, object], request.app.openapi())
        response.headers["Cache-Control"] = "no-store"
        return AuthorizedOperationCatalogView(
            operations=authorized_operations(openapi, current),
            openapi_url=request.app.openapi_url,
            agent_policy_revision=(
                current.agent_policy.policy_revision if current.agent_policy is not None else None
            ),
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
