"""Template-facing helpers that turn canonical operations and payloads into views.

Shared by the generic operations console and the resource workspaces so both
render the same fields and the same result envelope, and neither has to know
anything about control-plane internals.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.forms import FormField, build_fields
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

_BROWSER_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9](?:\.[0-9]{1,3})?)?")
# Credential inputs never render as visible text, including in the generic
# operations form that has no workspace-specific secret field list.
_CREDENTIAL_FIELDS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "recovery_code",
        "recovery_token",
        "verification_token",
        "invitation_token",
        "workload_token",
    }
)


def build_inputs(
    operation: AdminOperation,
    *,
    values: Mapping[str, str] | None = None,
    secret_fields: tuple[str, ...] = (),
    loaded_revisions: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Render values; only explicit owner-read revisions get a loaded-state label."""

    provided = values or {}
    secrets = frozenset(secret_fields) | _CREDENTIAL_FIELDS
    inputs: list[dict[str, Any]] = []
    for field in build_fields(operation):
        value = provided.get(field.name, field.default)
        view = _input_view(field, field.name, value, secrets, 0)
        if (
            field.name in loaded_revisions
            and field.name in provided
            and field.name.startswith("expected_")
            and ("revision" in field.name or field.name.endswith("_version"))
            and value.isdecimal()
        ):
            view["hidden"] = True
            view["loaded_revision"] = True
        inputs.append(view)
    return inputs


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bool, dict, list)):
        return json.dumps(value)
    return str(value)


def _input_view(
    field: FormField, name: str, value: str, secrets: frozenset[str], depth: int
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "name": name,
        "label": field.label,
        "kind": field.kind,
        "required": field.required and not field.nullable,
        "enum": field.enum,
        "value": value,
        "default": field.default,
        "description": field.description,
        "location": field.location,
        "multiline": field.multiline,
        "secret": field.name in secrets,
        "structured": False,
        "format": field.format,
    }
    if field.format == "time" and value and not _BROWSER_TIME.fullmatch(value):
        # Native time controls silently clear sub-millisecond precision and offsets.
        view["format"] = ""
        view["exact_time"] = True
    if field.name == "weekday" and field.enum == tuple(str(day) for day in range(7)):
        weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        view["enum_options"] = [
            {"value": str(day), "label": label} for day, label in enumerate(weekdays)
        ]
    if not field.children and field.item is None:
        return view
    try:
        current = json.loads(value) if value else None
    except ValueError:
        return view
    if current is not None and not isinstance(current, dict if field.kind == "object" else list):
        return view
    if field.kind == "object" and isinstance(current, dict):
        declared = {child.name for child in field.children}
        if set(as_mapping(current)) - declared:
            return view
    view["structured"] = True
    view["required"] = field.required
    view["nullable"] = field.nullable
    view["null_value"] = value == "null"
    view["included"] = field.required or current is not None or value == "null"
    if field.kind == "object":
        contents = as_mapping(current)
        children: list[dict[str, Any]] = []
        for child in field.children:
            child_view = _input_view(
                child,
                name + "." + child.name,
                _display_value(contents.get(child.name, child.default)),
                secrets,
                depth + 1,
            )
            child_view["preserve_null"] = (
                child.nullable and child.name in contents and contents[child.name] is None
            )
            if child_view["preserve_null"] and child.kind in {"object", "array"}:
                child_view = _input_view(child, name + "." + child.name, "null", secrets, depth + 1)
            children.append(child_view)
        view["children"] = children

    elif field.item is not None:
        view["rows"] = [
            _input_view(field.item, f"{name}[{index}]", _display_value(item), secrets, depth + 1)
            for index, item in enumerate(as_list(current))
        ]
        view["index_token"] = f"__INDEX_{depth}__"
        view["prototype"] = _input_view(
            field.item,
            name + "[" + view["index_token"] + "]",
            field.item.default,
            secrets,
            depth + 1,
        )
    return view


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
