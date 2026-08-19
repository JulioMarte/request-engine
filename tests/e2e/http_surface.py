from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

HttpMethod = Literal["GET", "POST"]
PROBE_UUID = "00000000-0000-4000-8000-000000000001"
PROBE_UUID_2 = "00000000-0000-4000-8000-000000000002"


class TenantIsolationMode(StrEnum):
    FILTERED = "filtered"
    NOT_FOUND = "not_found"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True, slots=True)
class HttpProbe:
    path: str
    query: tuple[tuple[str, str], ...] = ()
    body: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PublicHttpOperation:
    name: str
    method: HttpMethod
    path_template: str
    capability: str | None
    mutates: bool
    idempotency_required: bool
    tenant_isolation: TenantIsolationMode
    probe: HttpProbe

    @property
    def operation_key(self) -> tuple[str, str]:
        return self.method, self.path_template


PUBLIC_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "capabilities.list",
        "GET",
        "/v1/capabilities",
        None,
        False,
        False,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe("/v1/capabilities"),
    ),
    PublicHttpOperation(
        "business.read",
        "GET",
        "/v1/business",
        "business.get_info",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/business"),
    ),
    PublicHttpOperation(
        "catalog.offerings.list",
        "GET",
        "/v1/catalog/offerings",
        "catalog.search_offerings",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/catalog/offerings"),
    ),
    PublicHttpOperation(
        "catalog.offerings.read",
        "GET",
        "/v1/catalog/offerings/{offering_key}",
        "catalog.get_offering_details",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe("/v1/catalog/offerings/probe-offering"),
    ),
    PublicHttpOperation(
        "appointments.find_slots",
        "GET",
        "/v1/appointments/slots",
        "appointments.find_slots",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/appointments/slots",
            (
                ("offering_version_id", PROBE_UUID),
                ("window_start", "2030-01-07T13:00:00+00:00"),
                ("window_end", "2030-01-07T16:00:00+00:00"),
            ),
        ),
    ),
    PublicHttpOperation(
        "appointments.book",
        "POST",
        "/v1/appointments",
        "appointments.book",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/appointments",
            body={"option_id": "e2e-security-probe-option", "subject_party_id": PROBE_UUID},
        ),
    ),
    PublicHttpOperation(
        "appointments.read",
        "GET",
        "/v1/appointments/{reservation_id}",
        "appointments.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/appointments/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "appointments.cancel",
        "POST",
        "/v1/appointments/{reservation_id}/cancel",
        "appointments.cancel",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/appointments/{PROBE_UUID}/cancel",
            body={"expected_revision": 1, "reason": "e2e probe"},
        ),
    ),
    PublicHttpOperation(
        "appointments.reschedule",
        "POST",
        "/v1/appointments/{reservation_id}/reschedule",
        "appointments.reschedule",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/appointments/{PROBE_UUID}/reschedule",
            body={"option_id": "e2e-security-probe-option", "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "appointments.attendance",
        "POST",
        "/v1/appointments/{reservation_id}/attendance",
        "appointments.confirm_attendance",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/appointments/{PROBE_UUID}/attendance",
            body={"response": "accepted", "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "queue.list",
        "GET",
        "/v1/queues",
        "queue.list",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/queues"),
    ),
    PublicHttpOperation(
        "queue.join",
        "POST",
        "/v1/queues/{queue_id}/join",
        "queue.join",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/queues/{PROBE_UUID}/join", body={"subject_party_id": PROBE_UUID_2}),
    ),
    PublicHttpOperation(
        "queue.status",
        "GET",
        "/v1/queues/{queue_id}/status",
        "queue.status",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/queues/{PROBE_UUID}/status", (("subject_party_id", PROBE_UUID_2),)),
    ),
    PublicHttpOperation(
        "queue.leave",
        "POST",
        "/v1/queues/{queue_id}/entries/{queue_entry_id}/leave",
        "queue.leave",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queues/{PROBE_UUID}/entries/{PROBE_UUID_2}/leave",
            body={"expected_revision": 1, "reason": "e2e probe"},
        ),
    ),
    PublicHttpOperation(
        "queue.call_next",
        "POST",
        "/v1/queues/{queue_id}/call-next",
        "queue.call_next",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/queues/{PROBE_UUID}/call-next"),
    ),
    PublicHttpOperation(
        "waitlist.join",
        "POST",
        "/v1/waitlist",
        "waitlist.join",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/waitlist", body={"offering_id": PROBE_UUID, "subject_party_id": PROBE_UUID_2}
        ),
    ),
    PublicHttpOperation(
        "waitlist.read",
        "GET",
        "/v1/waitlist/{waitlist_entry_id}",
        "waitlist.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/waitlist/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "waitlist.leave",
        "POST",
        "/v1/waitlist/{waitlist_entry_id}/leave",
        "waitlist.leave",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/waitlist/{PROBE_UUID}/leave", body={"expected_revision": 1, "reason": "e2e probe"}
        ),
    ),
    PublicHttpOperation(
        "requests.submit",
        "POST",
        "/v1/requests/definitions/{request_key}/submit",
        "requests.submit",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/requests/definitions/probe_request/submit",
            body={"payload": {"message": "e2e probe"}},
        ),
    ),
    PublicHttpOperation(
        "requests.read",
        "GET",
        "/v1/requests/{request_id}",
        "requests.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/requests/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "requests.cancel",
        "POST",
        "/v1/requests/{request_id}/cancel",
        "requests.cancel",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/requests/{PROBE_UUID}/cancel",
            body={"reason": "e2e probe", "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "reminders.create",
        "POST",
        "/v1/reminders",
        "reminders.create_plan",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/reminders",
            body={
                "subject_party_id": PROBE_UUID,
                "purpose": "medication",
                "timezone": "America/Santo_Domingo",
                "daily_times": ["09:00:00"],
                "template_key": "e2e-probe",
                "template_version": 1,
            },
        ),
    ),
    PublicHttpOperation(
        "reminders.read",
        "GET",
        "/v1/reminders/{reminder_plan_id}",
        "reminders.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/reminders/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "reminders.cancel",
        "POST",
        "/v1/reminders/{reminder_plan_id}/cancel",
        "reminders.cancel_plan",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/reminders/{PROBE_UUID}/cancel",
            body={"expected_revision": 1, "reason": "e2e probe"},
        ),
    ),
)


def operation_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS)
