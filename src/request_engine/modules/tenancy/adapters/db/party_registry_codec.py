"""Party registry view assembly and idempotent-replay JSON serialization."""

from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
    RegisteredVia,
)


def contact_point_views_from_rows(
    rows: list[RowMapping],
) -> tuple[PartyContactPoint, ...]:
    views: list[PartyContactPoint] = []
    for row in rows:
        raw_via = cast(str | None, row["registered_via"])
        views.append(
            PartyContactPoint(
                party_id=cast(UUID, row["party_id"]),
                contact_point_id=cast(UUID, row["id"]),
                channel=cast(str, row["channel"]),
                normalized_value=cast(str, row["normalized_value"]),
                verified=cast(bool, row["verified"]),
                registered_via=RegisteredVia(raw_via) if raw_via else None,
            )
        )
    return tuple(views)


def document_views_from_rows(rows: list[RowMapping]) -> tuple[PartyIdentityDocument, ...]:
    return tuple(
        PartyIdentityDocument(
            party_id=cast(UUID, row["party_id"]),
            document_id=cast(UUID, row["id"]),
            kind=cast(str, row["kind"]),
            normalized_value=cast(str, row["normalized_value"]),
        )
        for row in rows
    )


def view_from_rows(
    party_row: RowMapping,
    contact_rows: list[RowMapping],
    document_rows: list[RowMapping],
) -> RegisteredParty:
    return RegisteredParty(
        party_id=cast(UUID, party_row["party_id"]),
        organization_id=cast(UUID, party_row["organization_id"]),
        party_kind=cast(str, party_row["party_kind"]),
        display_name=cast(str, party_row["display_name"]),
        active=cast(bool, party_row["active"]),
        contact_points=contact_point_views_from_rows(contact_rows),
        documents=document_views_from_rows(document_rows),
    )


def party_to_json(view: RegisteredParty) -> dict[str, object]:
    return {
        "party_id": str(view.party_id),
        "organization_id": str(view.organization_id),
        "party_kind": view.party_kind,
        "display_name": view.display_name,
        "active": view.active,
        "contact_points": [
            {
                "party_id": str(item.party_id),
                "contact_point_id": str(item.contact_point_id),
                "channel": item.channel,
                "normalized_value": item.normalized_value,
                "verified": item.verified,
                "registered_via": item.registered_via.value if item.registered_via else None,
            }
            for item in view.contact_points
        ],
        "documents": [
            {
                "party_id": str(item.party_id),
                "document_id": str(item.document_id),
                "kind": item.kind,
                "normalized_value": item.normalized_value,
            }
            for item in view.documents
        ],
    }


def party_from_json(data: dict[str, object]) -> RegisteredParty:
    return RegisteredParty(
        party_id=UUID(cast(str, data["party_id"])),
        organization_id=UUID(cast(str, data["organization_id"])),
        party_kind=cast(str, data["party_kind"]),
        display_name=cast(str, data["display_name"]),
        active=cast(bool, data["active"]),
        contact_points=tuple(
            PartyContactPoint(
                party_id=UUID(cast(str, item["party_id"])),
                contact_point_id=UUID(cast(str, item["contact_point_id"])),
                channel=cast(str, item["channel"]),
                normalized_value=cast(str, item["normalized_value"]),
                verified=cast(bool, item["verified"]),
                registered_via=(
                    RegisteredVia(cast(str, item["registered_via"]))
                    if item["registered_via"] is not None
                    else None
                ),
            )
            for item in cast(list[dict[str, object]], data["contact_points"])
        ),
        documents=tuple(
            PartyIdentityDocument(
                party_id=UUID(cast(str, item["party_id"])),
                document_id=UUID(cast(str, item["document_id"])),
                kind=cast(str, item["kind"]),
                normalized_value=cast(str, item["normalized_value"]),
            )
            for item in cast(list[dict[str, object]], data["documents"])
        ),
    )
