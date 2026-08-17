from __future__ import annotations

import ast
import runpy
from pathlib import Path
from typing import Any, cast

from request_engine.platform.security.capabilities import CAPABILITIES

_EXPECTED_OPERATIONS = (
    "capabilities.list|GET|/v1/capabilities|",
    "business.read|GET|/v1/business|business.get_info",
    "catalog.offerings.list|GET|/v1/catalog/offerings|catalog.search_offerings",
    "catalog.offerings.read|GET|/v1/catalog/offerings/{offering_key}|catalog.get_offering_details",
    "appointments.find_slots|GET|/v1/appointments/slots|appointments.find_slots",
    "appointments.book|POST|/v1/appointments|appointments.book",
    "appointments.read|GET|/v1/appointments/{reservation_id}|appointments.read",
    "appointments.cancel|POST|/v1/appointments/{reservation_id}/cancel|appointments.cancel",
    "appointments.reschedule|POST|/v1/appointments/{reservation_id}/reschedule|appointments.reschedule",
    "appointments.attendance|POST|/v1/appointments/{reservation_id}/attendance|appointments.confirm_attendance",
    "queue.list|GET|/v1/queues|queue.list",
    "queue.join|POST|/v1/queues/{queue_id}/join|queue.join",
    "queue.status|GET|/v1/queues/{queue_id}/status|queue.status",
    "queue.leave|POST|/v1/queues/{queue_id}/entries/{queue_entry_id}/leave|queue.leave",
    "queue.call_next|POST|/v1/queues/{queue_id}/call-next|queue.call_next",
    "waitlist.join|POST|/v1/waitlist|waitlist.join",
    "waitlist.read|GET|/v1/waitlist/{waitlist_entry_id}|waitlist.read",
    "waitlist.leave|POST|/v1/waitlist/{waitlist_entry_id}/leave|waitlist.leave",
    "requests.submit|POST|/v1/requests/definitions/{request_key}/submit|requests.submit",
    "requests.read|GET|/v1/requests/{request_id}|requests.read",
    "requests.cancel|POST|/v1/requests/{request_id}/cancel|requests.cancel",
    "reminders.create|POST|/v1/reminders|reminders.create_plan",
    "reminders.read|GET|/v1/reminders/{reminder_plan_id}|reminders.read",
    "reminders.cancel|POST|/v1/reminders/{reminder_plan_id}/cancel|reminders.cancel_plan",
)

_EXPECTED_CAPABILITIES = (
    "business.get_info|public|query|none|none|||business.read|1",
    "catalog.search_offerings|public|query|none|none|||catalog.read|1",
    "catalog.get_offering_details|public|query|none|none|||catalog.read|1",
    "appointments.find_slots|public|query|none|none|||booking.find_slots|1",
    "appointments.book|public|command|required|none|appointments.book|appointments.subject_override|booking.book_appointment|1",
    "appointments.read|public|query|none|none|appointments.manage|appointments.subject_override|booking.read|1",
    "appointments.cancel|public|command|required|required|appointments.manage|appointments.subject_override|booking.cancel_reservation|1",
    "appointments.reschedule|public|command|required|required|appointments.manage|appointments.subject_override|booking.reschedule_reservation|1",
    "appointments.confirm_attendance|public|command|required|required|appointments.manage|appointments.subject_override||1",
    "appointments.subject_override|operator|command|required|none|||booking.subject_override|0",
    "queue.list|public|query|none|none|||queue.read|1",
    "queue.join|public|command|required|none|queue.join|queue.subject_override||1",
    "queue.status|public|query|none|none|queue.manage|queue.subject_override|queue.read|1",
    "queue.leave|public|command|required|required|queue.manage|queue.subject_override||1",
    "queue.call_next|operator|command|required|server_selected||||1",
    "queue.subject_override|operator|command|required|none||||0",
    "waitlist.join|public|command|required|none|waitlist.join|waitlist.subject_override||1",
    "waitlist.read|public|query|none|none|waitlist.manage|waitlist.subject_override||1",
    "waitlist.leave|public|command|required|required|waitlist.manage|waitlist.subject_override||1",
    "waitlist.accept_offer|public|command|required|required|waitlist.manage|waitlist.subject_override||1",
    "waitlist.decline_offer|public|command|required|required|waitlist.manage|waitlist.subject_override||1",
    "waitlist.subject_override|operator|command|required|none||||0",
    "waitlist.create_opportunity|internal|command|required|none||||1",
    "reminders.create_plan|public|command|required|none|reminders.manage|reminders.subject_override|communications.create_reminder_plan|1",
    "reminders.read|public|query|none|none|reminders.manage|reminders.subject_override||1",
    "reminders.cancel_plan|public|command|required|required|reminders.manage|reminders.subject_override|communications.cancel_reminder_plan|1",
    "reminders.subject_override|operator|command|required|none||||0",
    "requests.submit|public|command|required|none|requests.submit|requests.party_override||1",
    "requests.read|public|query|none|none|requests.manage|requests.party_override||1",
    "requests.cancel|public|command|required|required|requests.manage|requests.party_override||1",
    "requests.record_result|internal|command|required|required||||1",
    "requests.complete|internal|command|required|required||||1",
    "requests.fail|internal|command|required|required||||1",
    "requests.party_override|operator|command|required|none||||0",
)

_ERROR_MODULES = (
    Path("src/request_engine/entrypoints/http/errors.py"),
    Path("src/request_engine/modules/booking/api/errors.py"),
    Path("src/request_engine/modules/queue/api/errors.py"),
    Path("src/request_engine/modules/communications/api/errors.py"),
    Path("src/request_engine/modules/requests/api/errors.py"),
)

_EXPECTED_LITERAL_ERROR_CODES = frozenset(
    {
        "active_queue_entry_not_found",
        "already_in_queue",
        "already_on_waitlist",
        "appointment_option_expired",
        "appointment_option_invalid",
        "appointment_unavailable",
        "authentication_required",
        "booking_configuration_error",
        "booking_error",
        "capability_required",
        "communications_error",
        "conflict",
        "database_integrity_error",
        "external_correlation_conflict",
        "http_error",
        "idempotency_conflict",
        "invalid_resource_selection",
        "method_not_allowed",
        "not_found",
        "offering_not_available_for_waitlist",
        "offering_not_bookable",
        "offering_version_not_found",
        "party_authority_required",
        "queue_entry_not_cancellable",
        "queue_entry_not_found",
        "queue_error",
        "queue_inactive",
        "queue_not_found",
        "reminder_plan_not_active",
        "reminder_plan_not_found",
        "request_definition_inactive",
        "request_definition_invalid",
        "request_definition_not_found",
        "request_definition_version_not_found",
        "request_error",
        "request_not_found",
        "request_not_open",
        "request_party_not_usable",
        "request_payload_invalid",
        "request_result_not_defined",
        "reservation_not_cancellable",
        "reservation_not_found",
        "reservation_not_reschedulable",
        "revision_conflict",
        "slot_opportunity_source_conflict",
        "tenant_reference_not_usable",
        "validation_failed",
        "waitlist_entry_not_cancellable",
        "waitlist_entry_not_found",
    }
)


def _public_operations() -> tuple[Any, ...]:
    namespace = runpy.run_path("tests/e2e/http_surface.py")
    return cast(tuple[Any, ...], namespace["PUBLIC_HTTP_OPERATIONS"])


def _literal_error_codes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "ErrorBody":
            continue
        for keyword in node.keywords:
            if keyword.arg != "code":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                codes.add(value.value)
    return codes


def test_v3_public_http_operation_surface_is_frozen() -> None:
    actual = tuple(
        "|".join(
            (
                operation.name,
                operation.method,
                operation.path_template,
                operation.capability or "",
            )
        )
        for operation in _public_operations()
    )
    assert actual == _EXPECTED_OPERATIONS


def test_v3_capability_registry_is_frozen() -> None:
    actual = tuple(
        "|".join(
            (
                definition.key,
                definition.exposure.value,
                definition.kind.value,
                definition.idempotency.value,
                definition.revision.value,
                definition.party_scope or "",
                definition.override_capability or "",
                ",".join(sorted(definition.legacy_aliases)),
                "1" if definition.runtime_available else "0",
            )
        )
        for definition in CAPABILITIES
    )
    assert actual == _EXPECTED_CAPABILITIES
    assert all(definition.schema_version == 1 for definition in CAPABILITIES)


def test_v3_public_error_code_inventory_is_frozen() -> None:
    literal_codes: set[str] = set()
    for path in _ERROR_MODULES:
        literal_codes |= _literal_error_codes(path)
    assert literal_codes == _EXPECTED_LITERAL_ERROR_CODES

    request_errors = Path("src/request_engine/modules/requests/api/errors.py").read_text(
        encoding="utf-8"
    )
    assert '_conflict("request_result_already_recorded"' in request_errors
    assert '_conflict("request_result_required"' in request_errors


def test_v3_operation_capabilities_are_classified() -> None:
    definitions = {definition.key: definition for definition in CAPABILITIES}
    for operation in _public_operations():
        if operation.capability is None:
            assert operation.name == "capabilities.list"
            continue
        definition = definitions[operation.capability]
        assert definition.runtime_available
        assert definition.exposure.value in {"public", "operator"}
        requires_idempotency = definition.idempotency.value == "required"
        assert requires_idempotency is operation.idempotency_required
        assert (definition.kind.value == "command") is operation.mutates
