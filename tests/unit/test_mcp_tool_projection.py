"""Unit proofs for projecting canonical OpenAPI operations into MCP tools (ADR 0018)."""

from typing import Any, cast

import pytest

from request_engine.entrypoints.http.mcp_tools import (
    ToolArgumentsInvalid,
    build_inner_call,
    project_tool,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_COMMAND_POINTER = "/paths/~1v1~1things~1{thing_id}~1cancel/post"
_QUERY_POINTER = "/paths/~1v1~1things/get"


def _openapi(**overrides: Any) -> dict[str, Any]:
    command: dict[str, Any] = {
        "operationId": "things_cancel",
        "summary": "Cancel a thing",
        "x-request-engine-operation-id": "things_cancel",
        "x-request-engine-capability": "things.cancel",
        "x-request-engine-kind": "command",
        "parameters": [
            {"name": "thing_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            },
            {
                "name": "X-RE-Organization-ID",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            },
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Body"}}},
        },
    }
    command.update(overrides)
    return {
        "paths": {
            "/v1/things/{thing_id}/cancel": {"post": command},
            "/v1/things": {
                "get": {
                    "operationId": "things_list",
                    "x-request-engine-operation-id": "things_list",
                    "x-request-engine-capability": "things.list",
                    "x-request-engine-kind": "query",
                    "parameters": [
                        {
                            "name": "tag",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "array", "items": {"type": "string"}},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                    ],
                }
            },
        },
        "components": {
            "schemas": {
                "Body": {
                    "type": "object",
                    "properties": {
                        "expected_revision": {"type": "integer"},
                        "reason": {"$ref": "#/components/schemas/Reason"},
                    },
                    "required": ["expected_revision"],
                },
                "Reason": {"type": "string", "maxLength": 10},
            }
        },
    }


def test_command_schema_merges_path_body_and_required_idempotency_key() -> None:
    binding = project_tool(_openapi(), _COMMAND_POINTER, "things_cancel")
    assert binding is not None
    schema = cast(dict[str, Any], binding.descriptor["inputSchema"])
    assert set(schema["properties"]) == {
        "thing_id",
        "expected_revision",
        "reason",
        "idempotency_key",
    }
    # References are inlined; the tenant header is never a model argument.
    assert schema["properties"]["reason"] == {"type": "string", "maxLength": 10}
    assert schema["required"] == ["thing_id", "expected_revision", "idempotency_key"]
    assert schema["additionalProperties"] is False
    assert binding.descriptor["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
        "title": "Cancel a thing",
    }


def test_query_annotations_and_array_query_mapping() -> None:
    binding = project_tool(_openapi(), _QUERY_POINTER, "things_list")
    assert binding is not None
    annotations = binding.descriptor["annotations"]
    assert isinstance(annotations, dict)
    assert annotations["readOnlyHint"] is True
    assert annotations["destructiveHint"] is False
    call = build_inner_call(binding, {"tag": ["a", "b"], "limit": 5})
    assert call.method == "GET"
    assert call.query == (("tag", "a"), ("tag", "b"), ("limit", "5"))
    assert call.body is None
    assert call.idempotency_key is None


def test_arguments_split_into_owner_inputs_and_idempotency_header() -> None:
    binding = project_tool(_openapi(), _COMMAND_POINTER, "things_cancel")
    assert binding is not None
    call = build_inner_call(
        binding,
        {"thing_id": "abc", "expected_revision": 3, "idempotency_key": "k-1"},
    )
    assert (call.method, call.path) == ("POST", "/v1/things/abc/cancel")
    assert call.body == {"expected_revision": 3}
    assert call.idempotency_key == "k-1"


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "arguments",
    [
        {"thing_id": "abc", "organization_id": "00000000-0000-4000-8000-000000000001"},
        {"thing_id": "abc", "X-RE-Organization-ID": "x"},
        {"thing_id": "abc", "principal_id": "x"},
        {"thing_id": "../../agents"},
        {"thing_id": ".."},
        {"thing_id": "a/b"},
        {"thing_id": {"nested": True}},
        {"expected_revision": 1},
        {"thing_id": "abc", "idempotency_key": 7},
    ],
)
def test_unexpected_identity_or_rerouting_arguments_are_rejected(
    arguments: dict[str, object],
) -> None:
    binding = project_tool(_openapi(), _COMMAND_POINTER, "things_cancel")
    assert binding is not None
    with pytest.raises(ToolArgumentsInvalid):
        build_inner_call(binding, arguments)


_UNMAPPABLE: list[dict[str, Any]] = [
    {"operationId": "legacy_fallback_id"},
    {
        "parameters": [
            {"name": "thing_id", "in": "path", "required": True, "schema": {}},
            {"name": "If-Match", "in": "header", "required": True, "schema": {}},
        ]
    },
    {
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": {"type": "object"}}},
        }
    },
    {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"type": "object", "properties": {"thing_id": {}}}}
            },
        }
    },
]


@pytest.mark.parametrize("overrides", _UNMAPPABLE)
def test_unmappable_operations_fail_closed(overrides: dict[str, Any]) -> None:
    assert project_tool(_openapi(**overrides), _COMMAND_POINTER, "things_cancel") is None


def test_unknown_pointer_is_not_projected() -> None:
    assert project_tool(_openapi(), "/paths/~1v1~1missing/get", "missing") is None
