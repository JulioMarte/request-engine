"""Schema-driven form fields and submission parsing for generic operations.

Canonical schemas describe both scalar controls and nested visual editors.
Submitted controls are coerced into the owner payload; owner validation remains
authoritative. Unstructured schemas retain an explicit advanced JSON input.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.field_labels import field_label
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

_JSON_KINDS = frozenset({"object", "array"})
_KIND_NAMES = {"object": "un objeto JSON", "array": "una lista JSON"}


class FormSubmissionError(ValueError):
    """Raised when a submitted field cannot be coerced to its declared type."""


@dataclass(frozen=True)
class FormField:
    name: str
    location: str
    label: str
    kind: str
    required: bool
    enum: tuple[str, ...]
    default: str
    description: str
    multiline: bool
    nullable: bool = False
    children: tuple[FormField, ...] = ()
    item: FormField | None = None
    format: str = ""


def _field_from_schema(
    *,
    name: str,
    location: str,
    schema: dict[str, Any],
    required: bool,
    description: str = "",
) -> FormField:
    alternatives = [as_mapping(value) for value in as_list(schema.get("anyOf"))]
    nullable = (
        schema.get("nullable") is True
        or schema.get("type") == "null"
        or any(value.get("type") == "null" for value in alternatives)
    )
    typed_alternatives = [value for value in alternatives if value.get("type") != "null"]
    effective = typed_alternatives[0] if len(typed_alternatives) == 1 else schema
    kind = effective.get("type")
    if not isinstance(kind, str):
        kind = "object" if "properties" in schema else "string"
    enum = tuple(
        str(item) for item in as_list(effective.get("enum")) if not isinstance(item, (dict, list))
    )
    if (
        name == "weekday"
        and kind == "integer"
        and effective.get("minimum") == 0
        and effective.get("maximum") == 6
    ):
        enum = tuple(str(day) for day in range(7))
    default_raw = schema.get("default")
    default = (
        ""
        if default_raw is None
        else json.dumps(default_raw)
        if isinstance(default_raw, (dict, list, bool))
        else str(default_raw)
    )
    properties = as_mapping(effective.get("properties"))
    required_children = frozenset(as_list(effective.get("required")))
    children = tuple(
        _field_from_schema(
            name=key, location=location, schema=as_mapping(value), required=key in required_children
        )
        for key, value in properties.items()
        if effective.get("additionalProperties") in (None, False)
    )
    item_schema = as_mapping(effective.get("items"))
    item = (
        _field_from_schema(name="item", location=location, schema=item_schema, required=True)
        if kind == "array" and item_schema
        else None
    )
    return FormField(
        name=name,
        location=location,
        label=field_label(name),
        kind=kind,
        required=required,
        enum=enum,
        default=default,
        description=description or _schema_description(schema),
        multiline=kind in _JSON_KINDS or default.startswith("{") or default.startswith("["),
        nullable=nullable,
        children=children,
        item=item,
        format=str(effective.get("format", "")),
    )


def _schema_description(schema: dict[str, Any]) -> str:
    description = schema.get("description")
    return description if isinstance(description, str) else ""


def build_fields(operation: AdminOperation) -> tuple[FormField, ...]:
    fields: list[FormField] = []
    for parameter in operation.parameters:
        if parameter.location == "header":
            continue
        fields.append(
            _field_from_schema(
                name=parameter.name,
                location=parameter.location,
                schema=parameter.schema,
                required=parameter.required,
                description=parameter.description,
            )
        )
    body = operation.body_schema
    if isinstance(body, dict):
        properties = as_mapping(body.get("properties"))
        required_set = {str(item) for item in as_list(body.get("required"))}
        for name, schema in properties.items():
            fields.append(
                _field_from_schema(
                    name=name,
                    location="body",
                    schema=as_mapping(schema),
                    required=name in required_set,
                )
            )
    return tuple(fields)


def _coerce(field: FormField, raw: str) -> Any:
    if raw == "":
        return None
    if field.kind == "boolean":
        normalized = raw.strip().lower()
        if normalized not in {"1", "true", "on", "yes", "0", "false", "off", "no"}:
            raise FormSubmissionError(f"{field.label}: elija sí o no.")
        return normalized in {"1", "true", "on", "yes"}
    if field.kind == "integer":
        try:
            return int(raw)
        except ValueError as exc:
            raise FormSubmissionError(f"{field.label}: escriba un número entero.") from exc
    if field.kind == "number":
        try:
            number = float(raw)
        except ValueError as exc:
            raise FormSubmissionError(f"{field.label}: escriba un número.") from exc
        if not math.isfinite(number):
            raise FormSubmissionError(f"{field.label}: escriba un número válido.")
        return number
    if field.kind in _JSON_KINDS:
        try:
            value = json.loads(raw)
            # JSON's numeric grammar excludes NaN/infinity. Check nested values
            # too, including overflowed exponents accepted by Python's decoder.
            json.dumps(value, allow_nan=False)
            return value
        except ValueError as exc:
            raise FormSubmissionError(
                f"{field.label}: el JSON no es válido. Revise comillas, comas y llaves."
            ) from exc
    return raw


@dataclass(frozen=True)
class Submission:
    path_params: dict[str, str]
    query_params: dict[str, str]
    body: dict[str, Any] | None


_OMITTED = object()
_MAX_ARRAY_ITEMS = 100


def _read_value(field: FormField, name: str, form: Mapping[str, str]) -> Any:
    structured = form.get("__structured__" + name) == "true"
    if structured:
        if not field.required and form.get("__include__" + name) != "true":
            return _OMITTED
        if field.nullable and form.get("__mode__" + name) == "null":
            return None
        if field.kind == "object" and field.children:
            result: dict[str, Any] = {}
            for child in field.children:
                value = _read_value(child, name + "." + child.name, form)
                if value is not _OMITTED:
                    result[child.name] = value
            return result
        if field.kind == "array" and field.item is not None:
            prefix = name + "["
            indices: set[int] = set()
            for key in form:
                candidate = key.removeprefix("__structured__").removeprefix("__include__")
                if candidate.startswith(prefix):
                    match = re.match(r"(\d+)\]", candidate[len(prefix) :])
                    if match:
                        indices.add(int(match.group(1)))
            if len(indices) > _MAX_ARRAY_ITEMS:
                raise FormSubmissionError(
                    f"{field.label}: hay demasiadas entradas. Quite algunas e intente de nuevo."
                )
            return [_read_value(field.item, f"{name}[{index}]", form) for index in sorted(indices)]
        raise FormSubmissionError(
            f"{field.label}: este campo no acepta entradas estructuradas. Recargue la página."
        )
    raw = form.get(name, field.default).strip()
    if raw == "" and field.nullable and form.get("__null__" + name) == "true":
        return None
    if raw == "" and field.required and field.nullable and name in form:
        return None
    if raw == "" and not field.required:
        return _OMITTED
    if raw == "":
        raise FormSubmissionError(f"{field.label}: este campo es obligatorio.")
    value = _coerce(field, raw)
    if value is None and field.nullable:
        return None
    if field.kind in _JSON_KINDS and not isinstance(
        value, dict if field.kind == "object" else list
    ):
        raise FormSubmissionError(
            f"{field.label}: el valor debe ser {_KIND_NAMES.get(field.kind, field.kind)}."
        )
    return cast(Any, value)


def parse_submission(
    fields: tuple[FormField, ...],
    form: Mapping[str, str],
) -> Submission:
    path_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    body: dict[str, Any] = {}
    has_body_field = False
    for field in fields:
        if field.location in {"path", "query"}:
            raw = form.get(field.name, field.default).strip()
            if raw != "":
                target = path_params if field.location == "path" else query_params
                target[field.name] = raw
            elif field.required:
                raise FormSubmissionError(f"{field.label}: este campo es obligatorio.")
            continue
        has_body_field = True
        value = _read_value(field, field.name, form)
        if value is not _OMITTED:
            body[field.name] = value
    return Submission(
        path_params=path_params,
        query_params=query_params,
        body=body if has_body_field else None,
    )


def render_path(path_template: str, path_params: Mapping[str, str]) -> str:
    rendered = path_template
    for name, value in path_params.items():
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise FormSubmissionError(
                "Un identificador no es válido: no puede contener barras ni ser «.» o «..»."
            )
        rendered = rendered.replace("{" + name + "}", quote(value, safe=""))
    return rendered


__all__ = [
    "FormField",
    "FormSubmissionError",
    "Submission",
    "build_fields",
    "parse_submission",
    "render_path",
]
