"""Owner-boundary proof: no backtracking execution or unbounded schema admission.

A regression to stdlib re hangs the isolated attack subprocess and fails its
watchdog. Other assertions use public owner validation and independent limits.
These prove CPU/input safety, not PostgreSQL rollback or HTTP authentication.
"""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
import re2
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from request_engine.modules.requests.api.errors import request_error_handler
from request_engine.modules.requests.api.router import create_router
from request_engine.modules.requests.application.commands.create_request import CreateRequestCommand
from request_engine.modules.requests.application.commands.manage_definition import (
    validate_definition_schemas,
)
from request_engine.modules.requests.contracts.request import Request as BusinessRequest
from request_engine.modules.requests.domain.errors import (
    RequestError,
    RequestPayloadInvalid,
    UnsupportedRequestSchema,
)
from request_engine.modules.requests.domain.schema_validation import (
    validate_request_document,
    validate_request_schema,
)
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit, pytest.mark.adversarial, pytest.mark.security]


def test_pathological_backtracking_pattern_cannot_stall_owner_validation() -> None:
    # The subprocess contains the production owner call, not a replacement
    # engine. Its watchdog makes removing the safe engine a falsifiable defect.
    attack = """
from request_engine.modules.requests.domain.schema_validation import validate_request_document
from request_engine.modules.requests.domain.errors import RequestPayloadInvalid
try:
    validate_request_document('a' * 100000 + '!', {'type': 'string', 'pattern': '(a|aa)+$'})
except RequestPayloadInvalid as exc:
    assert 'does not match pattern' in str(exc)
else:
    raise AssertionError('invalid demand accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", attack], capture_output=True, text=True, timeout=5, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "pattern",
    [r"(a)\1", r"(?=a)a", "(", "a" * 2049, "a{999999999}", None],
)
def test_publication_and_legacy_validation_reject_unsupported_or_unbounded_patterns(
    pattern: object,
) -> None:
    schema: dict[str, object] = {"type": "string", "pattern": pattern}
    with pytest.raises(RequestPayloadInvalid, match="pattern"):
        validate_definition_schemas(schema, None)
    with pytest.raises(UnsupportedRequestSchema) as exc:
        validate_request_document("a", schema)
    assert exc.value.keyword == ("schema" if pattern is None else "pattern")


def test_pattern_collection_is_bounded_even_when_each_pattern_is_small() -> None:
    schema: dict[str, object] = {
        "properties": {f"p{index}": {"pattern": f"value{index}"} for index in range(33)}
    }
    with pytest.raises(UnsupportedRequestSchema) as exc:
        validate_request_schema(schema)
    assert exc.value.keyword == "pattern"


def test_pattern_source_budget_is_aggregate_not_only_per_expression() -> None:
    schema: dict[str, object] = {
        "properties": {f"p{index}": {"pattern": "a" * 1900 + str(index)} for index in range(9)}
    }
    with pytest.raises(UnsupportedRequestSchema) as exc:
        validate_request_schema(schema)
    assert exc.value.keyword == "pattern"


@pytest.mark.parametrize("document", [["a" * 600000, "a" * 600000], [0] * 4096, "\ud800"])
def test_document_admission_bounds_aggregate_work_and_invalid_unicode(document: object) -> None:
    with pytest.raises(RequestPayloadInvalid, match="safety limit|UTF-8"):
        validate_request_document(document, {})


def test_legacy_deep_schema_and_deep_document_fail_before_recursion() -> None:
    schema: dict[str, object] = {}
    document: object = "a"
    for _ in range(1000):
        schema = {"items": schema}
        document = [document]
    with pytest.raises(RequestPayloadInvalid, match="safety limit"):
        validate_request_schema(schema)
    with pytest.raises(RequestPayloadInvalid, match="safety limit"):
        validate_request_document(document, {})


def test_search_not_fullmatch_and_safe_unicode_patterns_are_supported() -> None:
    validate_request_document("prefix-ñ-suffix", {"pattern": "ñ"})
    validate_request_document("abc42", {"pattern": r"^[a-z]+[0-9]+$"})
    validate_request_document("abc", {"pattern": ""})
    with pytest.raises(RequestPayloadInvalid, match="does not match"):
        validate_request_document("abc", {"pattern": r"^[0-9]+$"})


def test_repeated_item_validation_does_not_readmit_or_recompile_schema_per_item() -> None:
    schema: dict[str, object] = {"type": "array", "items": {"pattern": "^valid$"}}
    with patch.object(re2, "compile", wraps=re2.compile) as compiler:
        validate_request_document(["valid"] * 1000, schema)
    assert compiler.call_count == 1
    assert compiler.call_args is not None
    assert compiler.call_args.kwargs["options"].max_mem == 1048576
    assert compiler.call_args.kwargs["options"].log_errors is False


def test_deep_regex_groups_do_not_overflow_the_compiler_stack() -> None:
    # Within the public byte budget but beyond Python re's recursive parser.
    pattern = "(" * 900 + "a" + ")" * 900
    validate_request_schema({"pattern": pattern})
    validate_request_document("a", {"pattern": pattern})


def test_re2_unicode_property_is_explicit_not_python_shorthand() -> None:
    validate_request_document("ñ", {"pattern": r"^\p{L}$"})
    with pytest.raises(RequestPayloadInvalid, match="does not match"):
        validate_request_document("ñ", {"pattern": r"^\w$"})


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", [False, True])
async def test_error_mapping_distinguishes_operator_schema_failure_from_caller_input(
    publication: bool,
) -> None:
    schema: dict[str, object] = {"pattern": r"(a)\1"}
    try:
        if publication:
            validate_definition_schemas(schema, None)
        else:
            validate_request_document("a", schema)
    except (RequestPayloadInvalid, UnsupportedRequestSchema) as exc:
        response = await request_error_handler(Request({"type": "http"}), exc)
    else:
        pytest.fail("unsupported pattern admitted")
    body = json.loads(bytes(response.body))
    assert response.status_code == (422 if publication else 500)
    assert body["error"]["code"] == (
        "request_payload_invalid" if publication else "request_definition_invalid"
    )
    assert body["error"]["resolution"] == (
        "fix_request" if publication else "operator_intervention"
    )
    assert "(a)" not in bytes(response.body).decode()


@pytest.mark.parametrize(
    "document",
    [[1, 1.0], [{"a": 1, "b": False}, {"b": False, "a": 1.0}], [[1, False], [1.0, False]]],
)
def test_unique_items_fingerprint_preserves_numeric_and_structural_equality(
    document: list[object],
) -> None:
    with pytest.raises(RequestPayloadInvalid, match="items must be unique"):
        validate_request_document(document, {"uniqueItems": True})


def test_unique_items_keeps_boolean_number_object_and_array_order_distinctions() -> None:
    validate_request_document(
        [False, 0, True, 1, "1", [False, 1], [1, False], {"a": False}, {"a": 0}],
        {"uniqueItems": True},
    )


def test_unique_items_large_admission_uses_structural_identities_not_pairwise_comparison() -> None:
    with patch(
        "request_engine.modules.requests.domain.schema_validation._json_equal",
        side_effect=AssertionError("pairwise equality makes uniqueItems quadratic"),
    ):
        validate_request_document(list(range(4000)), {"uniqueItems": True})


@pytest.mark.parametrize("schema", [{"properties": []}, {"type": "wrong"}, {"pattern": None}])
def test_invalid_stored_schema_is_operator_failure_but_publication_is_caller_error(
    schema: dict[str, object],
) -> None:
    with pytest.raises(UnsupportedRequestSchema) as exc:
        validate_request_document({}, schema)
    assert exc.value.keyword == "schema"
    with pytest.raises(RequestPayloadInvalid):
        validate_definition_schemas(schema, None)


def test_deep_stored_schema_is_not_reported_as_a_fixable_demand_payload() -> None:
    schema: dict[str, object] = {}
    for _ in range(70):
        schema = {"items": schema}
    with pytest.raises(UnsupportedRequestSchema) as exc:
        validate_request_document([], schema)
    assert exc.value.keyword == "schema"
    with pytest.raises(RequestPayloadInvalid):
        validate_definition_schemas(schema, None)


def test_invalid_demand_document_keeps_caller_input_classification() -> None:
    with pytest.raises(RequestPayloadInvalid, match="expected type string"):
        validate_request_document(1, {"type": "string"})
    with pytest.raises(RequestPayloadInvalid, match="safety limit"):
        validate_request_document("a" * 1048577, {"type": "string"})


def test_schema_configuration_errors_are_explicit_in_owner_http_contracts() -> None:
    router = create_router(
        create_handler=Mock(),
        record_result_handler=Mock(),
        complete_handler=Mock(),
        cancel_handler=Mock(),
        fail_handler=Mock(),
        reader=Mock(),
        definition_resolver=Mock(),
        actor_resolver=Mock(),
        include_internal=True,
    )
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    response = schema["paths"]["/v1/requests/definitions/{request_key}/submit"]["post"][
        "responses"
    ]["500"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    # INTERNAL routes intentionally remain hidden from OpenAPI. Their explicit
    # owner response declarations still describe the mounted internal handler.
    for suffix in ("/{request_id}/result", "/{request_id}/complete"):
        route = next(
            item
            for item in router.routes
            if isinstance(item, APIRoute) and item.path.endswith(suffix)
        )
        assert route.responses[500]["model"] is ErrorEnvelope


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_schema", [False, True])
async def test_actual_submit_http_distinguishes_persisted_schema_and_document_failures(
    invalid_schema: bool,
) -> None:
    # Isolated port; real router, typed Command, validator and owner error handler.
    # This is transport/error evidence, not DB rollback or native-auth evidence.
    schema: dict[str, object] = (
        {"properties": []} if invalid_schema else {"type": "object", "required": ["name"]}
    )

    async def validate_submit(command: CreateRequestCommand) -> BusinessRequest:
        validate_request_document(command.payload, schema)
        raise AssertionError("invalid input reached successful submission")

    actor = ActorContext(uuid4(), uuid4(), frozenset({"requests.submit"}))
    app = FastAPI()
    app.add_exception_handler(RequestError, request_error_handler)
    app.include_router(
        create_router(
            create_handler=Mock(create_request=AsyncMock(side_effect=validate_submit)),
            record_result_handler=Mock(),
            complete_handler=Mock(),
            cancel_handler=Mock(),
            fail_handler=Mock(),
            reader=Mock(),
            definition_resolver=Mock(
                resolve_request_definition=AsyncMock(return_value=Mock(id=uuid4()))
            ),
            actor_resolver=Mock(resolve_actor=AsyncMock(return_value=actor)),
        )
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/v1/requests/definitions/contact/submit",
            headers={"Idempotency-Key": "schema-error-contract"},
            json={"definition_version": 1, "payload": {}},
        )
    assert response.status_code == (500 if invalid_schema else 422)
    assert response.json()["error"]["resolution"] == (
        "operator_intervention" if invalid_schema else "fix_request"
    )
