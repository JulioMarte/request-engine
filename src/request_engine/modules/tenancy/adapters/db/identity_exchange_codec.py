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
    PortableContactSuggestion,
    PortableInsuranceIdentifier,
)


def portable_contacts(
    profile: Mapping[str, object], consented_fields: tuple[str, ...]
) -> tuple[PortableContactSuggestion, ...]:
    allowed = set(consented_fields)
    rows = cast(list[dict[str, object]], profile.get("contact_points", []))
    distinct: dict[tuple[str, str], PortableContactSuggestion] = {}
    for row in rows:
        channel = str(row["channel"])
        if channel in {"phone", "whatsapp"} and "phone" not in allowed:
            continue
        if channel == "email" and "email" not in allowed:
            continue
        value = str(row["value"])
        distinct[(channel, value)] = PortableContactSuggestion(channel=channel, value=value)
    return tuple(distinct.values())


def portable_insurance(
    profile: Mapping[str, object], consented_fields: tuple[str, ...]
) -> tuple[PortableInsuranceIdentifier, ...]:
    if "insurance_member" not in consented_fields:
        return ()
    rows = cast(list[dict[str, object]], profile.get("insurance_identifiers", []))
    distinct = {(str(row["issuer"]), str(row["value"])) for row in rows}
    return tuple(
        PortableInsuranceIdentifier(issuer=issuer, value=value)
        for issuer, value in sorted(distinct)
    )


def adoption_to_json(result: IdentityAdoptionResult) -> dict[str, object]:
    return {
        "party": party_to_json(result.party),
        "binding_id": str(result.binding_id),
        "portable_contact_suggestions": [
            {"channel": item.channel, "value": item.value}
            for item in result.portable_contact_suggestions
        ],
        "portable_insurance_identifiers": [
            {"issuer": item.issuer, "value": item.value}
            for item in result.portable_insurance_identifiers
        ],
    }


def adoption_from_json(payload: Mapping[str, object]) -> IdentityAdoptionResult:
    party = party_from_json(cast(dict[str, object], payload["party"]))
    contacts = cast(list[dict[str, object]], payload.get("portable_contact_suggestions", []))
    insurance = cast(list[dict[str, object]], payload.get("portable_insurance_identifiers", []))
    return IdentityAdoptionResult(
        party=party,
        binding_id=UUID(str(payload["binding_id"])),
        portable_contact_suggestions=tuple(
            PortableContactSuggestion(channel=str(item["channel"]), value=str(item["value"]))
            for item in contacts
        ),
        portable_insurance_identifiers=tuple(
            PortableInsuranceIdentifier(issuer=str(item["issuer"]), value=str(item["value"]))
            for item in insurance
        ),
    )
