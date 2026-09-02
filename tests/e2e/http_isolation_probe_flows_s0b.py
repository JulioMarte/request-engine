"""S0b/S0c Party registry tenant-isolation probe flows (`parties.*`).

Expected outcomes are mutation-free for the actor's own tenant. Resource
mutations address a foreign Party the actor cannot see; tenant-scoped lookups
and identifier lists are read-only and filter foreign rows.
"""

from typing import TYPE_CHECKING

from .http_surface import PROBE_UUID, PROBE_UUID_2

if TYPE_CHECKING:
    from .http_isolation_probes import ForeignObjects
    from .http_surface import PublicHttpOperation
    from .tenant_sandbox import TenantSandbox


def foreign_request(
    operation: "PublicHttpOperation",
    actor: "TenantSandbox",
    foreign: "TenantSandbox",
    objects: "ForeignObjects",
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    del actor, objects
    if operation.name == "parties.register":
        return (
            "/v1/parties",
            {},
            {
                "display_name": "Isolation Probe",
                "documents": [{"kind": "cedula", "value": "12345"}],
            },
            422,
        )
    if operation.name == "parties.add_contact_point":
        return (
            f"/v1/parties/{foreign.party_id}/contact-points",
            {},
            {"channel": "phone", "value": "+18295550100"},
            404,
        )
    if operation.name == "parties.confirm_contact_point":
        return (
            f"/v1/parties/{foreign.party_id}/contact-points/{PROBE_UUID_2}/confirm",
            {},
            None,
            404,
        )
    if operation.name == "parties.rename":
        return (
            f"/v1/parties/{foreign.party_id}/rename",
            {},
            {"display_name": "Isolation Probe"},
            404,
        )
    if operation.name == "parties.add_document":
        return (
            f"/v1/parties/{foreign.party_id}/documents",
            {},
            {"kind": "cedula", "value": "40212345678"},
            404,
        )
    if operation.name == "parties.deactivate_contact_point":
        return (
            f"/v1/parties/{foreign.party_id}/contact-points/{PROBE_UUID_2}/deactivate",
            {},
            None,
            404,
        )
    if operation.name == "parties.deactivate":
        return (f"/v1/parties/{foreign.party_id}/deactivate", {}, None, 404)
    if operation.name == "parties.read_revisions":
        return (f"/v1/parties/{foreign.party_id}/revisions", {}, None, 404)
    if operation.name == "parties.rollback_identity":
        return (
            f"/v1/parties/{foreign.party_id}/rollback",
            {},
            {"target_revision": 1},
            404,
        )
    if operation.name == "parties.add_administrative_identifier":
        return (
            f"/v1/parties/{foreign.party_id}/administrative-identifiers",
            {},
            {"kind": "insurance_member", "issuer": "ARS Probe", "value": "MEMBER-001"},
            404,
        )
    if operation.name == "parties.list_administrative_identifiers":
        return (f"/v1/parties/{foreign.party_id}/administrative-identifiers", {}, None, 200)
    if operation.name == "parties.lookup_administrative_identifier":
        return (
            "/v1/parties/lookup/administrative-identifier",
            {"kind": "insurance_member", "issuer": "ARS Probe", "value": "MEMBER-001"},
            None,
            200,
        )
    if operation.name == "staff.register_contact":
        return ("/v1/staff/contacts", {}, {"channel": "phone", "value": "12"}, 422)
    if operation.name == "staff.request_contact_verification":
        return (f"/v1/staff/contacts/{PROBE_UUID}/request-verification", {}, None, 404)
    if operation.name == "staff.confirm_contact":
        return (f"/v1/staff/contacts/{PROBE_UUID}/confirm", {}, {"code": "123456"}, 404)
    if operation.name == "parties.lookup":
        return ("/v1/parties/lookup", {"mode": "phone", "value": "+18295550100"}, None, 200)
    raise AssertionError(f"missing S0b tenant probe for {operation.name}")
