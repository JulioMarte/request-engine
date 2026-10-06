from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as policy_commands,
)
from request_engine.modules.communications.application.queries.channel_configuration import (
    ChannelConfigurationQuery,
    ChannelConfigurationReader,
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


class ChannelPolicyView(BaseModel):
    purpose: str
    enabled: bool
    channel_policy: dict[str, object]
    revision: int


class ChannelConfigurationView(BaseModel):
    purpose: str
    configured: bool
    revision: int
    enabled: bool | None
    channel_policy: dict[str, object] | None


class ChannelConfigurationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID


def create_channel_policy_router(
    *,
    handler: policy_commands.SetOrganizationChannelPolicyHandler,
    actor_resolver: ActorResolver,
    reader: ChannelConfigurationReader | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/communications", tags=["communications"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def set_policy(
        purpose: PurposePath,
        body: SetChannelPolicyBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ChannelPolicyView:
        """Configure one purpose using the revision returned by its GET operation.

        Requires current operations.manage_profile Party authority. For an unconfigured
        purpose use expected_revision=0. Retry an uncertain result with the same
        Idempotency-Key and unchanged body; a new intent needs a new key.
        Current communications.configure standing authority, active Party and exact
        Representation are checked inside the owner transaction before every receipt
        lookup. Withdrawal denies new work and completed-result replay; it does not
        undo a Command admitted before the withdrawal.
        """
        require_capability(current, "communications.configure")
        result = await policy_commands.set_organization_channel_policy(
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
        return ChannelPolicyView(
            purpose=result.purpose,
            enabled=result.enabled,
            channel_policy=result.channel_policy,
            revision=result.revision,
        )

    async def read_policy(
        purpose: PurposePath,
        params: Annotated[ChannelConfigurationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ChannelConfigurationView:
        """Read the current policy before configuring this purpose.

        Requires current operations.manage_profile Party authority. Missing configuration
        returns configured=false, revision=0 and null settings; it does not imply an
        enabled default. Use that revision as expected_revision on the matching PUT.
        This read does not certify provider connectivity or actual message delivery.
        """
        require_capability(current, "communications.read_configuration")
        assert reader is not None
        result = await reader.read_configuration(
            ChannelConfigurationQuery(
                current.organization_id, current.principal_id, params.authority_party_id, purpose
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return ChannelConfigurationView(
            purpose=result.purpose,
            configured=result.configured,
            revision=result.revision,
            enabled=result.enabled,
            channel_policy=result.channel_policy,
        )

    add_capability_route(
        router,
        "/channel-policies/{purpose}",
        set_policy,
        capability="communications.configure",
        methods=["PUT"],
        operation_id="communications_configure_channel_policy",
        response_model=ChannelPolicyView,
    )
    if reader is not None:
        add_capability_route(
            router,
            "/channel-policies/{purpose}",
            read_policy,
            capability="communications.read_configuration",
            methods=["GET"],
            operation_id="communications_channel_policy_get",
            response_model=ChannelConfigurationView,
        )
    return router
