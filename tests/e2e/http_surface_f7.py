from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

F7_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "appointments.arrival_estimate",
        "POST",
        "/v1/appointments/{reservation_id}/arrival-estimate",
        "appointments.record_arrival_estimate",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/appointments/{PROBE_UUID}/arrival-estimate",
            body={
                "estimated_arrival_at": "2026-09-01T10:20:00+00:00",
                "expected_revision": 1,
            },
        ),
    ),
    PublicHttpOperation(
        "front_desk.day_board",
        "GET",
        "/v1/front-desk/day-board",
        "front_desk.day_board.read",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(
            "/v1/front-desk/day-board",
            query=(
                ("window_start", "2030-01-07T00:00:00+00:00"),
                ("window_end", "2030-01-08T00:00:00+00:00"),
            ),
        ),
    ),
    PublicHttpOperation(
        "queue.operator_select",
        "POST",
        "/v1/queues/{queue_id}/entries/{queue_entry_id}/operator-select",
        "queue.operator_select",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queues/{PROBE_UUID}/entries/{PROBE_UUID_2}/operator-select",
            body={"expected_revision": 1, "reason": "operator_override"},
        ),
    ),
    PublicHttpOperation(
        "queue.recall_hold",
        "POST",
        "/v1/queues/{queue_id}/entries/{queue_entry_id}/recall-hold",
        "queue.recall_hold",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queues/{PROBE_UUID}/entries/{PROBE_UUID_2}/recall-hold",
            body={
                "expected_revision": 1,
                "kind": "until_customer_initiates",
                "release_at": None,
                "reason": "probe",
            },
        ),
    ),
    PublicHttpOperation(
        "queue.release_recall_hold",
        "POST",
        "/v1/queues/{queue_id}/entries/{queue_entry_id}/recall-hold/release",
        "queue.release_recall_hold",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queues/{PROBE_UUID}/entries/{PROBE_UUID_2}/recall-hold/release",
            body={"hold_id": PROBE_UUID, "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "queue.skip",
        "POST",
        "/v1/queues/{queue_id}/skip",
        "queue.skip",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queues/{PROBE_UUID}/skip",
            body={"reason": "operator_override"},
        ),
    ),
)
