from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

S5_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "queue.operator_select",
        "POST",
        "/v1/queue-entries/{queue_entry_id}/operator-select",
        "queue.operator_select",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queue-entries/{PROBE_UUID}/operator-select",
            body={"reason": "urgent", "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "queue.recall_hold",
        "POST",
        "/v1/queue-entries/{queue_entry_id}/recall-hold",
        "queue.recall_hold",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queue-entries/{PROBE_UUID}/recall-hold",
            body={
                "condition_kind": "until_customer_initiates",
                "expected_revision": 1,
                "reason": "stepped out",
            },
        ),
    ),
    PublicHttpOperation(
        "queue.skip",
        "POST",
        "/v1/queue-entries/{queue_entry_id}/skip",
        "queue.skip",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/queue-entries/{PROBE_UUID}/skip",
            body={"reason": "no_response", "expected_revision": 1},
        ),
    ),
)
