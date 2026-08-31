from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.operational_recovery.api.models import RecoveryProposalView
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

READ_CAPABILITY = "operational_copilot.read"


def create_tool_recovery_proposal_router(
    *,
    actor_resolver: ActorResolver,
    proposal_reader: RecoveryProposalReader,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot/tools", tags=["operational-copilot-tools"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def proposal(
        proposal_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RecoveryProposalView:
        require_capability(current, READ_CAPABILITY)
        value = await proposal_reader.get_proposal(
            organization_id=current.organization_id,
            proposal_id=proposal_id,
        )
        return RecoveryProposalView.from_contract(value)

    add_capability_route(
        router,
        "/recovery/proposals/{proposal_id}",
        proposal,
        capability=READ_CAPABILITY,
        methods=["GET"],
        operation_id="copilot_recovery_proposal",
        response_model=RecoveryProposalView,
    )
    return router
