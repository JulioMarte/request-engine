"""Replay codec and row mapping for the staff principal contact commands.

The JSON replay payloads are the idempotency store's serialization of the
command results. The request-verification payload deliberately carries only
the contact id and expiry: a replayed request must never re-expose a stale
one-time code.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContact,
    PrincipalContactVerificationIssued,
)


def contact_from_row(row: RowMapping) -> PrincipalContact:
    return PrincipalContact(
        contact_id=cast(UUID, row["id"]),
        channel=cast(str, row["channel"]),
        normalized_value=cast(str, row["normalized_value"]),
        verified=cast(bool, row["verified"]),
        active=cast(bool, row["active"]),
    )


def contact_to_json(contact: PrincipalContact) -> dict[str, object]:
    return {
        "contact_id": str(contact.contact_id),
        "channel": contact.channel,
        "normalized_value": contact.normalized_value,
        "verified": contact.verified,
        "active": contact.active,
    }


def contact_from_json(data: Mapping[str, object]) -> PrincipalContact:
    return PrincipalContact(
        contact_id=UUID(cast(str, data["contact_id"])),
        channel=cast(str, data["channel"]),
        normalized_value=cast(str, data["normalized_value"]),
        verified=cast(bool, data["verified"]),
        active=cast(bool, data["active"]),
    )


def issued_to_json(issued: PrincipalContactVerificationIssued) -> dict[str, object]:
    """Replay payload carries the contact id and expiry, never the code."""

    return {"contact_id": str(issued.contact_id), "expires_at": issued.expires_at.isoformat()}


def issued_from_json(data: Mapping[str, object]) -> PrincipalContactVerificationIssued:
    return PrincipalContactVerificationIssued(
        contact_id=UUID(cast(str, data["contact_id"])),
        expires_at=datetime.fromisoformat(cast(str, data["expires_at"])),
    )
