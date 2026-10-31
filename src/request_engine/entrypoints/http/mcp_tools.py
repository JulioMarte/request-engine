"""Project canonical OpenAPI operations into MCP tool descriptors (ADR 0018).

This module is a pure projection. It reads only the mounted OpenAPI document and the
tool metadata emitted by ``add_capability_route``; it owns no business rule, copies no
capability policy and grants nothing. Authorization is decided by the authorized
operation catalog and, again, by the owner operation when the tool is invoked.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote

MCP_TOOL_AUDIENCE = "operator"
IDEMPOTENCY_ARGUMENT = "idempotency_key"
IDEMPOTENCY_HEADER = "Idempotency-Key"
TENANT_HEADER = "X-RE-Organization-ID"
_IDEMPOTENCY_DESCRIPTION = (
    "Unique key for this intended change; reuse the same key only when retrying the same change."
)
# Descriptive MCP hint only; authorization never depends on it.
_DESTRUCTIVE_VERBS = frozenset(
    {"cancel", "revoke", "deactivate", "retire", "delete", "withdraw", "leave"}
)
_LOCAL_REF = re.compile(r"^#/components/schemas/([^/]+)$")
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")


class ToolArgumentsInvalid(ValueError):
    """Model-supplied arguments do not fit the projected owner operation."""


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """One MCP tool bound to exactly one canonical owner operation."""

    name: str
    operation_id: str
    capability: str
    method: str
    path_template: str
    path_parameters: frozenset[str]
    query_parameters: Mapping[str, bool]  # name -> schema is an array
    body_properties: frozenset[str]
    body_required: bool
    idempotency: bool
    descriptor: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class InnerCall:
    method: str
    path: str
    query: tuple[tuple[str, str], ...]
    body: dict[str, object] | None
    idempotency_key: str | None


def _descend(node: object, segments: list[str]) -> object | None:
    if not segments:
        return node
    if not isinstance(node, dict):
        return None
    children = cast(dict[str, object], node)
    if segments[0] not in children:
        return None
    return _descend(children[segments[0]], segments[1:])


def resolve_pointer(openapi: Mapping[str, object], pointer: str) -> object | None:
    segments = [raw.replace("~1", "/").replace("~0", "~") for raw in pointer.split("/")[1:]]
    return _descend(dict(openapi), segments)


def _inline_refs(
    schema: object,
    components: Mapping[str, object],
    seen: frozenset[str] = frozenset(),
) -> object:
    """Inline local component references so a tool schema is self-contained."""

    if isinstance(schema, list):
        return [_inline_refs(item, components, seen) for item in cast(list[object], schema)]
    if not isinstance(schema, dict):
        return schema
    node = cast(dict[str, object], schema)
    reference = node.get("$ref")
    if isinstance(reference, str):
        match = _LOCAL_REF.fullmatch(reference)
        if match is None or match.group(1) in seen or match.group(1) not in components:
            # Recursive or non-local references degrade to an unconstrained value;
            # the owner operation still validates the full contract.
            return {key: value for key, value in node.items() if key != "$ref"}
        name = match.group(1)
        resolved = _inline_refs(copy.deepcopy(components[name]), components, seen | {name})
        merged = dict(cast(dict[str, object], resolved)) if isinstance(resolved, dict) else {}
        merged.update({key: value for key, value in node.items() if key != "$ref"})
        return {key: _inline_refs(value, components, seen) for key, value in merged.items()}
    return {key: _inline_refs(value, components, seen) for key, value in node.items()}


def _is_array_schema(schema: Mapping[str, object]) -> bool:
    if schema.get("type") == "array":
        return True
    variants = schema.get("anyOf")
    return isinstance(variants, list) and any(
        isinstance(item, dict) and cast(dict[str, object], item).get("type") == "array"
        for item in cast(list[object], variants)
    )


def project_tool(openapi: Mapping[str, object], pointer: str, tool_name: str) -> ToolBinding | None:
    """Build an MCP tool from one OpenAPI operation, or ``None`` if not projectable.

    Fails closed: any input shape the gateway cannot map faithfully (cookies, unknown
    headers, non-object or non-JSON bodies, argument-name collisions) is not exposed.
    """

    operation_value = resolve_pointer(openapi, pointer)
    segments = pointer.split("/")
    if not isinstance(operation_value, dict) or len(segments) < 4:
        return None
    operation = cast(dict[str, Any], operation_value)
    method = segments[-1].upper()
    path_template = segments[-2].replace("~1", "/").replace("~0", "~")
    components_value = cast(dict[str, Any], openapi.get("components", {})).get("schemas", {})
    components = cast(dict[str, object], components_value)
    capability = operation.get("x-request-engine-capability")
    operation_id = operation.get("x-request-engine-operation-id")
    if not isinstance(capability, str) or operation_id != operation.get("operationId"):
        return None

    properties: dict[str, object] = {}
    required: list[str] = []
    path_parameters: set[str] = set()
    query_parameters: dict[str, bool] = {}
    idempotency = False
    idempotency_required = False
    for parameter_value in cast(list[object], operation.get("parameters", [])):
        parameter = cast(dict[str, Any], _inline_refs(parameter_value, components))
        name, location = parameter.get("name"), parameter.get("in")
        if not isinstance(name, str):
            return None
        if location == "header" and name.lower() == TENANT_HEADER.lower():
            continue  # supplied by the trusted connection path, never by the model
        if location == "header" and name.lower() == IDEMPOTENCY_HEADER.lower():
            idempotency = True
            idempotency_required = parameter.get("required") is True
            continue
        if location not in {"path", "query"} or name in properties:
            return None
        schema = dict(cast(dict[str, object], parameter.get("schema", {})))
        if isinstance(parameter.get("description"), str):
            schema["description"] = parameter["description"]
        properties[name] = schema
        if location == "path":
            path_parameters.add(name)
            required.append(name)
        else:
            query_parameters[name] = _is_array_schema(schema)
            if parameter.get("required") is True:
                required.append(name)
    if set(_PATH_PARAMETER.findall(path_template)) != path_parameters:
        return None

    body_properties: set[str] = set()
    body_required = False
    request_body = operation.get("requestBody")
    if request_body is not None:
        content = cast(dict[str, Any], request_body).get("content", {})
        if set(content) != {"application/json"}:
            return None
        body_schema = _inline_refs(content["application/json"].get("schema", {}), components)
        body = cast(dict[str, Any], body_schema) if isinstance(body_schema, dict) else {}
        body_props = body.get("properties")
        if body.get("type") != "object" or not isinstance(body_props, dict):
            return None
        body_required = cast(dict[str, Any], request_body).get("required") is True
        for name, schema in cast(dict[str, object], body_props).items():
            if name in properties or name == IDEMPOTENCY_ARGUMENT:
                return None
            properties[name] = schema
            body_properties.add(name)
        if body_required:
            required.extend(
                name for name in cast(list[str], body.get("required", [])) if name in body_props
            )

    if idempotency:
        if IDEMPOTENCY_ARGUMENT in properties:
            return None
        properties[IDEMPOTENCY_ARGUMENT] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 250,
            "description": _IDEMPOTENCY_DESCRIPTION,
        }
        if idempotency_required:
            required.append(IDEMPOTENCY_ARGUMENT)

    read_only = operation.get("x-request-engine-kind") == "query"
    verb = cast(str, operation_id).rsplit("_", 1)[-1]
    summary = operation.get("summary")
    description = operation.get("description") or summary or cast(str, operation_id)
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        input_schema["required"] = list(dict.fromkeys(required))
    descriptor: dict[str, object] = {
        "name": tool_name,
        "description": (
            f"{description}\n\nOwner operation: {operation_id} "
            f"(capability {capability}). Request Engine enforces authority on every call."
        ),
        "inputSchema": input_schema,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": not read_only and verb in _DESTRUCTIVE_VERBS,
            "idempotentHint": idempotency_required,
            "openWorldHint": False,
        },
    }
    if isinstance(summary, str):
        descriptor["title"] = summary
        cast(dict[str, object], descriptor["annotations"])["title"] = summary
    return ToolBinding(
        name=tool_name,
        operation_id=cast(str, operation_id),
        capability=capability,
        method=method,
        path_template=path_template,
        path_parameters=frozenset(path_parameters),
        query_parameters=query_parameters,
        body_properties=frozenset(body_properties),
        body_required=body_required,
        idempotency=idempotency,
        descriptor=descriptor,
    )


def _scalar(name: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ToolArgumentsInvalid(f"argument {name!r} must be a scalar value")


def _path_segment(name: str, value: object) -> str:
    text = _scalar(name, value)
    # Reject anything that could re-route the inner request to another operation.
    if text in {"", ".", ".."} or "/" in text or "\\" in text or not text.isprintable():
        raise ToolArgumentsInvalid(f"argument {name!r} is not a valid path identifier")
    return quote(text, safe="")


def build_inner_call(binding: ToolBinding, arguments: Mapping[str, object]) -> InnerCall:
    """Split model arguments into the owner operation's own path/query/body inputs."""

    known = binding.path_parameters | set(binding.query_parameters) | binding.body_properties
    if binding.idempotency:
        known = known | {IDEMPOTENCY_ARGUMENT}
    unexpected = sorted(set(arguments) - known)
    if unexpected:
        raise ToolArgumentsInvalid(f"unexpected arguments: {', '.join(unexpected)}")
    missing_path = sorted(binding.path_parameters - set(arguments))
    if missing_path:
        raise ToolArgumentsInvalid(f"missing required arguments: {', '.join(missing_path)}")

    path = _PATH_PARAMETER.sub(
        lambda match: _path_segment(match.group(1), arguments[match.group(1)]),
        binding.path_template,
    )
    query: list[tuple[str, str]] = []
    for name, is_array in binding.query_parameters.items():
        value = arguments.get(name)
        if value is None:
            continue
        if is_array and isinstance(value, list):
            query.extend((name, _scalar(name, item)) for item in cast(list[object], value))
        else:
            query.append((name, _scalar(name, value)))
    body: dict[str, object] | None = None
    if binding.body_properties:
        body = {name: arguments[name] for name in binding.body_properties if name in arguments}
        if not body and not binding.body_required:
            body = None
    idempotency_key = arguments.get(IDEMPOTENCY_ARGUMENT)
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise ToolArgumentsInvalid(f"argument {IDEMPOTENCY_ARGUMENT!r} must be a string")
    return InnerCall(
        method=binding.method,
        path=path,
        query=tuple(query),
        body=body,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "IDEMPOTENCY_ARGUMENT",
    "MCP_TOOL_AUDIENCE",
    "TENANT_HEADER",
    "InnerCall",
    "ToolArgumentsInvalid",
    "ToolBinding",
    "build_inner_call",
    "project_tool",
    "resolve_pointer",
]
