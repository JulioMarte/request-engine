from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

IDENTITY_BINDING_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "identity_binding.list",
        "GET",
        "/v1/identity-bindings",
        "identity.binding.read",
        False,
        False,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe("/v1/identity-bindings"),
    ),
    PublicHttpOperation(
        "identity_binding.get",
        "GET",
        "/v1/identity-bindings/{binding_id}",
        "identity.binding.read",
        False,
        False,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(f"/v1/identity-bindings/{PROBE_UUID}"),
    ),
    PublicHttpOperation(
        "identity_binding.suspend",
        "POST",
        "/v1/identity-bindings/{binding_id}:suspend",
        "identity.bind",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/identity-bindings/{PROBE_UUID}:suspend",
            body={"expected_revision": 1, "provenance_reference": "probe"},
        ),
    ),
    PublicHttpOperation(
        "identity_binding.reactivate",
        "POST",
        "/v1/identity-bindings/{binding_id}:reactivate",
        "identity.bind",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/identity-bindings/{PROBE_UUID}:reactivate",
            body={"expected_revision": 1, "provenance_reference": "probe"},
        ),
    ),
    PublicHttpOperation(
        "identity_binding.revoke",
        "POST",
        "/v1/identity-bindings/{binding_id}:revoke",
        "identity.bind",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/identity-bindings/{PROBE_UUID}:revoke",
            body={"expected_revision": 1, "provenance_reference": "probe"},
        ),
    ),
)
