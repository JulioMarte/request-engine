from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

HttpMethod = Literal["GET", "POST"]

PROBE_UUID = "00000000-0000-4000-8000-000000000001"
PROBE_UUID_2 = "00000000-0000-4000-8000-000000000002"
PROBE_UUID_3 = "00000000-0000-4000-8000-000000000003"
PROBE_UUID_4 = "00000000-0000-4000-8000-000000000004"


class TenantIsolationMode(StrEnum):
    """Expected behavior when an actor targets data owned by another tenant."""

    FILTERED = "filtered"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class HttpProbe:
    path: str
    query: tuple[tuple[str, str], ...] = ()
    body: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PublicHttpOperation:
    """Executable E2E classification for one public Request Engine operation."""

    name: str
    method: HttpMethod
    path_template: str
    capability: str
    mutates: bool
    idempotency_required: bool
    tenant_isolation: TenantIsolationMode
    probe: HttpProbe

    @property
    def operation_key(self) -> tuple[str, str]:
        return self.method, self.path_template


PUBLIC_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        name="business.read",
        method="GET",
        path_template="/v1/business",
        capability="business.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.FILTERED,
        probe=HttpProbe(path="/v1/business"),
    ),
    PublicHttpOperation(
        name="catalog.offerings.list",
        method="GET",
        path_template="/v1/catalog/offerings",
        capability="catalog.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.FILTERED,
        probe=HttpProbe(path="/v1/catalog/offerings"),
    ),
    PublicHttpOperation(
        name="catalog.offerings.read",
        method="GET",
        path_template="/v1/catalog/offerings/{offering_key}",
        capability="catalog.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(path="/v1/catalog/offerings/probe-offering"),
    ),
    PublicHttpOperation(
        name="booking.slots.find",
        method="GET",
        path_template="/v1/appointments/slots",
        capability="booking.find_slots",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path="/v1/appointments/slots",
            query=(
                ("offering_version_id", PROBE_UUID),
                ("location_id", PROBE_UUID_2),
                ("window_start", "2030-01-07T13:00:00+00:00"),
                ("window_end", "2030-01-07T16:00:00+00:00"),
            ),
        ),
    ),
    PublicHttpOperation(
        name="booking.appointments.book",
        method="POST",
        path_template="/v1/appointments",
        capability="booking.book_appointment",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path="/v1/appointments",
            body={
                "offering_version_id": PROBE_UUID,
                "subject_party_id": PROBE_UUID_2,
                "location_id": PROBE_UUID_3,
                "start_at": "2030-01-07T13:00:00+00:00",
                "resources": [
                    {"requirement_id": PROBE_UUID_3, "resource_id": PROBE_UUID_4}
                ],
            },
        ),
    ),
    PublicHttpOperation(
        name="booking.appointments.read",
        method="GET",
        path_template="/v1/appointments/{reservation_id}",
        capability="booking.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(path=f"/v1/appointments/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        name="booking.appointments.cancel",
        method="POST",
        path_template="/v1/appointments/{reservation_id}/cancel",
        capability="booking.cancel_reservation",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/appointments/{PROBE_UUID}/cancel",
            body={"reason": "e2e security probe"},
        ),
    ),
    PublicHttpOperation(
        name="booking.appointments.reschedule",
        method="POST",
        path_template="/v1/appointments/{reservation_id}/reschedule",
        capability="booking.reschedule_reservation",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/appointments/{PROBE_UUID}/reschedule",
            body={
                "start_at": "2030-01-07T14:00:00+00:00",
                "location_id": PROBE_UUID_2,
                "resources": [
                    {"requirement_id": PROBE_UUID_3, "resource_id": PROBE_UUID_4}
                ],
            },
        ),
    ),
    PublicHttpOperation(
        name="queue.list",
        method="GET",
        path_template="/v1/queues",
        capability="queue.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.FILTERED,
        probe=HttpProbe(path="/v1/queues"),
    ),
    PublicHttpOperation(
        name="queue.join",
        method="POST",
        path_template="/v1/queues/{queue_id}/join",
        capability="queue.join",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/queues/{PROBE_UUID}/join",
            body={"subject_party_id": PROBE_UUID_2},
        ),
    ),
    PublicHttpOperation(
        name="queue.status",
        method="GET",
        path_template="/v1/queues/{queue_id}/status",
        capability="queue.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/queues/{PROBE_UUID}/status",
            query=(("subject_party_id", PROBE_UUID_2),),
        ),
    ),
    PublicHttpOperation(
        name="queue.leave",
        method="POST",
        path_template="/v1/queues/{queue_id}/leave",
        capability="queue.leave",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/queues/{PROBE_UUID}/leave",
            body={"subject_party_id": PROBE_UUID_2, "reason": "e2e security probe"},
        ),
    ),
    PublicHttpOperation(
        name="queue.call_next",
        method="POST",
        path_template="/v1/queues/{queue_id}/call-next",
        capability="queue.call_next",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(path=f"/v1/queues/{PROBE_UUID}/call-next"),
    ),
    PublicHttpOperation(
        name="requests.submit",
        method="POST",
        path_template="/v1/requests/definitions/{request_key}/submit",
        capability="requests.submit",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path="/v1/requests/definitions/probe_request/submit",
            body={"payload": {"message": "security probe"}},
        ),
    ),
    PublicHttpOperation(
        name="requests.read",
        method="GET",
        path_template="/v1/requests/{request_id}",
        capability="requests.read",
        mutates=False,
        idempotency_required=False,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(path=f"/v1/requests/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        name="requests.record_result",
        method="POST",
        path_template="/v1/requests/{request_id}/result",
        capability="requests.record_result",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/requests/{PROBE_UUID}/result",
            body={"result_payload": {"accepted": True}, "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        name="requests.complete",
        method="POST",
        path_template="/v1/requests/{request_id}/complete",
        capability="requests.complete",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/requests/{PROBE_UUID}/complete",
            body={"result_payload": {"accepted": True}, "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        name="requests.cancel",
        method="POST",
        path_template="/v1/requests/{request_id}/cancel",
        capability="requests.cancel",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/requests/{PROBE_UUID}/cancel",
            body={"reason": "e2e security probe", "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        name="requests.fail",
        method="POST",
        path_template="/v1/requests/{request_id}/fail",
        capability="requests.fail",
        mutates=True,
        idempotency_required=True,
        tenant_isolation=TenantIsolationMode.NOT_FOUND,
        probe=HttpProbe(
            path=f"/v1/requests/{PROBE_UUID}/fail",
            body={"error_class": "e2e_probe", "details": {}, "expected_revision": 1},
        ),
    ),
)


def operation_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS)
