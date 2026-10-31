from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

# Invalidation-only change feed (ADR 0020). Authorized per topic with existing
# owner read capabilities, so it has no single capability of its own.
CHANGES_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "changes.stream",
        "GET",
        "/v1/changes/stream",
        None,
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/changes/stream", query=(("topics", "day_board"),)),
    ),
)
