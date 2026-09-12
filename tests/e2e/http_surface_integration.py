from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

INTEGRATION_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "integration.list",
        "GET",
        "/v1/integrations",
        "integration.read",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/integrations"),
    ),
    PublicHttpOperation(
        "integration.read",
        "GET",
        "/v1/integrations/{integration_principal_id}",
        "integration.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/integrations/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "integration.credential.rotate",
        "POST",
        "/v1/integrations/{integration_principal_id}/credentials:rotate",
        "integration.provision",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/integrations/{PROBE_UUID}/credentials:rotate",
            body={
                "expected_revision": 1,
                "provenance_reference": "surface-probe",
                "credential_expires_at": "2030-01-01T00:00:00Z",
            },
        ),
    ),
    *tuple(
        PublicHttpOperation(
            f"integration.{action}.command",
            "POST",
            "/v1/integrations/{integration_principal_id}:" + action,
            capability,
            True,
            True,
            TenantIsolationMode.CONTEXTUAL,
            HttpProbe(
                f"/v1/integrations/{PROBE_UUID}:" + action,
                body={
                    "expected_revision": 1,
                    "provenance_reference": "surface-probe",
                },
            ),
        )
        for action, capability in (
            ("activate", "integration.provision"),
            ("suspend", "integration.suspend"),
            ("revoke", "integration.suspend"),
        )
    ),
    PublicHttpOperation(
        "integration.provision",
        "POST",
        "/v1/integrations",
        "integration.provision",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/integrations",
            body={
                "identity_authority_id": PROBE_UUID,
                "credential_expires_at": "2030-01-01T00:00:00Z",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "integration.authority.replace",
        "PUT",
        "/v1/integrations/{integration_principal_id}/authority",
        "integration.manage_authority",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/integrations/{PROBE_UUID}/authority",
            body={
                "expected_authority_revision": 1,
                "desired_capabilities": ["parties.lookup"],
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "integration.suspend",
        "PUT",
        "/v1/integrations/{integration_principal_id}/status",
        "integration.suspend",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/integrations/{PROBE_UUID}/status",
            body={
                "expected_revision": 1,
                "target_status": "suspended",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
)
