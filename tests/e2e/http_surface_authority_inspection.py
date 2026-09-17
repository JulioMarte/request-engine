from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

RESOURCE_AUTHORITY_INSPECTION_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "authority.inspect_resource",
        "POST",
        "/v1/me/authority:inspect",
        "authority.inspect_resource",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/me/authority:inspect",
            body={"operation": "appointments.book", "subject_party_id": PROBE_UUID},
        ),
    ),
)
