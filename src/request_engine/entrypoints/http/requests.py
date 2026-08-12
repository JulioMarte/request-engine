from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.entrypoints.http.request_models import (
    CancelRequestBody,
    CompleteRequestBody,
    FailRequestBody,
    RecordRequestResultBody,
    RequestView,
    SubmitRequestBody,
    SubmittedRequestView,
)
from request_engine.entrypoints.http.security import ActorResolver, AuthenticationRequired
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.adapters.db.request_definition_reader import (
    PostgresRequestDefinitionResolver,
)
from request_engine.modules.requests.adapters.db.request_reader import PostgresRequestReader
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
    cancel_request,
)
from request_engine.modules.requests.application.commands.complete_request import (
    CompleteRequestCommand,
    complete_request,
)
from request_engine.modules.requests.application.commands.create_request import (
    CreateRequestCommand,
    create_request,
)
from request_engine.modules.requests.application.commands.fail_request import (
    FailRequestCommand,
    fail_request,
)
from request_engine.modules.requests.application.commands.record_request_result import (
    RecordRequestResultCommand,
    record_request_result,
)
from request_engine.modules.requests.application.queries.get_request_status import (
    get_request_status,
)
from request_engine.modules.requests.application.queries.resolve_request_definition import (
    resolve_request_definition,
)
from request_engine.modules.requests.contracts.request import (
    ExternalCorrelationInput,
    RequestParticipantInput,
)
from request_engine.platform.security.context import ActorContext

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_requests_router(
    *,
    commands: PostgresRequestCommands,
    reader: PostgresRequestReader,
    definition_resolver: PostgresRequestDefinitionResolver,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/requests", tags=["requests"])

    async def authenticated_actor(request: Request) -> ActorContext:
        try:
            return await actor_resolver.resolve_actor(request)
        except AuthenticationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            ) from exc

    async def submit_request(
        request_key: str,
        body: SubmitRequestBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> SubmittedRequestView:
        _require(actor, "requests.submit")
        resolved = await resolve_request_definition(
            definition_resolver,
            organization_id=actor.organization_id,
            request_key=request_key,
            version=body.definition_version,
        )
        request = await create_request(
            commands,
            CreateRequestCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                request_definition_version_id=resolved.id,
                payload=body.payload,
                requester_party_id=body.requester_party_id,
                recipient_party_id=body.recipient_party_id,
                participants=tuple(
                    RequestParticipantInput(
                        party_id=item.party_id,
                        role_key=item.role_key,
                    )
                    for item in body.participants
                ),
                correlations=tuple(
                    ExternalCorrelationInput(
                        correlation_kind=item.correlation_kind,
                        provider_key=item.provider_key,
                        external_key=item.external_key,
                    )
                    for item in body.correlations
                ),
                idempotency_key=idempotency_key,
            ),
        )
        return SubmittedRequestView(
            request_key=resolved.request_key,
            definition_version=resolved.version,
            request=RequestView.from_contract(request),
        )

    async def read_request(
        request_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> RequestView:
        _require(actor, "requests.read")
        request = await get_request_status(
            reader,
            organization_id=actor.organization_id,
            request_id=request_id,
        )
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )
        return RequestView.from_contract(request)

    async def record_result(
        request_id: UUID,
        body: RecordRequestResultBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RequestView:
        _require(actor, "requests.record_result")
        request = await record_request_result(
            commands,
            RecordRequestResultCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                request_id=request_id,
                result_payload=body.result_payload,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return RequestView.from_contract(request)

    async def complete(
        request_id: UUID,
        body: CompleteRequestBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RequestView:
        _require(actor, "requests.complete")
        request = await complete_request(
            commands,
            CompleteRequestCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                request_id=request_id,
                result_payload=body.result_payload,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return RequestView.from_contract(request)

    async def cancel(
        request_id: UUID,
        body: CancelRequestBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RequestView:
        _require(actor, "requests.cancel")
        request = await cancel_request(
            commands,
            CancelRequestCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                request_id=request_id,
                reason=body.reason,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return RequestView.from_contract(request)

    async def fail(
        request_id: UUID,
        body: FailRequestBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RequestView:
        _require(actor, "requests.fail")
        request = await fail_request(
            commands,
            FailRequestCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                request_id=request_id,
                error_class=body.error_class,
                details=body.details,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return RequestView.from_contract(request)

    router.add_api_route(
        "/definitions/{request_key}/submit",
        submit_request,
        methods=["POST"],
        response_model=SubmittedRequestView,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/{request_id}",
        read_request,
        methods=["GET"],
        response_model=RequestView,
    )
    router.add_api_route(
        "/{request_id}/result",
        record_result,
        methods=["POST"],
        response_model=RequestView,
    )
    router.add_api_route(
        "/{request_id}/complete",
        complete,
        methods=["POST"],
        response_model=RequestView,
    )
    router.add_api_route(
        "/{request_id}/cancel",
        cancel,
        methods=["POST"],
        response_model=RequestView,
    )
    router.add_api_route(
        "/{request_id}/fail",
        fail,
        methods=["POST"],
        response_model=RequestView,
    )
    return router


def _require(actor: ActorContext, capability: str) -> None:
    if not actor.allows(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"capability {capability!r} is required",
        )
