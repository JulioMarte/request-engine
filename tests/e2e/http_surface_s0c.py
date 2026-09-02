from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

S0C_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "parties.add_administrative_identifier",
        "POST",
        "/v1/parties/{party_id}/administrative-identifiers",
        "parties.add_administrative_identifier",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/parties/{PROBE_UUID}/administrative-identifiers",
            body={"kind": "insurance_member", "issuer": "ARS Probe", "value": "MEMBER-001"},
        ),
    ),
    PublicHttpOperation(
        "parties.list_administrative_identifiers",
        "GET",
        "/v1/parties/{party_id}/administrative-identifiers",
        "parties.lookup_administrative_identifier",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(f"/v1/parties/{PROBE_UUID}/administrative-identifiers"),
    ),
    PublicHttpOperation(
        "parties.lookup_administrative_identifier",
        "GET",
        "/v1/parties/lookup/administrative-identifier",
        "parties.lookup_administrative_identifier",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe(
            "/v1/parties/lookup/administrative-identifier",
            (("kind", "insurance_member"), ("issuer", "ARS Probe"), ("value", "MEMBER-001")),
        ),
    ),
)
