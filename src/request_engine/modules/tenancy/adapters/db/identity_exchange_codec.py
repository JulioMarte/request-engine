"""Portable-profile parsing and idempotency codecs for S0d identity adoption."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from request_engine.modules.tenancy.adapters.db.party_registry_codec import (
    party_from_json,
    party_to_json,
)
from request_engine.modules.tenancy.contracts.identity_exchange import (
    IdentityAdoptionResult,
    PortableInsuranceIdentifier,
)
from request_engine.modules.tenancy.contracts.party_registry import PartyContactPointInput


def portable_display_name(profile: Mapping[str, object]) -> str:
    value = profile.get("display_name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("portable profile does not contain a usable display_name")
    return value.strip()


def portable_contacts(
    profile: Mapping[str, object], consented_fields: tuple[str, ...]
) -> tuple[PartyContactPointInput, ...]:
    allowed = set(consented_fields)
    rows = cast(list[dict[str, object]], profile.get("contact_points", []))
    result: list[PartyContactPointInput] = []
    for row in rows:
        channel = str(row["channel"])
        if channel in {"phone", "whatsapp"} and "phone" not in allowed:
            continue
        if channel == "email" and "email" not in allowed:
            continue
        result.append(PartyContactPointInput(channel=channel, value=str(row["value"])))
    return tuple(result)


def portable_insurance(
    profile: Mapping[str, object], consented_fields: tuple[str, ...]
) -> tuple[PortableInsuranceIdentifier, ...]:
    if "insurance_member" not in consented_fields:
        return ()
    rows = cast(list[dict[str, object]], profile.get("insurance_identifiers", []))
    return tuple(
        PortableInsuranceIdentifier(issuer=str(row["issuer"]), value=str(row["value"]))
        for row in rows
    )


def adoption_to_json(result: IdentityAdoptionResult) -> dict[str, object]:
    return {
        "party": party_to_json(result.party),
        "binding_id": str(result.binding_id),
        "portable_insurance_identifiers": [
            {"issuer": item.issuer, "value": item.value}
            for item in result.portable_insurance_identifiers
        ],
    }


def adoption_from_json(payload: Mapping[str, object]) -> IdentityAdoptionResult:
    party = party_from_json(cast(dict[str, object], payload["party"]))
    insurance = cast(list[dict[str, object]], payload.get("portable_insurance_identifiers", []))
    return IdentityAdoptionResult(
        party=party,
        binding_id=UUID(str(payload["binding_id"])),
        portable_insurance_identifiers=tuple(
            PortableInsuranceIdentifier(issuer=str(item["issuer"]), value=str(item["value"]))
            for item in insurance
        ),
    )
