from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

STAFF_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "staff.invite.native",
        "POST",
        "/v1/staff/members/native",
        "staff.invite",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/staff/members/native",
            body={
                "identity_authority_id": PROBE_UUID,
                "native_identity_id": PROBE_UUID_2,
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "staff.authority.replace",
        "PUT",
        "/v1/staff/members/{membership_id}/authority",
        "staff.manage_authority",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/staff/members/{PROBE_UUID}/authority",
            body={
                "expected_authority_revision": 1,
                "desired_capabilities": ["staff.invite"],
                "provenance_reference": "surface-probe",
            },
        ),
    ),
    PublicHttpOperation(
        "staff.membership.transition",
        "PUT",
        "/v1/staff/members/{membership_id}/status",
        "staff.manage_membership",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/staff/members/{PROBE_UUID}/status",
            body={
                "expected_revision": 1,
                "target_status": "suspended",
                "provenance_reference": "surface-probe",
            },
        ),
    ),
)
