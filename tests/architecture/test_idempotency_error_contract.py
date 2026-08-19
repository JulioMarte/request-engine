import json

import pytest
from starlette.requests import Request

from request_engine.entrypoints.http.errors import idempotency_conflict_handler
from request_engine.platform.idempotency.errors import IdempotencyConflict


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


@pytest.mark.asyncio
async def test_idempotency_conflict_requires_corrected_command_identity() -> None:
    response = await idempotency_conflict_handler(
        _request(),
        IdempotencyConflict("appointments.cancel", "reuse-key"),
    )
    assert response.status_code == 409
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": "idempotency_conflict",
            "message": "the idempotency key was already used for a different command",
            "retryable": False,
            "resolution": "fix_request",
            "details": {
                "capability": "appointments.cancel",
                "idempotency_key": "reuse-key",
            },
        }
    }
