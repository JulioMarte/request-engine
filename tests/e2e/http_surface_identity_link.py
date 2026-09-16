from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

IDENTITY_LINK_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "identity_link.intent_create",
        "POST",
        "/v1/me/identity-link-intents",
        "identity.link_self",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/me/identity-link-intents",
            body={"target_authority_id": PROBE_UUID, "provenance_reference": "probe"},
        ),
    ),
    PublicHttpOperation(
        "identity_link.intent_confirm",
        "POST",
        "/v1/me/identity-link-intents/{intent_id}:confirm",
        "identity.link_self",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/me/identity-link-intents/{PROBE_UUID}:confirm",
            body={
                "proof": {
                    "native_identity_id": PROBE_UUID_2,
                    "login_handle": "probe@example.test",
                    "password": "probe-password-value",
                },
                "expected_actor_binding_revision": 1,
                "provenance_reference": "probe",
            },
        ),
    ),
)
