from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

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
)
