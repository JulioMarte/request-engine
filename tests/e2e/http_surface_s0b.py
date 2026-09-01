from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

S0B_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "parties.register",
        "POST",
        "/v1/parties",
        "parties.register",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/parties",
            body={
                "display_name": "S0b Probe",
                "contact_points": [{"channel": "phone", "value": "809-555-1234"}],
            },
        ),
    ),
    PublicHttpOperation(
        "parties.add_contact_point",
        "POST",
        "/v1/parties/{party_id}/contact-points",
        "parties.add_contact_point",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/parties/{PROBE_UUID}/contact-points",
            body={"channel": "whatsapp", "value": "+18295550100"},
        ),
    ),
    PublicHttpOperation(
        "parties.confirm_contact_point",
        "POST",
        "/v1/parties/{party_id}/contact-points/{contact_point_id}/confirm",
        "parties.confirm_contact_point",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/parties/{PROBE_UUID}/contact-points/{PROBE_UUID_2}/confirm",
        ),
    ),
    PublicHttpOperation(
        "parties.lookup",
        "GET",
        "/v1/parties/lookup",
        "parties.lookup",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(
            "/v1/parties/lookup",
            (("mode", "phone"), ("value", "+18295550100")),
        ),
    ),
)
