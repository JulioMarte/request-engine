import json
from uuid import uuid4

import pytest
from starlette.requests import Request

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import (
    AuthenticationRequired,
    CapabilityRequired,
    require_capability,
)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


@pytest.mark.asyncio
async def test_authentication_failure_has_stable_machine_readable_envelope() -> None:
    response = await authentication_required_handler(_request(), AuthenticationRequired())
    assert response.status_code == 401
    assert json.loads(response.body) == {
        "error": {
            "code": "authentication_required",
            "message": "authentication is required",
            "retryable": False,
            "details": {},
        }
    }


@pytest.mark.asyncio
async def test_capability_failure_names_exact_canonical_requirement() -> None:
    response = await capability_required_handler(
        _request(),
        CapabilityRequired("appointments.cancel"),
    )
    assert response.status_code == 403
    assert json.loads(response.body) == {
        "error": {
            "code": "capability_required",
            "message": "the authenticated actor lacks a required capability",
            "retryable": False,
            "details": {"capability": "appointments.cancel"},
        }
    }


def test_require_capability_accepts_registered_legacy_grant_but_reports_canonical_failure() -> None:
    legacy_actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"booking.cancel_reservation"}),
    )
    require_capability(legacy_actor, "appointments.cancel")

    unprivileged_actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
    )
    with pytest.raises(CapabilityRequired) as captured:
        require_capability(unprivileged_actor, "appointments.cancel")
    assert captured.value.capability == "appointments.cancel"
