import asyncio
import json
from typing import cast
from uuid import uuid4

from fastapi import Request

from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.application.errors import AppointmentUnavailable


def _body_text(body: str | bytes | memoryview) -> str:
    if isinstance(body, str):
        return body
    return bytes(body).decode("utf-8")


def _response(reason: str) -> tuple[int, dict[str, object], str]:
    response = asyncio.run(
        booking_error_handler(cast(Request, object()), AppointmentUnavailable(reason))
    )
    raw = _body_text(response.body)
    return response.status_code, cast(dict[str, object], json.loads(raw)), raw


def test_local_and_cross_tenant_unavailability_are_publicly_indistinguishable() -> None:
    local_resource_id = uuid4()
    foreign_organization_id = uuid4()
    local = _response(f"Resource {local_resource_id} no longer has capacity")
    shared = _response(f"capacity unavailable foreign-org={foreign_organization_id}")

    assert local[:2] == shared[:2]
    assert local[0] == 409
    error = cast(dict[str, object], local[1]["error"])
    assert error["code"] == "appointment_unavailable"
    assert error["message"] == "the requested appointment is unavailable"
    assert error["details"] == {}
    assert str(local_resource_id) not in local[2]
    assert str(foreign_organization_id) not in shared[2]
