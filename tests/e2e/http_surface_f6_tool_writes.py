from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

UUID_1 = "00000000-0000-4000-8000-000000000001"
UUID_2 = "00000000-0000-4000-8000-000000000002"


def _write(name: str, path: str, body: dict[str, object]) -> PublicHttpOperation:
    return PublicHttpOperation(
        name,
        "POST",
        path,
        "operational_copilot.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(path, body=body),
    )


F6_TOOL_WRITE_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    _write(
        "operational_copilot.tools.recovery_proposal",
        "/v1/operational-copilot/tools/recovery/proposals",
        {"service_queue_id": UUID_1, "search_days": 7},
    ),
    _write(
        "operational_copilot.tools.recovery_execution",
        "/v1/operational-copilot/tools/recovery/executions",
        {"proposal_id": UUID_1, "reservation_id": UUID_2},
    ),
    _write(
        "operational_copilot.tools.recovery_intake",
        "/v1/operational-copilot/tools/recovery/intake",
        {
            "incident_id": UUID_1,
            "accepting": False,
            "expected_source_revision": 0,
            "expected_intake_revision": 0,
        },
    ),
    _write(
        "operational_copilot.tools.recovery_day_extension",
        "/v1/operational-copilot/tools/recovery/day-extensions",
        {
            "incident_id": UUID_1,
            "assignment_id": UUID_2,
            "start_at": "2030-01-07T13:00:00+00:00",
            "end_at": "2030-01-07T14:00:00+00:00",
            "expected_source_revision": 0,
            "expected_location_operational_revision": 0,
            "expected_resource_availability_revision": 0,
            "reason": "probe",
        },
    ),
    _write(
        "operational_copilot.tools.operational_intake",
        "/v1/operational-copilot/tools/queues/intake-control",
        {
            "service_queue_id": UUID_1,
            "accepting": False,
            "expected_intake_revision": 1,
            "reason": "probe",
        },
    ),
    _write(
        "operational_copilot.tools.operational_day_extension",
        "/v1/operational-copilot/tools/assignments/day-extensions",
        {
            "assignment_id": UUID_1,
            "start_at": "2030-01-07T13:00:00+00:00",
            "end_at": "2030-01-07T14:00:00+00:00",
            "expected_resource_availability_revision": 1,
            "reason": "probe",
        },
    ),
    _write(
        "operational_copilot.tools.discovery_publish",
        "/v1/operational-copilot/tools/discovery/publications",
        {
            "offering_id": UUID_1,
            "location_id": UUID_2,
            "effective_start": "2030-01-07T13:00:00+00:00",
        },
    ),
    _write(
        "operational_copilot.tools.discovery_revoke",
        "/v1/operational-copilot/tools/discovery/revocations",
        {"publication_id": UUID_1, "expected_revision": 0},
    ),
)
