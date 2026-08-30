from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

P1 = "00000000-0000-4000-8000-000000000001"
P2 = "00000000-0000-4000-8000-000000000002"

PROPOSAL_ACTION_BODY: dict[str, object] = {
    "expected_source_revision": 1,
    "proposal_id": P2,
    "reservation_id": P2,
    "expected_source_fingerprint": "probe-source",
    "expected_proposal_fingerprint": "probe-proposal",
    "allow_subject_override": False,
}

F5_WORKFLOW_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
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
            body={
                "expected_source_revision": 1,
                "expected_intake_revision": 1,
                "accepting": False,
            },
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
    PublicHttpOperation(
        "operational_recovery.reschedule_action",
        "POST",
        "/v1/operational-recovery/incidents/{incident_id}/reschedule",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/incidents/{P1}/reschedule",
            body=PROPOSAL_ACTION_BODY,
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.replace_resource_action",
        "POST",
        "/v1/operational-recovery/incidents/{incident_id}/replace-resource",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/incidents/{P1}/replace-resource",
            body=PROPOSAL_ACTION_BODY,
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.communicate_impact",
        "POST",
        "/v1/operational-recovery/incidents/{incident_id}/communicate-impact",
        "operational_recovery.execute",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/incidents/{P1}/communicate-impact",
            body={
                "expected_source_revision": 1,
                "recipient_party_id": P2,
                "message": "probe",
            },
        ),
    ),
    PublicHttpOperation(
        "operational_recovery.configure_autonomy",
        "POST",
        "/v1/operational-recovery/queues/{service_queue_id}/autonomy-policy",
        "operational_recovery.configure_autonomy",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/operational-recovery/queues/{P1}/autonomy-policy",
            body={
                "enabled": True,
                "max_delay_minutes": 60,
                "max_auto_actions_per_incident": 1,
            },
        ),
    ),
)
