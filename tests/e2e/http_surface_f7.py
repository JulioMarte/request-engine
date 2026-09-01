from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

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
)
