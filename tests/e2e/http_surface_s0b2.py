"""R2 party revision surface classification (`parties.read_revisions`,
`parties.rollback_identity`) plus the staff administrative contact surface
(`staff.manage_own_admin_contact`, `staff.confirm_own_admin_contact`).
"""

from .http_surface import PROBE_UUID, HttpProbe, PublicHttpOperation, TenantIsolationMode

S0B2_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "parties.read_revisions",
        "GET",
        "/v1/parties/{party_id}/revisions",
        "parties.read_revisions",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/parties/{PROBE_UUID}/revisions"),
    ),
    PublicHttpOperation(
        "parties.rollback_identity",
        "POST",
        "/v1/parties/{party_id}/rollback",
        "parties.rollback_identity",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/parties/{PROBE_UUID}/rollback",
            body={"target_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "staff.register_contact",
        "POST",
        "/v1/staff/contacts",
        "staff.manage_own_admin_contact",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/staff/contacts",
            body={"channel": "phone", "value": "12"},
        ),
    ),
    PublicHttpOperation(
        "staff.request_contact_verification",
        "POST",
        "/v1/staff/contacts/{contact_id}/request-verification",
        "staff.manage_own_admin_contact",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/staff/contacts/{PROBE_UUID}/request-verification"),
    ),
    PublicHttpOperation(
        "staff.confirm_contact",
        "POST",
        "/v1/staff/contacts/{contact_id}/confirm",
        "staff.confirm_own_admin_contact",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/staff/contacts/{PROBE_UUID}/confirm",
            body={"code": "123456"},
        ),
    ),
)
