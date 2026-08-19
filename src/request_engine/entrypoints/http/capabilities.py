from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.discovery import (
    BaselineTenantCapabilityPolicy,
    CapabilityAvailability,
    TenantCapabilityPolicy,
    discover_capabilities,
)
from request_engine.platform.security.http import ActorResolver


class CapabilityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    schema_version: int
    kind: str
    exposure: str
    description: str
    idempotency: str
    expected_revision: str
    party_scope: str | None
    override_capability: str | None
    product_supported: bool
    runtime_available: bool
    tenant_enabled: bool
    actor_granted: bool
    openapi_operation_id: str | None

    @classmethod
    def from_availability(cls, item: CapabilityAvailability) -> "CapabilityView":
        definition = item.definition
        return cls(
            key=definition.key,
            schema_version=definition.schema_version,
            kind=definition.kind.value,
            exposure=definition.exposure.value,
            description=definition.description,
            idempotency=definition.idempotency.value,
            expected_revision=definition.revision.value,
            party_scope=definition.party_scope,
            override_capability=definition.override_capability,
            product_supported=item.product_supported,
            runtime_available=definition.runtime_available,
            tenant_enabled=item.tenant_enabled,
            actor_granted=item.actor_granted,
            openapi_operation_id=(
                definition.key.replace(".", "_") if definition.runtime_available else None
            ),
        )


class CapabilityCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: tuple[CapabilityView, ...]


def create_capability_router(
    *,
    actor_resolver: ActorResolver,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["capabilities"])
    policy = tenant_capability_policy or BaselineTenantCapabilityPolicy()

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def capabilities(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> CapabilityCatalogView:
        discovered = await discover_capabilities(actor, policy)
        return CapabilityCatalogView(
            capabilities=tuple(CapabilityView.from_availability(item) for item in discovered)
        )

    router.add_api_route(
        "/capabilities",
        capabilities,
        methods=["GET"],
        response_model=CapabilityCatalogView,
        operation_id="capabilities_list",
        openapi_extra={"x-request-engine-discovery": True},
    )
    return router
