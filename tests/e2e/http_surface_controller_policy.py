from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

CONTROLLER_POLICY_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "controller_policy.adoption_request_create",
        "POST",
        "/v1/controller-policy-adoptions",
        "organization.bootstrap",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/controller-policy-adoptions",
            body={"expected_authority_revision": 1, "reason": "E2E surface classification"},
        ),
    ),
    PublicHttpOperation(
        "controller_policy.adoption_request_get",
        "GET",
        "/v1/controller-policy-adoptions/{request_id}",
        "organization.bootstrap",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe("/v1/controller-policy-adoptions/" + PROBE_UUID),
    ),
    PublicHttpOperation(
        "controller_policy.adoption_request_withdraw",
        "POST",
        "/v1/controller-policy-adoptions/{request_id}:withdraw",
        "organization.bootstrap",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/controller-policy-adoptions/" + PROBE_UUID + ":withdraw",
            body={"expected_request_revision": 1},
        ),
    ),
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
