"""S0c administrative-identifier tenant-isolation probe flows."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .http_isolation_probes import ForeignObjects
    from .http_surface import PublicHttpOperation
    from .tenant_sandbox import TenantSandbox

_FOREIGN_ISSUER = "ARS Isolation Foreign"
_FOREIGN_VALUE = "FOREIGN-POLICY-001"


def foreign_request(
    operation: "PublicHttpOperation",
    actor: "TenantSandbox",
    foreign: "TenantSandbox",
    objects: "ForeignObjects",
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    del actor, objects
    if operation.name == "parties.add_administrative_identifier":
        return (
            f"/v1/parties/{foreign.party_id}/administrative-identifiers",
            {},
            {
                "kind": "insurance_member",
                "issuer": "ARS Isolation Actor",
                "value": "ACTOR-POLICY-001",
            },
            404,
        )
    if operation.name == "parties.list_administrative_identifiers":
        return (
            f"/v1/parties/{foreign.party_id}/administrative-identifiers",
            {},
            None,
            200,
        )
    if operation.name == "parties.lookup_administrative_identifier":
        return (
            "/v1/parties/lookup/administrative-identifier",
            {
                "kind": "insurance_member",
                "issuer": _FOREIGN_ISSUER,
                "value": _FOREIGN_VALUE,
            },
            None,
            200,
        )
    raise AssertionError(f"missing S0c tenant probe for {operation.name}")


def foreign_identifier() -> dict[str, str]:
    return {
        "kind": "insurance_member",
        "issuer": _FOREIGN_ISSUER,
        "value": _FOREIGN_VALUE,
    }
