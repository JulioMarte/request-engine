"""Read-to-command form guidance without copying owner authority or revisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.resources import list_items, prefill_values

# Each revision comes from an actual parent owner read, never from an empty child page.
_READ_ACTIONS = {
    "request_definitions_list": (
        ("request_definition_read", (("definition_id", "definition_id"),)),
    ),
    "request_definition_read": (
        (
            "request_definition_version_publish",
            (("definition_id", "definition_id"), ("expected_revision", "revision")),
        ),
        (
            "request_definition_set_active",
            (("definition_id", "definition_id"), ("expected_revision", "revision")),
        ),
    ),
    "requests_list_inbox": (("requests_read", (("request_id", "request_id"),)),),
    "catalog_location_configuration_list": (
        ("catalog_location_configuration_read", (("location_id", "location_id"),)),
    ),
    "catalog_location_configuration_read": (
        (
            "catalog_location_update",
            (
                ("location_id", "location_id"),
                ("expected_operational_revision", "operational_revision"),
                ("timezone", "timezone"),
            ),
        ),
    ),
    "catalog_offering_configuration_list": (
        ("catalog_offering_configuration_read", (("offering_id", "offering_id"),)),
    ),
    "catalog_offering_configuration_read": (
        (
            "catalog_offering_version_configuration_read",
            (("offering_version_id", "offering_version_id"),),
        ),
    ),
    "queue_service_queue_configuration_list": (
        ("queue_service_queue_configuration_read", (("queue_id", "queue_id"),)),
    ),
    "communications_channel_policy_get": (
        (
            "communications_configure_channel_policy",
            (("purpose", "purpose"), ("expected_revision", "revision")),
        ),
    ),
    "catalog_offering_version_configuration_read": (
        (
            "catalog_manage_offering_version_booking_policy",
            (
                ("offering_version_id", "offering_version_id"),
                ("expected_revision", "booking_policy_revision"),
                ("booking_policy", "booking_policy"),
            ),
        ),
    ),
    "booking_resource_list": (
        (
            "booking_resource_assignment_create",
            (
                ("resource_id", "resource_id"),
                ("expected_resource_availability_revision", "availability_revision"),
            ),
        ),
        (
            "booking_resource_exception_set",
            (
                ("resource_id", "resource_id"),
                ("expected_resource_availability_revision", "availability_revision"),
            ),
        ),
    ),
    "booking_resource_assignment_list": (
        (
            "booking_resource_assignment_retire",
            (
                ("assignment_id", "assignment_id"),
                ("expected_assignment_revision", "assignment_revision"),
                ("expected_resource_availability_revision", "resource_availability_revision"),
            ),
        ),
        (
            "booking_resource_assignment_availability_replace",
            (
                ("assignment_id", "assignment_id"),
                ("expected_resource_availability_revision", "resource_availability_revision"),
            ),
        ),
        (
            "booking_resource_assignment_exception_set",
            (
                ("assignment_id", "assignment_id"),
                ("expected_resource_availability_revision", "resource_availability_revision"),
            ),
        ),
    ),
    "booking_context_terms_list": (
        (
            "booking_context_terms_supersede",
            (
                ("current_context_terms_id", "context_terms_id"),
                ("expected_current_revision", "revision"),
            ),
        ),
    ),
}


def read_action_links(
    operation_id: str,
    payload: Any,
    *,
    values: Mapping[str, str],
    catalog: AdminCatalog,
    root: str,
) -> list[dict[str, str]]:
    """Offer only actions whose required read preconditions were actually returned."""
    if not inventory_read_valid(operation_id, payload):
        return []
    body = as_mapping(payload)
    rows = list_items(body) if "items" in body else [body]
    links: list[dict[str, str]] = []
    for row in rows:
        for target, pairs in _READ_ACTIONS.get(operation_id, ()):
            operation = catalog.by_id().get(target)
            if operation is None:
                continue
            if not _valid_preconditions(row, pairs, target):
                continue
            prefill = prefill_values(row, pairs)
            if not all(prefill.values()):
                continue
            if target == "request_definition_version_publish":
                if not isinstance(row.get("input_schema"), dict):
                    continue
                prefill["input_schema"] = json.dumps(row["input_schema"])
                prefill["result_schema"] = (
                    json.dumps(row["result_schema"]) if row.get("result_schema") is not None else ""
                )
            if target == "request_definition_set_active":
                if type(row.get("active")) is not bool:
                    continue
                prefill["active"] = "true" if row["active"] else "false"
            if target == "catalog_manage_offering_version_booking_policy":
                prefill["booking_policy"] = json.dumps(row["booking_policy"])
            if target == "catalog_location_update":
                prefill["active"] = "true" if row["active"] else "false"
                for field in _LOCATION_OPTIONAL_FIELDS:
                    value = row[field]
                    prefill[field] = "" if value is None else str(value)
            accepted_names = {parameter.name for parameter in operation.parameters}
            accepted_names.update(as_mapping(as_mapping(operation.body_schema).get("properties")))
            if values.get("authority_party_id") and "authority_party_id" in accepted_names:
                prefill["authority_party_id"] = values["authority_party_id"]
            reference = next((value for key, value in prefill.items() if key.endswith("_id")), "")
            links.append(
                {
                    "label": operation.summary or target.replace("_", " "),
                    "reference": reference,
                    "href": f"{root}/{target}?{urlencode(prefill)}",
                }
            )
    return links


_LOCATION_OPTIONAL_FIELDS = (
    "address_line1",
    "address_line2",
    "locality",
    "administrative_area",
    "postal_code",
    "country_code",
    "latitude",
    "longitude",
    "geocoding_source",
    "geocoded_at",
)
_DEFINITION_FIELDS = (
    "definition_id",
    "request_key",
    "display_name",
    "active",
    "revision",
    "version_id",
    "version",
    "input_schema",
    "result_schema",
)
_INVENTORY_FIELDS = {
    "request_definitions": _DEFINITION_FIELDS,
    "request_definition": _DEFINITION_FIELDS,
    "catalog_location_configuration": (
        "location_id",
        "location_key",
        "display_name",
        "timezone",
        "active",
        "operational_revision",
        *_LOCATION_OPTIONAL_FIELDS,
    ),
    "catalog_offering_configuration": (
        "offering_id",
        "offering_key",
        "display_name",
        "description",
        "active",
        "offering_version_id",
        "version",
        "duration_minutes",
        "bookable",
        "requestable",
        "booking_policy_revision",
    ),
    "queue_service_queue_configuration": (
        "queue_id",
        "queue_key",
        "display_name",
        "location_id",
        "offering_id",
        "policy_key",
        "active",
        "revision",
    ),
}


def inventory_read_valid(operation_id: str, payload: Any) -> bool:
    """Reject incomplete transport responses rather than offer unsafe inventory guidance."""
    prefix, _, kind = operation_id.rpartition("_")
    fields = _INVENTORY_FIELDS.get(prefix)
    if fields is None:
        return True
    if not isinstance(payload, dict):
        return False
    body = as_mapping(payload)
    rows: list[Any] = [body]
    if kind == "list":
        if not isinstance(body.get("items"), list) or "next_cursor" not in body:
            return False
        rows = as_list(body["items"])
        if len(rows) > (200 if prefix == "request_definitions" else 100):
            return False
        cursor = body["next_cursor"]
        if cursor is not None:
            if prefix == "request_definitions":
                if not isinstance(cursor, str) or not cursor or len(cursor) > 2000:
                    return False
            elif not _uuid_value(cursor):
                return False
    for candidate in rows:
        if not isinstance(candidate, dict):
            return False
        row = as_mapping(candidate)
        if not set(fields) <= row.keys():
            return False
        for field in fields:
            value = row[field]
            if field.endswith("_id"):
                if (
                    value is None
                    and field in {"location_id", "offering_id"}
                    and prefix.startswith("queue_")
                ):
                    continue
                if not _uuid_value(value):
                    return False
            elif field in {"active", "bookable", "requestable"}:
                if type(value) is not bool:
                    return False
            elif "revision" in field or field == "version":
                if type(value) is not int or value < (
                    0 if field == "booking_policy_revision" else 1
                ):
                    return False
            elif field.endswith("_key") or field in {"display_name", "timezone"}:
                if not isinstance(value, str) or not value:
                    return False
            elif field in {"input_schema", "result_schema"}:
                if field == "result_schema" and value is None:
                    continue
                if not isinstance(value, dict):
                    return False
            elif field in {"latitude", "longitude"}:
                if value is not None and (type(value) not in {str, int, float}):
                    return False
            elif field == "duration_minutes":
                if value is not None and (type(value) is not int or value <= 0):
                    return False
            elif value is not None and not isinstance(value, str):
                return False
    return True


def _uuid_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


__all__ = ["read_action_links", "inventory_read_valid"]


def _valid_preconditions(
    row: Mapping[str, Any], pairs: tuple[tuple[str, str], ...], target: str
) -> bool:
    for field, source in pairs:
        value = row.get(source)
        if "revision" in field:
            minimum = (
                0
                if target
                in {
                    "communications_configure_channel_policy",
                    "catalog_manage_offering_version_booking_policy",
                }
                else 1
            )
            if type(value) is not int or value < minimum:
                return False
        elif field.endswith("_id"):
            if not isinstance(value, str):
                return False
            try:
                UUID(value)
            except ValueError:
                return False
        elif field == "booking_policy":
            if not isinstance(value, dict):
                return False
        elif not isinstance(value, str) or not value:
            return False
    return True
