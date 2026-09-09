from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

AGENT_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "agent.provision",
        "POST",
        "/v1/agents",
        "agent.provision",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/agents",
            body={
                "identity_authority_id": PROBE_UUID,
                "display_name": "Surface Probe Agent",
                "purpose": "surface probe",
                "sponsor_principal_id": PROBE_UUID_2,
                "operating_mode": "autonomous",
                "credential_expires_at": "2030-01-01T00:00:00Z",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "agent.authority.replace",
        "PUT",
        "/v1/agents/{agent_principal_id}/authority",
        "agent.manage_authority",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/agents/{PROBE_UUID}/authority",
            body={
                "expected_authority_revision": 1,
                "desired_capabilities": ["parties.lookup"],
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "agent.policy.read",
        "GET",
        "/v1/agents/{agent_principal_id}/policy",
        "agent.policy.read",
        False,
        False,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(f"/v1/agents/{PROBE_UUID}/policy"),
    ),
    PublicHttpOperation(
        "agent.policy.replace",
        "PUT",
        "/v1/agents/{agent_principal_id}/policy",
        "agent.manage_policy",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/agents/{PROBE_UUID}/policy",
            body={
                "allowed_capabilities": ["parties.lookup"],
                "denied_capabilities": [],
                "risk_ceiling": "low_impact_write",
                "max_mutations_per_minute": 30,
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "agent.suspend",
        "PUT",
        "/v1/agents/{agent_principal_id}/status",
        "agent.suspend",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/agents/{PROBE_UUID}/status",
            body={
                "expected_revision": 1,
                "target_status": "suspended",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
)
