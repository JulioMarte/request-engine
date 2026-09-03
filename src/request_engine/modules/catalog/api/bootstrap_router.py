from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    CatalogBootstrapHandler,
    ChannelPolicyInput,
    CreateOfferingCommand,
    CreateResourceCapabilityCommand,
    OfferingRequirementInput,
    ReservationPolicyInput,
    create_offering,
    create_resource_capability,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ResourceCapabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    capability_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)


class OfferingRequirementBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: UUID
    quantity: int = Field(default=1, ge=1)


class ChannelPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: tuple[Literal["email", "phone", "sms", "voice", "whatsapp"], ...]
    provider_key: str | None = Field(default=None, min_length=1, max_length=128)
    reconcile_after_seconds: int = Field(default=300, ge=30, le=86400)
    retry_after_seconds: int = Field(default=60, ge=30, le=86400)


class ReservationPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: bool = False
    reminders_before_minutes: tuple[int, ...] = ()
    channel_policy: ChannelPolicyBody | None = None
    attendance_confirmation_required: bool = False
    attendance_request_before_minutes: int | None = Field(default=None, gt=0)
    decline_action: Literal["keep", "cancel"] = "keep"
    no_show_after_minutes: int | None = Field(default=None, gt=0)
    slot_recovery_enabled: bool = False
    slot_recovery_minimum_lead_minutes: int = Field(default=30, gt=0)


class OfferingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    offering_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    duration_minutes: int = Field(gt=0, le=1440)
    bookable: bool = True
    requestable: bool = True
    slot_step_minutes: int = Field(default=30, gt=0, le=1440)
    requirements: tuple[OfferingRequirementBody, ...] = ()
    reservation_policy: ReservationPolicyBody = ReservationPolicyBody()


def create_bootstrap_router(
    *,
    handler: CatalogBootstrapHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def capability(
        body: ResourceCapabilityBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "catalog.manage")
        return await create_resource_capability(
            handler,
            CreateResourceCapabilityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                capability_key=body.capability_key,
                display_name=body.display_name,
                idempotency_key=idempotency_key,
            ),
        )

    async def offering(
        body: OfferingBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "catalog.manage")
        policy = body.reservation_policy
        channel_policy = (
            ChannelPolicyInput(
                channels=policy.channel_policy.channels,
                provider_key=policy.channel_policy.provider_key,
                reconcile_after_seconds=policy.channel_policy.reconcile_after_seconds,
                retry_after_seconds=policy.channel_policy.retry_after_seconds,
            )
            if policy.channel_policy is not None
            else None
        )
        return await create_offering(
            handler,
            CreateOfferingCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                offering_key=body.offering_key,
                display_name=body.display_name,
                description=body.description,
                duration_minutes=body.duration_minutes,
                bookable=body.bookable,
                requestable=body.requestable,
                slot_step_minutes=body.slot_step_minutes,
                requirements=tuple(
                    OfferingRequirementInput(item.capability_id, item.quantity)
                    for item in body.requirements
                ),
                reservation_policy=ReservationPolicyInput(
                    confirmation=policy.confirmation,
                    reminders_before_minutes=policy.reminders_before_minutes,
                    channel_policy=channel_policy,
                    attendance_confirmation_required=policy.attendance_confirmation_required,
                    attendance_request_before_minutes=policy.attendance_request_before_minutes,
                    decline_action=policy.decline_action,
                    no_show_after_minutes=policy.no_show_after_minutes,
                    slot_recovery_enabled=policy.slot_recovery_enabled,
                    slot_recovery_minimum_lead_minutes=(policy.slot_recovery_minimum_lead_minutes),
                ),
                idempotency_key=idempotency_key,
            ),
        )

    add_capability_route(
        router,
        "/resource-capabilities",
        capability,
        capability="catalog.manage",
        methods=["POST"],
        operation_id="catalog_manage_resource_capabilities",
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/offerings",
        offering,
        capability="catalog.manage",
        methods=["POST"],
        operation_id="catalog_manage_offerings",
        status_code=status.HTTP_201_CREATED,
    )
    return router
