from .http_surface import (
    PROBE_UUID,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

S0D_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "identity_exchange.publish",
        "POST",
        "/v1/parties/{party_id}/portable-profile",
        "identity_exchange.publish",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/parties/{PROBE_UUID}/portable-profile",
            body={
                "document_kind": "cedula",
                "consented_fields": ["display_name"],
                "proof_kind": "operator_document_witness",
            },
        ),
    ),
    PublicHttpOperation(
        "identity_exchange.match",
        "POST",
        "/v1/identity-exchange/matches",
        "identity_exchange.match",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/identity-exchange/matches",
            body={
                "document_kind": "cedula",
                "document_value": "40212345678",
                "proof_kind": "operator_document_witness",
            },
        ),
    ),
    PublicHttpOperation(
        "identity_exchange.adopt",
        "POST",
        "/v1/identity-exchange/adoptions",
        "identity_exchange.adopt",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/identity-exchange/adoptions",
            body={
                "candidate_ref": PROBE_UUID,
                "document_kind": "cedula",
                "document_value": "40212345678",
                "consented_fields": ["display_name"],
                "proof_kind": "operator_document_witness",
            },
        ),
    ),
)
