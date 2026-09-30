import httpx
import pytest

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.execution import execute_operation


class _TimeoutState:
    async def control_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ReadTimeout("response lost", request=request)


def _operation() -> AdminOperation:
    return AdminOperation(
        operation_id="example_mutation",
        method="post",
        path_template="/v1/example",
        summary="Example",
        description="",
        tags=("test",),
        capability="example.write",
        kind="command",
        idempotency="required",
        exposure="private",
        owner="test",
        tool_name=None,
        tool_audiences=(),
        auth_kind="bearer",
        console_flow=None,
        parameters=(),
        body_schema=None,
    )


@pytest.mark.asyncio
async def test_timeout_is_ambiguous_and_preserves_stable_intent_key() -> None:
    intent = "stable-intent-123"
    outcome = await execute_operation(
        _TimeoutState(),
        _operation(),
        bearer="synthetic-token",
        form={"_intent_id": intent},
    )

    assert outcome.status == 504
    assert outcome.ok is False
    assert outcome.error_code == "outcome_unknown"
    assert outcome.idempotency_key == intent
    assert "may have completed" in outcome.message.lower()
    assert "nothing was changed" not in outcome.message.lower()


class _ReadErrorState:
    async def control_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ReadError("connection reset after send", request=request)


class _ConnectErrorState:
    async def control_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.asyncio
async def test_post_connect_transport_error_is_ambiguous_and_preserves_intent() -> None:
    outcome = await execute_operation(
        _ReadErrorState(),
        _operation(),
        bearer="synthetic-token",
        form={"_intent_id": "stable-intent-read"},
    )
    assert outcome.error_code == "outcome_unknown"
    assert outcome.idempotency_key == "stable-intent-read"


@pytest.mark.asyncio
async def test_connect_error_does_not_claim_command_completed() -> None:
    outcome = await execute_operation(
        _ConnectErrorState(),
        _operation(),
        bearer="synthetic-token",
        form={"_intent_id": "stable-intent-connect"},
    )
    assert outcome.error_code == "control_unreachable"
    assert outcome.idempotency_key == "stable-intent-connect"
