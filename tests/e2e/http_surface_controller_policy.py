from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

CONTROLLER_POLICY_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "controller_policy.upgrade",
        "POST",
        "/v1/controller-policy-upgrades",
        "controller_policy_upgrade",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/controller-policy-upgrades",
            body={
                "target_principal_id": PROBE_UUID,
                "source_policy_key": "tenant-controller-v1",
                "target_policy_key": "tenant-controller-v3",
                "expected_authority_revision": 1,
            },
        ),
    ),
)
