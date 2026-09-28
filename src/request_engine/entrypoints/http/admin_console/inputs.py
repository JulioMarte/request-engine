"""Template-facing helpers that turn canonical operations and payloads into views.

Shared by the generic operations console and the resource workspaces so both
render the same fields and the same result envelope, and neither has to know
anything about control-plane internals.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.forms import build_fields
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping


def build_inputs(
    operation: AdminOperation,
    *,
    values: Mapping[str, str] | None = None,
    secret_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Form inputs for one operation, with pre-filled values and secret marking."""

    provided = values or {}
    secrets = frozenset(secret_fields)
    inputs: list[dict[str, Any]] = []
    for field in build_fields(operation):
        value = provided.get(field.name)
        if value is None:
            value = field.default
        inputs.append(
            {
                "name": field.name,
                "label": field.label,
                "kind": field.kind,
                "required": field.required,
                "enum": field.enum,
                "value": value,
                "default": field.default,
                "description": field.description,
                "location": field.location,
                "multiline": field.multiline,
                "secret": field.name in secrets,
            }
        )
    return inputs


def summarize_payload(payload: Any) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split a JSON payload into scalar rows and pretty JSON rows for display."""

    scalars: list[tuple[str, str]] = []
    nested: list[tuple[str, str]] = []
    for key, value in sorted(as_mapping(payload).items()):
        if isinstance(value, bool):
            scalars.append((key, "yes" if value else "no"))
        elif value is None:
            scalars.append((key, "—"))
        elif isinstance(value, (str, int, float)):
            scalars.append((key, str(value)))
        elif isinstance(value, list):
            scalars.append((key, ", ".join(str(entry) for entry in as_list(value))))
        else:
            nested.append((key, json.dumps(value, indent=2, sort_keys=True, default=str)))
    return scalars, nested


def scalar_columns(payload: Mapping[str, Any], columns: tuple[str, ...]) -> list[str]:
    rendered: list[str] = []
    for column in columns:
        value = as_mapping(payload).get(column)
        if isinstance(value, bool):
            rendered.append("yes" if value else "no")
        elif value is None:
            rendered.append("—")
        else:
            rendered.append(str(value))
    return rendered


__all__ = ["build_inputs", "scalar_columns", "summarize_payload"]
