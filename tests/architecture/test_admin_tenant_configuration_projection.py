"""Tenant task projection must match the real runtime owner schemas."""

import json
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, load_catalog
from request_engine.entrypoints.http.admin_console.forms import build_fields
from request_engine.entrypoints.http.admin_console.presentation import (
    TENANT_CONFIGURATION_OPERATION_IDS,
    TENANT_RUNTIME_EXTERNAL_DESTINATIONS,
)
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    TODAY_OPERATION_IDS,
)
from request_engine.entrypoints.http.admin_console.tenant_configuration import (
    inventory_read_valid,
    read_action_links,
)
from request_engine.entrypoints.http.app import create_native_app

_RESOURCE = "11111111-1111-4111-8111-111111111111"
_ASSIGNMENT = "22222222-2222-4222-8222-222222222222"
_PARTY = "33333333-3333-4333-8333-333333333333"
_ROOT = f"/tenants/{_RESOURCE}/configuration"


@pytest.fixture(scope="module")
def runtime_catalog() -> AdminCatalog:
    app = create_native_app(
        session_factory=cast(Any, object()),
        native_identity_authority_id=UUID(_RESOURCE),
        appointment_option_signing_key=b"coverage-native-appointment-key-32",
    )
    return load_catalog(app.openapi())


def test_configuration_tasks_reference_actual_owner_operations(
    runtime_catalog: AdminCatalog,
) -> None:
    assert set(runtime_catalog.by_id()) >= TENANT_CONFIGURATION_OPERATION_IDS


@pytest.mark.parametrize(
    "read_id,payload,expected",
    [
        (
            "booking_resource_list",
            {"items": [{"resource_id": _RESOURCE, "availability_revision": 9}]},
            {
                "booking_resource_assignment_create": {
                    "resource_id": _RESOURCE,
                    "expected_resource_availability_revision": "9",
                },
                "booking_resource_exception_set": {
                    "resource_id": _RESOURCE,
                    "expected_resource_availability_revision": "9",
                },
            },
        ),
        (
            "booking_resource_assignment_list",
            {
                "items": [
                    {
                        "assignment_id": _ASSIGNMENT,
                        "assignment_revision": 4,
                        "resource_availability_revision": 9,
                    }
                ]
            },
            {
                "booking_resource_assignment_retire": {
                    "assignment_id": _ASSIGNMENT,
                    "expected_assignment_revision": "4",
                    "expected_resource_availability_revision": "9",
                },
                "booking_resource_assignment_availability_replace": {
                    "assignment_id": _ASSIGNMENT,
                    "expected_resource_availability_revision": "9",
                },
                "booking_resource_assignment_exception_set": {
                    "assignment_id": _ASSIGNMENT,
                    "expected_resource_availability_revision": "9",
                },
            },
        ),
        (
            "booking_context_terms_list",
            {"items": [{"context_terms_id": _ASSIGNMENT, "revision": 3}]},
            {
                "booking_context_terms_supersede": {
                    "current_context_terms_id": _ASSIGNMENT,
                    "expected_current_revision": "3",
                }
            },
        ),
        (
            "communications_channel_policy_get",
            {"purpose": "appointment_reminder", "revision": 0},
            {
                "communications_configure_channel_policy": {
                    "purpose": "appointment_reminder",
                    "expected_revision": "0",
                }
            },
        ),
        (
            "catalog_offering_version_configuration_read",
            {
                "offering_version_id": _ASSIGNMENT,
                "booking_policy_revision": 0,
                "booking_policy": {"slot_step_minutes": 30},
            },
            {
                "catalog_manage_offering_version_booking_policy": {
                    "offering_version_id": _ASSIGNMENT,
                    "expected_revision": "0",
                    "booking_policy": '{"slot_step_minutes": 30}',
                }
            },
        ),
    ],
)
def test_owner_read_prefills_use_canonical_command_fields(
    runtime_catalog: AdminCatalog,
    read_id: str,
    payload: dict[str, Any],
    expected: dict[str, dict[str, str]],
) -> None:
    links = read_action_links(
        read_id, payload, values={"authority_party_id": _PARTY}, catalog=runtime_catalog, root=_ROOT
    )
    observed: dict[str, dict[str, str]] = {}
    for link in links:
        parsed = urlsplit(link["href"])
        target_id = parsed.path.rsplit("/", 1)[-1]
        values = {key: value[0] for key, value in parse_qs(parsed.query).items()}
        operation = runtime_catalog.by_id()[target_id]
        fields = build_fields(operation)
        assert set(values) <= {field.name for field in fields}
        # Other required input (dates/windows/location) remains visibly editable;
        # every required identifier/revision supplied by this read must match it.
        for key, value in expected[target_id].items():
            assert values[key] == value
        assert values["authority_party_id"] == _PARTY
        if "booking_policy" in values:
            assert json.loads(values["booking_policy"]) == {"slot_step_minutes": 30}
        observed[target_id] = values
    assert set(observed) == set(expected)


@pytest.mark.parametrize(
    "resource_id,revision",
    [("invalid", 1), (_RESOURCE, True), (_RESOURCE, -1), (_RESOURCE, "9"), (_RESOURCE, None)],
)
def test_malformed_parent_cannot_supply_action_preconditions(
    runtime_catalog: AdminCatalog, resource_id: str, revision: Any
) -> None:
    assert (
        read_action_links(
            "booking_resource_list",
            {"items": [{"resource_id": resource_id, "availability_revision": revision}]},
            values={},
            catalog=runtime_catalog,
            root=_ROOT,
        )
        == []
    )


_LOCATION: dict[str, Any] = {
    "location_id": _RESOURCE,
    "location_key": "main",
    "display_name": "Main office",
    "timezone": "America/Santo_Domingo",
    "active": False,
    "operational_revision": 7,
    "hours_windows": [],
    "public_contacts": [],
    "address_line1": "27 Main Street",
    "address_line2": None,
    "locality": "Santo Domingo",
    "administrative_area": None,
    "postal_code": None,
    "country_code": "DO",
    "latitude": "18.4861",
    "longitude": "-69.9312",
    "geocoding_source": None,
    "geocoded_at": None,
}
_OFFERING = {
    "offering_id": _RESOURCE,
    "offering_key": "consultation",
    "display_name": "Consultation",
    "description": None,
    "active": False,
    "offering_version_id": _ASSIGNMENT,
    "version": 2,
    "duration_minutes": 30,
    "bookable": True,
    "requestable": False,
    "booking_policy_revision": 0,
}
_QUEUE = {
    "queue_id": _RESOURCE,
    "queue_key": "reception",
    "display_name": "Reception",
    "location_id": _ASSIGNMENT,
    "offering_id": None,
    "policy_key": "fifo",
    "active": False,
    "revision": 3,
}


@pytest.mark.parametrize(
    "read_id,row,target,expected",
    [
        (
            "catalog_location_configuration_list",
            _LOCATION,
            "catalog_location_configuration_read",
            {"location_id": _RESOURCE, "authority_party_id": _PARTY},
        ),
        (
            "catalog_location_configuration_read",
            _LOCATION,
            "catalog_location_update",
            {
                "location_id": _RESOURCE,
                "authority_party_id": _PARTY,
                "expected_operational_revision": "7",
                "active": "false",
                "timezone": "America/Santo_Domingo",
                "address_line1": "27 Main Street",
                "country_code": "DO",
            },
        ),
        (
            "catalog_offering_configuration_list",
            _OFFERING,
            "catalog_offering_configuration_read",
            {"offering_id": _RESOURCE, "authority_party_id": _PARTY},
        ),
        (
            "catalog_offering_configuration_read",
            _OFFERING,
            "catalog_offering_version_configuration_read",
            {"offering_version_id": _ASSIGNMENT},
        ),
        (
            "queue_service_queue_configuration_list",
            _QUEUE,
            "queue_service_queue_configuration_read",
            {"queue_id": _RESOURCE, "authority_party_id": _PARTY},
        ),
    ],
)
def test_inventory_guidance_matches_real_owner_inputs(
    runtime_catalog: AdminCatalog,
    read_id: str,
    row: dict[str, Any],
    target: str,
    expected: dict[str, str],
) -> None:
    payload = {"items": [row], "next_cursor": None} if read_id.endswith("_list") else row
    links = read_action_links(
        read_id, payload, values={"authority_party_id": _PARTY}, catalog=runtime_catalog, root=_ROOT
    )
    matches = [link for link in links if urlsplit(link["href"]).path == f"{_ROOT}/{target}"]
    assert len(matches) == 1
    parsed = urlsplit(matches[0]["href"])
    values = {
        key: value[0] for key, value in parse_qs(parsed.query, keep_blank_values=True).items()
    }
    assert set(values) <= {field.name for field in build_fields(runtime_catalog.by_id()[target])}
    assert all(values[key] == value for key, value in expected.items())
    if target == "catalog_offering_version_configuration_read":
        assert "authority_party_id" not in values
    if target == "catalog_location_update":
        assert values["address_line2"] == ""


@pytest.mark.parametrize(
    "prefix,row",
    [
        ("catalog_location_configuration", _LOCATION),
        ("catalog_offering_configuration", _OFFERING),
        ("queue_service_queue_configuration", _QUEUE),
    ],
)
def test_incomplete_inventory_is_not_a_valid_empty_collection_or_action_source(
    runtime_catalog: AdminCatalog,
    prefix: str,
    row: dict[str, Any],
) -> None:
    list_id = f"{prefix}_list"
    invalid_payloads: tuple[dict[str, Any], ...] = (
        {},
        {"items": [], "next_cursor": True},
        {"items": [{}], "next_cursor": None},
        {"items": [{**row, "active": "false"}], "next_cursor": None},
    )
    for invalid in invalid_payloads:
        assert not inventory_read_valid(list_id, invalid)
        assert (
            read_action_links(list_id, invalid, values={}, catalog=runtime_catalog, root=_ROOT)
            == []
        )
    assert inventory_read_valid(list_id, {"items": [], "next_cursor": None})
    assert inventory_read_valid(f"{prefix}_read", row)


def test_queue_read_does_not_invent_a_queue_edit_operation(runtime_catalog: AdminCatalog) -> None:
    assert (
        read_action_links(
            "queue_service_queue_configuration_read",
            _QUEUE,
            values={"authority_party_id": _PARTY},
            catalog=runtime_catalog,
            root=_ROOT,
        )
        == []
    )


def test_every_runtime_operator_operation_has_an_explicit_admin_destination_or_scope_reason(
    runtime_catalog: AdminCatalog,
) -> None:
    operators = {op.operation_id for op in runtime_catalog.operations if op.exposure == "operator"}
    external = TENANT_RUNTIME_EXTERNAL_DESTINATIONS
    assert not operators - TENANT_CONFIGURATION_OPERATION_IDS - external.keys()
    assert set(external) <= operators
    assert not TENANT_CONFIGURATION_OPERATION_IDS & external.keys()
    assert all(destination and reason for destination, reason in external.values())


def test_today_front_desk_projects_only_mounted_owner_operations(
    runtime_catalog: AdminCatalog,
) -> None:
    # Every operation Today executes must exist in the real runtime OpenAPI, and
    # every operator operation it projects must be declared under tenant-today
    # (and nothing declared there may be absent from Today). Public owner
    # operations such as appointments_book keep their own exposure: Today
    # projects them without changing capability or authority metadata.
    by_id = runtime_catalog.by_id()
    assert not TODAY_OPERATION_IDS - by_id.keys()
    declared_today = {
        operation_id
        for operation_id, (destination, _) in TENANT_RUNTIME_EXTERNAL_DESTINATIONS.items()
        if destination == "tenant-today"
    }
    # Operator business-configuration operations keep their configuration
    # destination. Today may only READ them (who works where, for "Start
    # service"); it never runs an operator configuration command.
    configuration_today = {
        operation_id
        for operation_id in TODAY_OPERATION_IDS & TENANT_CONFIGURATION_OPERATION_IDS
        if by_id[operation_id].exposure == "operator"
    }
    assert configuration_today, "Today reads who works where from business configuration"
    for operation_id in configuration_today:
        assert by_id[operation_id].method.upper() == "GET", operation_id
        assert not by_id[operation_id].is_mutating, operation_id
    assert not declared_today & TENANT_CONFIGURATION_OPERATION_IDS
    operator_today = {
        operation_id
        for operation_id in TODAY_OPERATION_IDS - configuration_today
        if by_id[operation_id].exposure == "operator"
    }
    assert declared_today == operator_today
    for operation_id in TODAY_OPERATION_IDS:
        operation = by_id[operation_id]
        assert operation.capability, operation_id
        if operation.is_mutating:
            assert operation.requires_idempotency_key, operation_id


_DEFINITION = {
    "definition_id": _RESOURCE,
    "request_key": "frontdesk_help",
    "display_name": "Front desk help",
    "active": False,
    "revision": 5,
    "version_id": _ASSIGNMENT,
    "version": 2,
    "input_schema": {"type": "object"},
    "result_schema": None,
}


@pytest.mark.parametrize(
    "read_id,payload,target,expected",
    [
        (
            "request_definitions_list",
            {"items": [_DEFINITION], "next_cursor": None},
            "request_definition_read",
            {"definition_id": _RESOURCE},
        ),
        (
            "requests_list_inbox",
            {"items": [{"request_id": _RESOURCE}]},
            "requests_read",
            {"request_id": _RESOURCE},
        ),
    ],
)
def test_requests_collection_guidance_opens_the_exact_owner_read(
    runtime_catalog: AdminCatalog,
    read_id: str,
    payload: dict[str, Any],
    target: str,
    expected: dict[str, str],
) -> None:
    links = read_action_links(read_id, payload, values={}, catalog=runtime_catalog, root=_ROOT)
    assert len(links) == 1
    parsed = urlsplit(links[0]["href"])
    assert parsed.path == f"{_ROOT}/{target}"
    values = {key: value[0] for key, value in parse_qs(parsed.query).items()}
    assert values == expected
    assert set(values) <= {field.name for field in build_fields(runtime_catalog.by_id()[target])}


def test_definition_revision_prefills_both_commands_without_manufacturing_party(
    runtime_catalog: AdminCatalog,
) -> None:
    links = read_action_links(
        "request_definition_read",
        _DEFINITION,
        values={},
        catalog=runtime_catalog,
        root=_ROOT,
    )
    assert len(links) == 2
    for link in links:
        parsed = urlsplit(link["href"])
        target = parsed.path.rsplit("/", 1)[-1]
        values = {
            key: value[0] for key, value in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        assert values["definition_id"] == _RESOURCE
        assert values["expected_revision"] == "5"
        assert "authority_party_id" not in values
        assert set(values) <= {
            field.name for field in build_fields(runtime_catalog.by_id()[target])
        }
        if target == "request_definition_version_publish":
            assert json.loads(values["input_schema"]) == {"type": "object"}
            assert values["result_schema"] == ""
        else:
            assert values["active"] == "false"
    assert (
        read_action_links(
            "request_definition_read",
            {"definition_id": _RESOURCE, "revision": 0, "active": False, "input_schema": {}},
            values={},
            catalog=runtime_catalog,
            root=_ROOT,
        )
        == []
    )


def test_partial_definition_does_not_offer_revision_sensitive_mutations(
    runtime_catalog: AdminCatalog,
) -> None:
    invalid_payloads: tuple[dict[str, Any], ...] = (
        {"definition_id": _RESOURCE, "revision": 5},
        {**_DEFINITION, "revision": 0},
        {**_DEFINITION, "input_schema": []},
    )
    for payload in invalid_payloads:
        assert (
            read_action_links(
                "request_definition_read", payload, values={}, catalog=runtime_catalog, root=_ROOT
            )
            == []
        )
    assert not inventory_read_valid("request_definitions_list", {})
    assert inventory_read_valid("request_definitions_list", {"items": [], "next_cursor": None})
