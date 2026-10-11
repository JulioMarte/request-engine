"""Schema publication rejects invalid caller input before opening a transaction."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from request_engine.modules.requests.api.definition_models import CreateRequestDefinitionBody
from request_engine.modules.requests.api.models import SubmitRequestBody
from request_engine.modules.requests.application.commands.manage_definition import (
    validate_definition_key,
    validate_definition_schemas,
)
from request_engine.modules.requests.application.errors import RequestPayloadInvalid


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "external"},
        {"type": "wrong"},
        {"properties": []},
        {"default": float("nan")},
        {"description": "x" * 65536},
    ],
)
def test_definition_schema_rejects_unsupported_malformed_nonfinite_or_unbounded_input(
    schema: dict[str, object],
) -> None:
    with pytest.raises(RequestPayloadInvalid):
        validate_definition_schemas(schema, None)


def test_schema_subset_and_optional_result_contract_are_explicit() -> None:
    validate_definition_schemas(
        {
            "type": "object",
            "required": ["message"],
            "properties": {"message": {"type": "string", "maxLength": 200}},
        },
        {"type": "object", "properties": {"accepted": {"type": "boolean"}}},
    )
    with pytest.raises(ValidationError):
        SubmitRequestBody.model_validate({"payload": {}})
    with pytest.raises(ValidationError):
        CreateRequestDefinitionBody.model_validate(
            {
                "authority_party_id": str(uuid4()),
                "request_key": "contact",
                "display_name": "Contact",
                "input_schema": {},
                "organization_id": str(uuid4()),
            }
        )


def test_nested_schema_is_bounded_before_recursive_encoding_or_validation() -> None:
    schema: dict[str, object] = {"type": "string"}
    for _ in range(70):
        schema = {"type": "array", "items": schema}
    with pytest.raises(RequestPayloadInvalid, match="safety limit"):
        validate_definition_schemas(schema, None)


@pytest.mark.parametrize("key", ["/", "..", "../contact", "white space", "a?b", "a#b", "a" * 161])
def test_owner_rejects_unaddressable_definition_keys(key: str) -> None:
    with pytest.raises(RequestPayloadInvalid):
        validate_definition_key(key)
