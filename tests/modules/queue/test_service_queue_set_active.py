"""Transport/command admission and OpenAPI policy of ``queue_service_queue_set_active``.

Protected risks: an unknown body field, non-positive revision or missing key
reaching the owner handler; the route losing its explicit operation identity,
owner, capability or required idempotency; owner conflicts mapping to 500.
"""

import json
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from request_engine.modules.queue.api.errors import queue_error_handler
from request_engine.modules.queue.api.service_queue_activation_router import (
    SetServiceQueueActiveBody,
    create_service_queue_activation_router,
)
from request_engine.modules.queue.application.commands.set_service_queue_active import (
    ServiceQueueActivationState,
    SetServiceQueueActiveCommand,
    set_service_queue_active,
)
from request_engine.modules.queue.application.errors import (
    ServiceQueueHasActiveEntries,
    ServiceQueueRevisionConflict,
    ServiceQueueStateUnchanged,
)

pytestmark = [pytest.mark.contract]


class _Handler:
    def __init__(self) -> None:
        self.calls = 0

    async def set_service_queue_active(
        self, command: SetServiceQueueActiveCommand
    ) -> ServiceQueueActivationState:
        self.calls += 1
        return ServiceQueueActivationState(
            command.queue_id, "q", "Q", None, None, command.active, command.expected_revision + 1
        )


class _Resolver:
    async def resolve_actor(self, request: object) -> object:
        raise AssertionError("not used while building OpenAPI")


def _command(**overrides: Any) -> SetServiceQueueActiveCommand:
    values: dict[str, Any] = {
        "organization_id": uuid4(),
        "principal_id": uuid4(),
        "authority_party_id": uuid4(),
        "queue_id": uuid4(),
        "expected_revision": 1,
        "active": False,
        "idempotency_key": "key",
    }
    values.update(overrides)
    return SetServiceQueueActiveCommand(**values)


@pytest.mark.parametrize(
    "body",
    [
        {"expected_revision": 1, "active": False},
        {"authority_party_id": str(uuid4()), "expected_revision": 0, "active": False},
        {"authority_party_id": str(uuid4()), "expected_revision": 1},
        {
            "authority_party_id": str(uuid4()),
            "expected_revision": 1,
            "active": False,
            "drain": True,
        },
    ],
)
def test_body_rejects_incomplete_or_unknown_input(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SetServiceQueueActiveBody.model_validate(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"idempotency_key": ""}, {"expected_revision": 0}])
async def test_command_rejects_before_handler(overrides: dict[str, Any]) -> None:
    handler = _Handler()
    with pytest.raises(ValueError):
        await set_service_queue_active(handler, _command(**overrides))
    assert handler.calls == 0


def test_route_publishes_canonical_command_policy() -> None:
    app = FastAPI()
    app.include_router(
        create_service_queue_activation_router(
            handler=_Handler(), actor_resolver=cast(Any, _Resolver())
        )
    )
    operation = app.openapi()["paths"]["/v1/queues/{queue_id}:set-active"]["post"]
    assert operation["operationId"] == "queue_service_queue_set_active"
    assert operation["x-request-engine-owner"] == "queue"
    assert operation["x-request-engine-capability"] == "queue.configure"
    assert operation["x-request-engine-kind"] == "command"
    assert operation["x-request-engine-idempotency"] == "required"


@pytest.mark.asyncio
async def test_owner_conflicts_map_to_stable_409_codes() -> None:
    queue_id = uuid4()
    cases = {
        "service_queue_revision_conflict": ServiceQueueRevisionConflict(queue_id, 1, 2),
        "service_queue_state_unchanged": ServiceQueueStateUnchanged(queue_id, False),
        "service_queue_has_active_entries": ServiceQueueHasActiveEntries(queue_id, 2, 1, 0),
    }
    bodies: dict[str, dict[str, Any]] = {}
    for code, error in cases.items():
        response = await queue_error_handler(cast(Any, None), error)
        body = json.loads(bytes(response.body))["error"]
        assert (response.status_code, body["code"]) == (409, code)
        assert body["details"]["queue_id"] == str(queue_id)
        bodies[code] = body
    assert bodies["service_queue_has_active_entries"]["details"] == {
        "queue_id": str(queue_id),
        "waiting": 2,
        "called": 1,
        "serving": 0,
    }
