"""Owner admission for Resource rename, capability replacement and absence deactivation.

Plausible defects: a blank/control-character label or duplicated capability ids
reaching the handler, a deactivation without the exception it targets, or the
routes losing their stable owner/capability/idempotency metadata.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from request_engine.modules.booking.adapters.db import resource_schedule_exception_codec as codec
from request_engine.modules.booking.api.operational_exception_router import ResourceExceptionBody
from request_engine.modules.booking.api.resource_configuration_router import (
    ResourceCapabilitiesBody,
    ResourceUpdateBody,
    create_resource_configuration_router,
)
from request_engine.modules.booking.application.commands.replace_resource_capabilities import (
    ReplaceResourceCapabilitiesCommand,
    replace_resource_capabilities,
)
from request_engine.modules.booking.application.commands.update_resource import (
    UpdateResourceCommand,
    update_resource,
)


class _Unreachable:
    async def update_resource(self, command: object) -> object:
        raise AssertionError("invalid input reached the handler")

    async def replace_resource_capabilities(self, command: object) -> object:
        raise AssertionError("invalid input reached the handler")


def _update(display_name: str, revision: int = 1) -> UpdateResourceCommand:
    return UpdateResourceCommand(uuid4(), uuid4(), uuid4(), uuid4(), display_name, revision, "k")


def _replace(ids: tuple[UUID, ...], revision: int = 1) -> ReplaceResourceCapabilitiesCommand:
    return ReplaceResourceCapabilitiesCommand(
        uuid4(), uuid4(), uuid4(), uuid4(), ids, revision, "k"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   ", "Dr.\nX", "x" * 201])
async def test_invalid_resource_labels_never_reach_the_handler(name: str) -> None:
    with pytest.raises(ValueError):
        await update_resource(cast(Any, _Unreachable()), _update(name))


@pytest.mark.asyncio
async def test_invalid_capability_sets_never_reach_the_handler() -> None:
    same = uuid4()
    with pytest.raises(ValueError, match="repeat"):
        await replace_resource_capabilities(cast(Any, _Unreachable()), _replace((same, same)))
    with pytest.raises(ValueError, match="at most"):
        await replace_resource_capabilities(
            cast(Any, _Unreachable()), _replace(tuple(uuid4() for _ in range(51)))
        )
    with pytest.raises(ValueError, match="positive"):
        await replace_resource_capabilities(cast(Any, _Unreachable()), _replace((), 0))


def test_transport_bodies_reject_invalid_input_and_trim_labels() -> None:
    party = str(uuid4())
    body = ResourceUpdateBody.model_validate(
        {
            "authority_party_id": party,
            "display_name": "  Consultorio 2 ",
            "expected_resource_availability_revision": 3,
        }
    )
    assert body.display_name == "Consultorio 2"
    same = str(uuid4())
    with pytest.raises(ValidationError):
        ResourceCapabilitiesBody.model_validate(
            {
                "authority_party_id": party,
                "capability_ids": [same, same],
                "expected_resource_availability_revision": 1,
            }
        )
    with pytest.raises(ValidationError):
        ResourceUpdateBody.model_validate(
            {
                "authority_party_id": party,
                "display_name": "x",
                "expected_resource_availability_revision": 1,
                "resource_key": "smuggled",
            }
        )


def test_resource_absence_deactivation_requires_the_target_exception() -> None:
    base = {
        "authority_party_id": str(uuid4()),
        "start_at": "2030-01-07T13:00:00Z",
        "end_at": "2030-01-07T16:00:00Z",
        "exception_kind": "unavailable",
        "expected_resource_availability_revision": 1,
        "active": False,
    }
    with pytest.raises(ValidationError, match="exception_id"):
        ResourceExceptionBody.model_validate(base)
    accepted = ResourceExceptionBody.model_validate({**base, "exception_id": str(uuid4())})
    assert accepted.active is False
    assert ResourceExceptionBody.model_validate({**base, "active": True}).active is True


def test_receipts_written_before_active_existed_replay_as_active() -> None:
    legacy: dict[str, object] = {
        "exception_id": str(uuid4()),
        "resource_id": str(uuid4()),
        "start_at": datetime(2030, 1, 7, 13, tzinfo=UTC).isoformat(),
        "end_at": datetime(2030, 1, 7, 16, tzinfo=UTC).isoformat(),
        "exception_kind": "unavailable",
        "reason": None,
        "resource_availability_revision": 4,
    }
    assert codec.from_json(legacy).active is True
    assert codec.from_json({**legacy, "active": False}).active is False


def test_routes_publish_stable_owner_operation_policy() -> None:
    app = FastAPI()
    app.include_router(
        create_resource_configuration_router(
            update_handler=cast(Any, object()),
            capabilities_handler=cast(Any, object()),
            actor_resolver=cast(Any, object()),
        )
    )
    paths = app.openapi()["paths"]
    for path, method, operation_id in (
        ("/v1/operations/resources/{resource_id}", "patch", "booking_resource_update"),
        (
            "/v1/operations/resources/{resource_id}/capabilities",
            "put",
            "booking_resource_capabilities_replace",
        ),
    ):
        operation = paths[path][method]
        assert operation["operationId"] == operation_id
        assert operation["x-request-engine-owner"] == "booking"
        assert operation["x-request-engine-capability"] == "booking.manage_supply"
        assert operation["x-request-engine-kind"] == "command"
        assert operation["x-request-engine-idempotency"] == "required"
