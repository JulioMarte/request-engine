"""Replay-view decoding and affected-view assembly for party corrections.

A correction's idempotency replay payload stores the authoritative party
snapshot (`party`) and, for contact-point deactivation, the affected contact
point (`contact_point`) as it exists after the command. Replays return these
serialized views; nothing is recomputed from live rows.
"""

from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_from_json
from request_engine.modules.tenancy.adapters.db.party_registry_views import document_by_kind_value
from request_engine.modules.tenancy.application.errors import (
    PartyContactPointNotFound,
    PartyNotFound,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
    RegisteredVia,
)


def replay_party(data: dict[str, object]) -> RegisteredParty:
    return party_from_json(cast(dict[str, object], data["party"]))


def replay_document(
    data: dict[str, object], kind: str, normalized_value: str, party_id: UUID
) -> PartyIdentityDocument:
    document = document_by_kind_value(replay_party(data), kind, normalized_value)
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
    raw_via = cast(str | None, row["registered_via"])
    return PartyContactPoint(
        party_id=cast(UUID, row["party_id"]),
        contact_point_id=cast(UUID, row["id"]),
        channel=cast(str, row["channel"]),
        normalized_value=cast(str, row["normalized_value"]),
        verified=cast(bool, row["verified"]),
        registered_via=RegisteredVia(raw_via) if raw_via else None,
    )


def contact_point_to_json(contact: PartyContactPoint) -> dict[str, object]:
    return {
        "party_id": str(contact.party_id),
        "contact_point_id": str(contact.contact_point_id),
        "channel": contact.channel,
        "normalized_value": contact.normalized_value,
        "verified": contact.verified,
        "registered_via": contact.registered_via.value if contact.registered_via else None,
    }


def contact_point_from_json(data: dict[str, object]) -> PartyContactPoint:
    return PartyContactPoint(
        party_id=UUID(cast(str, data["party_id"])),
        contact_point_id=UUID(cast(str, data["contact_point_id"])),
        channel=cast(str, data["channel"]),
        normalized_value=cast(str, data["normalized_value"]),
        verified=cast(bool, data["verified"]),
        registered_via=(
            RegisteredVia(cast(str, data["registered_via"]))
            if data["registered_via"] is not None
            else None
        ),
    )
