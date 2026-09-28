"""Schema-driven form fields and submission parsing for generic operations.

This is intentionally small: it flattens OpenAPI parameters and one level of
request-body properties into HTML fields, and coerces submitted strings back into
the typed JSON the control plane expects. Nested objects/arrays are submitted as
JSON text so no per-operation screen is required.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

_JSON_KINDS = frozenset({"object", "array"})


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


def _field_from_schema(
    *,
    name: str,
    location: str,
    schema: dict[str, Any],
    required: bool,
    description: str = "",
) -> FormField:
    kind = schema.get("type")
    if not isinstance(kind, str):
        kind = "object" if "properties" in schema else "string"
    enum = tuple(
        str(item) for item in as_list(schema.get("enum")) if not isinstance(item, (dict, list))
    )
    default_raw = schema.get("default")
    default = "" if default_raw is None else str(default_raw)
    return FormField(
        name=name,
        location=location,
        label=name.replace("_", " ").strip().title() or name,
        kind=kind,
        required=required,
        enum=enum,
        default=default,
        description=description or _schema_description(schema),
        multiline=kind in _JSON_KINDS or default.startswith("{") or default.startswith("["),
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
        return raw.strip().lower() in {"1", "true", "on", "yes"}
    if field.kind == "integer":
        try:
            return int(raw)
        except ValueError as exc:
            raise FormSubmissionError(f"{field.label} must be an integer") from exc
    if field.kind == "number":
        try:
            return float(raw)
        except ValueError as exc:
            raise FormSubmissionError(f"{field.label} must be a number") from exc
    if field.kind in _JSON_KINDS:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FormSubmissionError(f"{field.label} must be valid JSON") from exc
    return raw


@dataclass(frozen=True)
class Submission:
    path_params: dict[str, str]
    query_params: dict[str, str]
    body: dict[str, Any] | None


def parse_submission(
    fields: tuple[FormField, ...],
    form: Mapping[str, str],
) -> Submission:
    path_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    body: dict[str, Any] = {}
    has_body_field = False
    for field in fields:
        raw = form.get(field.name)
        if raw is None:
            raw = field.default
        raw = raw.strip()
        if field.location in {"path", "query"}:
            if raw != "":
                target = path_params if field.location == "path" else query_params
                target[field.name] = raw
            elif field.required:
                raise FormSubmissionError(f"{field.label} is required")
            continue
        has_body_field = True
        if raw == "" and not field.required:
            continue
        if raw == "" and field.required:
            raise FormSubmissionError(f"{field.label} is required")
        body[field.name] = _coerce(field, raw)
    return Submission(
        path_params=path_params,
        query_params=query_params,
        body=body if has_body_field else None,
    )


def render_path(path_template: str, path_params: Mapping[str, str]) -> str:
    rendered = path_template
    for name, value in path_params.items():
        rendered = rendered.replace("{" + name + "}", value)
    return rendered


__all__ = [
    "FormField",
    "FormSubmissionError",
    "Submission",
    "build_fields",
    "parse_submission",
    "render_path",
]
