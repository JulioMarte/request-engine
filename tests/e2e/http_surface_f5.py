from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

P1 = "00000000-0000-4000-8000-000000000001"
P2 = "00000000-0000-4000-8000-000000000002"

F5_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "operational_recovery.proposal.create",
        "POST",
        "/v1/operational-recovery/service-queues/{service_queue_id}/proposals",
        "operational_recovery.propose",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/service-queues/{P1}/proposals",
            body={"search_days": 7},
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.proposal.read",
        "GET",
        "/v1/operational-recovery/proposals/{proposal_id}",
        "operational_recovery.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/operational-recovery/proposals/{P1}"),
    ),
    PublicHttpOperation(
        "operational_recovery.execute",
        "POST",
        "/v1/operational-recovery/proposals/{proposal_id}/execute",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/proposals/{P1}/execute",
            body={
                "reservation_id": P2,
                "expected_source_fingerprint": "probe-source",
                "expected_proposal_fingerprint": "probe-proposal",
                "notify": False,
            },
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.intake_control",
        "POST",
        "/v1/operational-recovery/incidents/{incident_id}/intake-control",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/incidents/{P1}/intake-control",
            body={"expected_source_revision": 1, "accepting": False},
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.extend_day",
        "POST",
        "/v1/operational-recovery/incidents/{incident_id}/extend-day",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/incidents/{P1}/extend-day",
            body={
                "expected_source_revision": 1,
                "authority_party_id": P2,
                "assignment_id": P2,
                "start_at": "2026-08-28T20:00:00Z",
                "end_at": "2026-08-28T22:00:00Z",
                "expected_location_operational_revision": 1,
                "expected_resource_availability_revision": 1,
                "reason": "probe",
            },
        ),
    ),
)
