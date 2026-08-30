from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

F6_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "operational_copilot.interpret",
        "GET",
        "/v1/operational-copilot/interpret",
        "operational_copilot.interpret",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/operational-copilot/interpret",
            query=(("text", "propose recovery for queue 00000000-0000-4000-8000-000000000001"),),
        ),
    ),
)
