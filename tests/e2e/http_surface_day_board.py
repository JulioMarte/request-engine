from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

DAY_BOARD_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "appointments.day_board",
        "GET",
        "/v1/appointments/day-board",
        "appointments.day_board",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(
            "/v1/appointments/day-board",
            query=(
                ("window_start", "2030-01-07T13:00:00+00:00"),
                ("window_end", "2030-01-07T16:00:00+00:00"),
            ),
        ),
    ),
    PublicHttpOperation(
        "appointments.calendar",
        "GET",
        "/v1/appointments/calendar",
        "appointments.day_board",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(
            "/v1/appointments/calendar",
            query=(
                ("window_start", "2030-01-06T00:00:00+00:00"),
                ("window_end", "2030-01-20T00:00:00+00:00"),
            ),
        ),
    ),
    PublicHttpOperation(
        "front_desk.serving_resources",
        "GET",
        "/v1/locations/{location_id}/serving-resources",
        "service_session.start",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/locations/{PROBE_UUID}/serving-resources"),
    ),
)
