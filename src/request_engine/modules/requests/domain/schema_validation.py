import math
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

import re2

from request_engine.modules.requests.domain.errors import (
    RequestPayloadInvalid,
    UnsupportedRequestSchema,
)

_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_ANNOTATION_KEYWORDS = {"$schema", "$id", "title", "description", "default", "examples"}
_ASSERTION_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "items",
    "minProperties",
    "maxProperties",
}
_SUPPORTED_KEYWORDS = _ANNOTATION_KEYWORDS | _ASSERTION_KEYWORDS


class _CompiledPattern(Protocol):
    def search(self, text: str) -> object | None: ...


@dataclass(slots=True)
class _SchemaPatterns:
    compiled: dict[str, _CompiledPattern] = field(
        default_factory=lambda: dict[str, _CompiledPattern]()
    )
    source_bytes: int = 0

    def admit(self, pattern: str, *, path: str) -> _CompiledPattern:
        existing = self.compiled.get(pattern)
        if existing is not None:
            return existing
        size = _utf8_size(pattern, path=path)
        if size > 2048 or len(self.compiled) >= 32 or self.source_bytes + size > 16384:
            raise UnsupportedRequestSchema(path, "pattern")
        options = re2.Options()
        options.max_mem = 1048576
        options.log_errors = False
        try:
            compiled = re2.compile(pattern, options=options)
        except re2.error:
            raise UnsupportedRequestSchema(path, "pattern") from None
        self.compiled[pattern] = compiled
        self.source_bytes += size
        return compiled


def _utf8_size(value: str, *, path: str) -> int:
    if len(value) > 1048576:
        raise RequestPayloadInvalid(path, "JSON text exceeds safety limit")
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise RequestPayloadInvalid(path, "JSON strings must be valid UTF-8") from None


def _bound_json_tree(value: object, *, path: str) -> None:
    """Bound legacy schemas and owner documents before any recursive traversal."""
    pending: list[tuple[object, int]] = [(value, 0)]
    visited = 0
    text_bytes = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 4096:
            raise RequestPayloadInvalid(path, "JSON nesting or node count exceeds safety limit")
        if isinstance(item, str):
            text_bytes += _utf8_size(item, path=path)
        elif isinstance(item, dict):
            if len(cast(dict[object, object], item)) + visited + len(pending) > 4096:
                raise RequestPayloadInvalid(path, "JSON node count exceeds safety limit")
            for key, child in cast(dict[object, object], item).items():
                if not isinstance(key, str):
                    raise RequestPayloadInvalid(path, "JSON object keys must be strings")
                text_bytes += _utf8_size(key, path=path)
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            if len(cast(list[object], item)) + visited + len(pending) > 4096:
                raise RequestPayloadInvalid(path, "JSON node count exceeds safety limit")
            pending.extend((child, depth + 1) for child in cast(list[object], item))
        if text_bytes > 1048576:
            raise RequestPayloadInvalid(path, "aggregate JSON text exceeds safety limit")


def validate_request_document(document: object, schema: dict[str, object]) -> None:
    """Validate JSON data against the deliberately small V3 schema subset.

    The subset follows familiar JSON Schema keyword semantics but rejects every
    unimplemented keyword instead of silently accepting a broader dialect.
    """

    patterns = _SchemaPatterns()
    try:
        _bound_json_tree(schema, path="$")
        _validate_schema(schema, schema_path="$", patterns=patterns)
    except RequestPayloadInvalid as exc:
        # The document caller cannot repair an already-published definition.
        # Publication validates its caller-owned schema via validate_request_schema,
        # which deliberately keeps the normal input-error classification.
        raise UnsupportedRequestSchema(exc.path, "schema") from None
    _bound_json_tree(document, path="$")
    _ensure_json_value(document, path="$")
    _validate_value(document, schema, data_path="$", schema_path="$", patterns=patterns)


def validate_request_schema(schema: dict[str, object]) -> None:
    """Validate that a stored Request schema uses only the supported V3 subset."""

    _bound_json_tree(schema, path="$")
    _validate_schema(schema, schema_path="$", patterns=_SchemaPatterns())


def _validate_schema(
    schema: dict[str, object], *, schema_path: str, patterns: _SchemaPatterns
) -> None:
    for keyword in schema:
        if keyword not in _SUPPORTED_KEYWORDS:
            raise UnsupportedRequestSchema(schema_path, keyword)

    raw_type = schema.get("type")
    if raw_type is not None:
        _parse_types(raw_type, schema_path=schema_path)

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise RequestPayloadInvalid(schema_path, "schema properties must be an object")
        typed_properties = cast(dict[object, object], properties)
        for raw_name, raw_child in typed_properties.items():
            if not isinstance(raw_name, str) or not isinstance(raw_child, dict):
                raise RequestPayloadInvalid(
                    schema_path,
                    "schema properties must map string names to schema objects",
                )
            _validate_schema(
                cast(dict[str, object], raw_child),
                schema_path=f"{schema_path}.properties.{raw_name}",
                patterns=patterns,
            )

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list):
            raise RequestPayloadInvalid(schema_path, "schema required must be an array")
        typed_required = cast(list[object], required)
        if any(not isinstance(value, str) for value in typed_required):
            raise RequestPayloadInvalid(schema_path, "schema required values must be strings")
        required_names = cast(list[str], typed_required)
        if len(set(required_names)) != len(required_names):
            raise RequestPayloadInvalid(schema_path, "schema required values must be unique")

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):
        raise RequestPayloadInvalid(
            schema_path,
            "schema additionalProperties must be boolean or a schema object",
        )
    if isinstance(additional, dict):
        _validate_schema(
            cast(dict[str, object], additional),
            schema_path=f"{schema_path}.additionalProperties",
            patterns=patterns,
        )

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, dict):
            raise RequestPayloadInvalid(schema_path, "schema items must be a schema object")
        _validate_schema(
            cast(dict[str, object], items),
            schema_path=f"{schema_path}.items",
            patterns=patterns,
        )

    enum_values = schema.get("enum")
    if enum_values is not None:
        if not isinstance(enum_values, list) or not enum_values:
            raise RequestPayloadInvalid(schema_path, "schema enum must be a non-empty array")
        for value in cast(list[object], enum_values):
            _ensure_json_value(value, path=f"{schema_path}.enum")

    bounded_count_keywords = (
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
    )
    for keyword in bounded_count_keywords:
        value = schema.get(keyword)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise RequestPayloadInvalid(
                schema_path,
                f"schema {keyword} must be a non-negative integer",
            )

    pattern = schema.get("pattern")
    if "pattern" in schema:
        if not isinstance(pattern, str):
            raise RequestPayloadInvalid(schema_path, "schema pattern must be a string")
        patterns.admit(pattern, path=schema_path)

    for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        value = schema.get(keyword)
        if value is not None and not _is_number(value):
            raise RequestPayloadInvalid(schema_path, f"schema {keyword} must be numeric")

    unique_items = schema.get("uniqueItems")
    if unique_items is not None and not isinstance(unique_items, bool):
        raise RequestPayloadInvalid(schema_path, "schema uniqueItems must be boolean")

    if "const" in schema:
        _ensure_json_value(schema["const"], path=f"{schema_path}.const")


def _validate_value(
    value: object,
    schema: dict[str, object],
    *,
    data_path: str,
    schema_path: str,
    patterns: _SchemaPatterns,
) -> None:

    raw_type = schema.get("type")
    if raw_type is not None:
        allowed_types = _parse_types(raw_type, schema_path=schema_path)
        if not any(_matches_type(value, type_name) for type_name in allowed_types):
            expected = " | ".join(allowed_types)
            raise RequestPayloadInvalid(data_path, f"expected type {expected}")

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise RequestPayloadInvalid(data_path, "value does not match const")

    enum_values = schema.get("enum")
    if enum_values is not None:
        typed_enum = cast(list[object], enum_values)
        if not any(_json_equal(value, candidate) for candidate in typed_enum):
            raise RequestPayloadInvalid(data_path, "value is not in enum")

    if isinstance(value, dict):
        _validate_object(
            cast(dict[str, object], value),
            schema,
            data_path=data_path,
            schema_path=schema_path,
            patterns=patterns,
        )
    elif isinstance(value, list):
        _validate_array(
            cast(list[object], value),
            schema,
            data_path=data_path,
            schema_path=schema_path,
            patterns=patterns,
        )
    elif isinstance(value, str):
        _validate_string(value, schema, data_path=data_path, patterns=patterns)
    elif _is_number(value):
        _validate_number(value, schema, data_path=data_path)


def _validate_object(
    value: dict[str, object],
    schema: dict[str, object],
    *,
    data_path: str,
    schema_path: str,
    patterns: _SchemaPatterns,
) -> None:
    required = schema.get("required", [])
    if isinstance(required, list):
        for required_name in cast(list[object], required):
            if isinstance(required_name, str) and required_name not in value:
                raise RequestPayloadInvalid(
                    data_path,
                    f"missing required property {required_name!r}",
                )

    minimum = schema.get("minProperties")
    maximum = schema.get("maxProperties")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(value) < minimum:
        raise RequestPayloadInvalid(data_path, f"requires at least {minimum} properties")
    if isinstance(maximum, int) and not isinstance(maximum, bool) and len(value) > maximum:
        raise RequestPayloadInvalid(data_path, f"allows at most {maximum} properties")

    raw_properties = schema.get("properties", {})
    properties = cast(dict[str, object], raw_properties) if isinstance(raw_properties, dict) else {}
    additional = schema.get("additionalProperties", True)

    for name, child_value in value.items():
        child_schema = properties.get(name)
        if isinstance(child_schema, dict):
            _validate_value(
                child_value,
                cast(dict[str, object], child_schema),
                data_path=f"{data_path}.{name}",
                schema_path=f"{schema_path}.properties.{name}",
                patterns=patterns,
            )
            continue
        if additional is False:
            raise RequestPayloadInvalid(data_path, f"unexpected property {name!r}")
        if isinstance(additional, dict):
            _validate_value(
                child_value,
                cast(dict[str, object], additional),
                data_path=f"{data_path}.{name}",
                schema_path=f"{schema_path}.additionalProperties",
                patterns=patterns,
            )


def _validate_array(
    value: list[object],
    schema: dict[str, object],
    *,
    data_path: str,
    schema_path: str,
    patterns: _SchemaPatterns,
) -> None:
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(value) < minimum:
        raise RequestPayloadInvalid(data_path, f"requires at least {minimum} items")
    if isinstance(maximum, int) and not isinstance(maximum, bool) and len(value) > maximum:
        raise RequestPayloadInvalid(data_path, f"allows at most {maximum} items")

    if schema.get("uniqueItems") is True:
        seen: set[Hashable] = set()
        for item in value:
            identity = _json_fingerprint(item)
            if identity in seen:
                raise RequestPayloadInvalid(data_path, "array items must be unique")
            seen.add(identity)

    items = schema.get("items")
    if isinstance(items, dict):
        item_schema = cast(dict[str, object], items)
        for index, item in enumerate(value):
            _validate_value(
                item,
                item_schema,
                data_path=f"{data_path}[{index}]",
                schema_path=f"{schema_path}.items",
                patterns=patterns,
            )


def _validate_string(
    value: str, schema: dict[str, object], *, data_path: str, patterns: _SchemaPatterns
) -> None:
    minimum = schema.get("minLength")
    maximum = schema.get("maxLength")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(value) < minimum:
        raise RequestPayloadInvalid(data_path, f"string is shorter than {minimum}")
    if isinstance(maximum, int) and not isinstance(maximum, bool) and len(value) > maximum:
        raise RequestPayloadInvalid(data_path, f"string is longer than {maximum}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and patterns.compiled[pattern].search(value) is None:
        raise RequestPayloadInvalid(data_path, f"string does not match pattern {pattern!r}")


def _validate_number(value: object, schema: dict[str, object], *, data_path: str) -> None:
    numeric = cast(int | float, value)
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    exclusive_minimum = schema.get("exclusiveMinimum")
    exclusive_maximum = schema.get("exclusiveMaximum")
    if _is_number(minimum) and numeric < cast(int | float, minimum):
        raise RequestPayloadInvalid(data_path, f"number is below minimum {minimum}")
    if _is_number(maximum) and numeric > cast(int | float, maximum):
        raise RequestPayloadInvalid(data_path, f"number is above maximum {maximum}")
    if _is_number(exclusive_minimum) and numeric <= cast(int | float, exclusive_minimum):
        raise RequestPayloadInvalid(
            data_path,
            f"number must be greater than {exclusive_minimum}",
        )
    if _is_number(exclusive_maximum) and numeric >= cast(int | float, exclusive_maximum):
        raise RequestPayloadInvalid(
            data_path,
            f"number must be less than {exclusive_maximum}",
        )


def _parse_types(value: object, *, schema_path: str) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates: Sequence[object] = (value,)
    elif isinstance(value, list):
        candidates = cast(list[object], value)
    else:
        raise RequestPayloadInvalid(schema_path, "schema type must be a string or array")

    result: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str) or candidate not in _JSON_TYPES:
            raise RequestPayloadInvalid(schema_path, f"unsupported schema type {candidate!r}")
        if candidate in result:
            raise RequestPayloadInvalid(schema_path, "schema type values must be unique")
        result.append(candidate)
    if not result:
        raise RequestPayloadInvalid(schema_path, "schema type array cannot be empty")
    return tuple(result)


def _matches_type(value: object, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return _is_number(value)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def _ensure_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool)) or _is_number(value):
        return
    if isinstance(value, list):
        for index, item in enumerate(cast(list[object], value)):
            _ensure_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        typed = cast(dict[object, object], value)
        for key, item in typed.items():
            if not isinstance(key, str):
                raise RequestPayloadInvalid(path, "JSON object keys must be strings")
            _ensure_json_value(item, path=f"{path}.{key}")
        return
    raise RequestPayloadInvalid(path, f"value of type {type(value).__name__} is not JSON")


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _json_equal(left: object, right: object) -> bool:
    _ensure_json_value(left, path="$")
    _ensure_json_value(right, path="$")
    if _is_number(left) and _is_number(right):
        return cast(int | float, left) == cast(int | float, right)
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) and isinstance(right, list):
        left_items = cast(list[object], left)
        right_items = cast(list[object], right)
        if len(left_items) != len(right_items):
            return False
        return all(_json_equal(a, b) for a, b in zip(left_items, right_items, strict=True))
    if isinstance(left, dict) and isinstance(right, dict):
        left_map = cast(dict[str, object], left)
        right_map = cast(dict[str, object], right)
        if left_map.keys() != right_map.keys():
            return False
        return all(_json_equal(left_map[key], right_map[key]) for key in left_map)
    return False


def _json_fingerprint(value: object) -> Hashable:
    """Structural JSON identity, not a digest; numeric equality retains 1 == 1.0.

    Type tags keep bool distinct from number. Object order is irrelevant while
    list order remains significant. The public boundary already bounded and
    validated the tree, so constructing identities cannot recurse unboundedly.
    """
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if _is_number(value):
        return ("number", cast(int | float, value))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_json_fingerprint(item) for item in cast(list[object], value)))
    if isinstance(value, dict):
        return (
            "object",
            frozenset(
                (key, _json_fingerprint(item))
                for key, item in cast(dict[str, object], value).items()
            ),
        )
    raise RequestPayloadInvalid("$", f"value of type {type(value).__name__} is not JSON")
