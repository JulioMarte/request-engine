from dataclasses import replace

import httpx
import pytest

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation, AdminParameter
from request_engine.entrypoints.http.admin_console.execution import execute_operation


class _TimeoutState:
    async def control_request(self, *args: object, **kwargs: object):  # noqa: ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ReadTimeout("private-password-canary", request=request)


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
    assert "private-password-canary" not in outcome.payload_json + outcome.message


class _ReadErrorState:
    async def control_request(self, *args: object, **kwargs: object):  # noqa: ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ReadError("connection reset after send", request=request)


class _ConnectErrorState:
    async def control_request(self, *args: object, **kwargs: object):  # noqa: ANN202
        request = httpx.Request("POST", "https://control.test/v1/example")
        raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["..", "../another", "a/b", "a\\b"])
async def test_invalid_resource_segment_fails_before_any_api_call(value: str) -> None:
    class NoCalls:
        async def control_request(self, *args: object, **kwargs: object):  # noqa: ANN202
            pytest.fail("Invalid path must not reach an upstream API")

    operation = replace(
        _operation(),
        path_template="/v1/things/{thing_id}:run",
        parameters=(AdminParameter("thing_id", "path", True, {"type": "string"}, ""),),
    )
    outcome = await execute_operation(NoCalls(), operation, bearer="test", form={"thing_id": value})
    assert outcome.status == 422
    assert outcome.error_code == "form_error"


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
@pytest.mark.parametrize(
    ("kind", "raw"), [("boolean", "maybe"), ("number", "NaN"), ("object", '{"x": 1e999}')]
)
async def test_invalid_typed_value_fails_before_upstream(kind: str, raw: str) -> None:
    class NoCalls:
        async def control_request(self, *args: object, **kwargs: object):  # noqa: ANN202
            pytest.fail("Invalid typed value must not reach an upstream API")

    operation = replace(
        _operation(),
        body_schema={"type": "object", "properties": {"value": {"type": kind}}},
    )
    outcome = await execute_operation(NoCalls(), operation, bearer="test", form={"value": raw})
    assert outcome.status == 422
    assert outcome.error_code == "form_error"
    assert outcome.idempotency_key is None


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
