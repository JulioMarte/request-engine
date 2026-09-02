"""Row and idempotency codecs for Party administrative identifiers."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
    PartyAdministrativeIdentifierKind,
)


def identifier_from_mapping(
    row: RowMapping | Mapping[str, object],
) -> PartyAdministrativeIdentifier:
    return PartyAdministrativeIdentifier(
        identifier_id=cast(UUID, row["id"]),
        party_id=cast(UUID, row["party_id"]),
        kind=PartyAdministrativeIdentifierKind(str(row["kind"])),
        issuer=str(row["issuer"]),
        normalized_issuer=str(row["normalized_issuer"]),
        value=str(row["value"]),
        normalized_value=str(row["normalized_value"]),
        active=bool(row["active"]),
    )


def identifier_to_json(identifier: PartyAdministrativeIdentifier) -> dict[str, object]:
    return {
        "id": str(identifier.identifier_id),
        "party_id": str(identifier.party_id),
        "kind": identifier.kind.value,
        "issuer": identifier.issuer,
        "normalized_issuer": identifier.normalized_issuer,
        "value": identifier.value,
        "normalized_value": identifier.normalized_value,
        "active": identifier.active,
    }


def identifier_from_json(payload: Mapping[str, object]) -> PartyAdministrativeIdentifier:
    return PartyAdministrativeIdentifier(
        identifier_id=UUID(str(payload["id"])),
        party_id=UUID(str(payload["party_id"])),
        kind=PartyAdministrativeIdentifierKind(str(payload["kind"])),
        issuer=str(payload["issuer"]),
        normalized_issuer=str(payload["normalized_issuer"]),
        value=str(payload["value"]),
        normalized_value=str(payload["normalized_value"]),
        active=bool(payload["active"]),
    )
