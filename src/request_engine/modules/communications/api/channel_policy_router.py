from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as policy_commands,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]

PurposePath = Literal[
    "appointment_confirmation",
    "appointment_reminder",
    "attendance_confirmation_request",
    "slot_offer_available",
    "operational_recovery_impact",
    "operational_recovery_rescheduled",
]


class SetChannelPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    enabled: bool
    channels: tuple[Literal["email", "phone", "sms", "voice", "whatsapp"], ...] = (
        "whatsapp",
        "sms",
        "email",
    )
    provider_key: str | None = Field(default=None, min_length=1, max_length=128)
    reconcile_after_seconds: int = Field(default=300, ge=30, le=86400)
    retry_after_seconds: int = Field(default=60, ge=30, le=86400)
    expected_revision: int = Field(ge=0)


def create_channel_policy_router(
    *,
    handler: policy_commands.SetOrganizationChannelPolicyHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/communications", tags=["communications"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def set_policy(
        purpose: PurposePath,
        body: SetChannelPolicyBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "communications.configure")
        return await policy_commands.set_organization_channel_policy(
            handler,
            policy_commands.SetOrganizationChannelPolicyCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                policy=policy_commands.OrganizationChannelPolicyInput(
                    purpose=purpose,
                    enabled=body.enabled,
                    channels=body.channels,
                    provider_key=body.provider_key,
                    reconcile_after_seconds=body.reconcile_after_seconds,
                    retry_after_seconds=body.retry_after_seconds,
                ),
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )

    add_capability_route(
        router,
        "/channel-policies/{purpose}",
        set_policy,
        capability="communications.configure",
        methods=["PUT"],
        operation_id="communications_configure_channel_policy",
    )
    return router
