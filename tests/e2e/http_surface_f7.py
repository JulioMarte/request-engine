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
)
