from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode
from .http_surface_f6_tool_writes import F6_TOOL_WRITE_HTTP_OPERATIONS

UUID_1 = "00000000-0000-4000-8000-000000000001"


def _read(
    name: str,
    path: str,
    probe: HttpProbe,
) -> PublicHttpOperation:
    return PublicHttpOperation(
        name,
        "GET",
        path,
        "operational_copilot.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        probe,
    )


F6_TOOL_READ_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    _read(
        "operational_copilot.tools.resources",
        "/v1/operational-copilot/tools/resources",
        HttpProbe(
            "/v1/operational-copilot/tools/resources",
            query=(("reference", "probe"),),
        ),
    ),
    _read(
        "operational_copilot.tools.offerings",
        "/v1/operational-copilot/tools/offerings",
        HttpProbe(
            "/v1/operational-copilot/tools/offerings",
            query=(("reference", "probe"),),
        ),
    ),
    _read(
        "operational_copilot.tools.queues",
        "/v1/operational-copilot/tools/queues",
        HttpProbe("/v1/operational-copilot/tools/queues"),
    ),
    _read(
        "operational_copilot.tools.location_clock",
        "/v1/operational-copilot/tools/locations/{location_id}/clock",
        HttpProbe(f"/v1/operational-copilot/tools/locations/{UUID_1}/clock"),
    ),
    _read(
        "operational_copilot.tools.assignment_day_end",
        "/v1/operational-copilot/tools/assignments/{assignment_id}/day-end",
        HttpProbe(
            f"/v1/operational-copilot/tools/assignments/{UUID_1}/day-end",
            query=(("weekday", "0"),),
        ),
    ),
    _read(
        "operational_copilot.tools.queue_intake",
        "/v1/operational-copilot/tools/queues/{service_queue_id}/intake",
        HttpProbe(f"/v1/operational-copilot/tools/queues/{UUID_1}/intake"),
    ),
    _read(
        "operational_copilot.tools.recovery_incident",
        "/v1/operational-copilot/tools/queues/{service_queue_id}/recovery-incident",
        HttpProbe(f"/v1/operational-copilot/tools/queues/{UUID_1}/recovery-incident"),
    ),
    _read(
        "operational_copilot.tools.at_risk",
        "/v1/operational-copilot/tools/queues/{service_queue_id}/at-risk-reservations",
        HttpProbe(f"/v1/operational-copilot/tools/queues/{UUID_1}/at-risk-reservations"),
    ),
    _read(
        "operational_copilot.tools.recovery_proposal_read",
        "/v1/operational-copilot/tools/recovery/proposals/{proposal_id}",
        HttpProbe(f"/v1/operational-copilot/tools/recovery/proposals/{UUID_1}"),
    ),
    _read(
        "operational_copilot.tools.discovery_publication",
        "/v1/operational-copilot/tools/discovery/publications/{publication_id}",
        HttpProbe(f"/v1/operational-copilot/tools/discovery/publications/{UUID_1}"),
    ),
)

F6_TOOL_HTTP_OPERATIONS = F6_TOOL_READ_HTTP_OPERATIONS + F6_TOOL_WRITE_HTTP_OPERATIONS
