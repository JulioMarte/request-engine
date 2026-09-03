"""Replay-view decoding and affected-view assembly for party corrections."""

from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_from_json
from request_engine.modules.tenancy.adapters.db.party_registry_views import document_by_identity
from request_engine.modules.tenancy.application.errors import (
    PartyContactPointNotFound,
    PartyNotFound,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    PartySourceKind,
    RegisteredParty,
)


def replay_party(data: dict[str, object]) -> RegisteredParty:
    return party_from_json(cast(dict[str, object], data["party"]))


def replay_document(
    data: dict[str, object],
    kind: str,
    authority: str,
    normalized_value: str,
    party_id: UUID,
) -> PartyIdentityDocument:
    document = document_by_identity(replay_party(data), kind, authority, normalized_value)
    if document is None:
        raise PartyNotFound(party_id)
    return document


def replay_contact_point(
    data: dict[str, object], party_id: UUID, contact_point_id: UUID
) -> PartyContactPoint:
    contact = contact_point_from_json(cast(dict[str, object], data["contact_point"]))
    if contact.contact_point_id != contact_point_id:
        raise PartyContactPointNotFound(party_id, contact_point_id)
    return contact


def contact_point_from_row(row: RowMapping) -> PartyContactPoint:
    raw_kind = cast(str | None, row["source_kind"])
    return PartyContactPoint(
        party_id=cast(UUID, row["party_id"]),
        contact_point_id=cast(UUID, row["id"]),
        channel=cast(str, row["channel"]),
        normalized_value=cast(str, row["normalized_value"]),
        verified=cast(bool, row["verified"]),
        source_kind=PartySourceKind(raw_kind) if raw_kind else None,
    )


def contact_point_to_json(contact: PartyContactPoint) -> dict[str, object]:
    return {
        "party_id": str(contact.party_id),
        "contact_point_id": str(contact.contact_point_id),
        "channel": contact.channel,
        "normalized_value": contact.normalized_value,
        "verified": contact.verified,
        "source_kind": contact.source_kind.value if contact.source_kind else None,
    }


def contact_point_from_json(data: dict[str, object]) -> PartyContactPoint:
    return PartyContactPoint(
        party_id=UUID(cast(str, data["party_id"])),
        contact_point_id=UUID(cast(str, data["contact_point_id"])),
        channel=cast(str, data["channel"]),
        normalized_value=cast(str, data["normalized_value"]),
        verified=cast(bool, data["verified"]),
        source_kind=(
            PartySourceKind(cast(str, data["source_kind"]))
            if data["source_kind"] is not None
            else None
        ),
    )
