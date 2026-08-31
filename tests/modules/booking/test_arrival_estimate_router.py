from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import request_validation_error_handler
from request_engine.modules.booking.api.router import create_router
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
)
from request_engine.modules.booking.contracts.arrival_estimates import (
    ReservationArrivalEstimate,
)
from request_engine.platform.security.context import ActorContext


class _RecordingArrivalEstimateHandler:
    def __init__(self) -> None:
        self.commands: list[RecordArrivalEstimateCommand] = []

    async def record_arrival_estimate(
        self, command: RecordArrivalEstimateCommand
    ) -> ReservationArrivalEstimate:
        self.commands.append(command)
        raise AssertionError("arrival estimate command must not execute on invalid body")


class _FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


def _app(actor: ActorContext, handler: _RecordingArrivalEstimateHandler) -> FastAPI:
    unused: Any = object()
    router = create_router(
        availability_reader=unused,
        option_codec=unused,
        discovery_handoff_reader=unused,
        book_handler=unused,
        cancel_handler=unused,
        reschedule_handler=unused,
        attendance_handler=unused,
        arrival_estimate_handler=handler,
        reservation_reader=unused,
        authority_reader=unused,
        actor_resolver=_FixedActorResolver(actor),
    )
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    return app


@pytest.mark.asyncio
async def test_naive_arrival_timestamp_is_rejected_before_application_command() -> None:
    """A timezone-naive estimated_arrival_at must fail the transport input contract
    with the shared 422 validation_failed envelope, and never reach the application
    command as an ambiguous wall-clock value."""

    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"appointments.record_arrival_estimate"}),
    )
    handler = _RecordingArrivalEstimateHandler()
    app = _app(actor, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/appointments/{uuid4()}/arrival-estimate",
            json={
                "estimated_arrival_at": "2030-01-07T15:45:00",
                "expected_revision": 1,
            },
            headers={"Idempotency-Key": "arrival-estimate-router-naive-timestamp"},
        )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["resolution"] == "fix_request"
    assert [(item["location"], item["type"]) for item in error["details"]["fields"]] == [
        (["body", "estimated_arrival_at"], "value_error")
    ]
    assert handler.commands == []
