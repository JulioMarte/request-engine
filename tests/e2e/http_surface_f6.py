from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

F6_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "operational_copilot.interpret",
        "POST",
        "/v1/operational-copilot/interpret",
        "operational_copilot.interpret",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/operational-copilot/interpret",
            body={"text": "propose recovery for queue 00000000-0000-4000-8000-000000000001"},
        ),
    ),
)
