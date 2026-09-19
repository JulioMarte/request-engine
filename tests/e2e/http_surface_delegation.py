from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

DELEGATION_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "delegation.create",
        "POST",
        "/v1/delegations",
        "delegation.create",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/delegations",
            body={
                "delegate_principal_id": PROBE_UUID,
                "purpose": "surface probe",
                "allowed_capabilities": ["parties.lookup"],
                "not_before": "2030-01-01T00:00:00Z",
                "expires_at": "2030-01-01T02:00:00Z",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "delegation.revoke",
        "POST",
        "/v1/delegations/{delegation_id}/revoke",
        "delegation.revoke",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/delegations/{PROBE_UUID}/revoke",
            body={
                "expected_revision": 1,
                "provenance_reference": "surface-probe",
            },
        ),
    ),
)
