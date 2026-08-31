from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.booking.api.dependencies import IdempotencyKey
from request_engine.modules.booking.api.models import ArrivalEstimateBody, ArrivalEstimateView
from request_engine.modules.booking.application.authority import SUBJECT_OVERRIDE_PERMISSION
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
    RecordArrivalEstimateHandler,
    record_arrival_estimate,
)
from request_engine.modules.booking.contracts.arrival_estimates import ArrivalEstimateSource
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def add_arrival_estimate_routes(
    router: APIRouter,
    handler: RecordArrivalEstimateHandler,
    actor_resolver: ActorResolver,
) -> None:
    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def arrival_estimate(
        reservation_id: UUID,
        body: ArrivalEstimateBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ArrivalEstimateView:
        require_capability(actor, "appointments.record_arrival_estimate")
        estimate = await record_arrival_estimate(
            handler,
            RecordArrivalEstimateCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                estimated_arrival_at=body.estimated_arrival_at,
                source_kind=ArrivalEstimateSource(body.source_kind),
                idempotency_key=idempotency_key,
                expected_revision=body.expected_revision,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return ArrivalEstimateView.from_contract(estimate)

    add_capability_route(
        router,
        "/{reservation_id}/arrival-estimate",
        arrival_estimate,
        capability="appointments.record_arrival_estimate",
        methods=["POST"],
        response_model=ArrivalEstimateView,
    )
