import pytest

from request_engine.modules.requests.application.errors import (
    RequestPayloadInvalid,
    UnsupportedRequestSchema,
)
from request_engine.modules.requests.domain.schema_validation import (
    validate_request_document,
    validate_request_schema,
)


def test_supported_schema_validates_nested_request_document() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "required": ["name", "services"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 2},
            "services": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string"},
            },
        },
    }

    validate_request_schema(schema)
    validate_request_document(
        {"name": "Ana", "services": ["consultation", "lab"]},
        schema,
    )


def test_unsupported_schema_keyword_is_rejected_explicitly() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "oneOf": [{"required": ["email"]}, {"required": ["phone"]}],
    }

    with pytest.raises(UnsupportedRequestSchema) as exc_info:
        validate_request_schema(schema)

    assert exc_info.value.keyword == "oneOf"


def test_non_finite_numbers_are_not_valid_json_values() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
    }

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(RequestPayloadInvalid):
            validate_request_document({"amount": value}, schema)


def test_json_numeric_equality_matches_json_schema_semantics() -> None:
    enum_schema: dict[str, object] = {"enum": [1]}
    const_schema: dict[str, object] = {"const": {"amount": 1}}

    validate_request_document(1.0, enum_schema)
    validate_request_document({"amount": 1.0}, const_schema)


def test_unique_items_treats_equivalent_json_numbers_as_duplicates() -> None:
    schema: dict[str, object] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "number"},
    }

    with pytest.raises(RequestPayloadInvalid, match="array items must be unique"):
        validate_request_document([1, 1.0], schema)


def test_additional_properties_false_is_enforced() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": False,
    }

    with pytest.raises(RequestPayloadInvalid, match="unexpected property"):
        validate_request_document({"name": "Ana", "unexpected": True}, schema)
