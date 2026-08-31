from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

UUID_1 = "00000000-0000-4000-8000-000000000001"
UUID_2 = "00000000-0000-4000-8000-000000000002"


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


F6_TOOL_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
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
        "operational_copilot.tools.day_extension",
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
