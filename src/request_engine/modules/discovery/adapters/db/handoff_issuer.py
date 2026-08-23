import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.discovery.application.queries.search_supply import DiscoveryCandidate
from request_engine.platform.db.session import SessionFactory

_PREFIX = "discoopt_v1"
_TTL = timedelta(minutes=10)


class PostgresDiscoveryHandoffIssuer:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def issue_handoff(
        self,
        candidate: DiscoveryCandidate,
        slot: AppointmentSlot,
    ) -> str:
        _require_discoverable_slot(slot)
        secret = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        expires_at = datetime.now(UTC) + _TTL
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    SELECT request_engine.issue_discovery_booking_handoff(
                        :token_hash, :publication_id, :publication_revision,
                        :offering_version_id, :location_id,
                        CAST(:selection AS jsonb), :expires_at
                    )
                    """
                ),
                {
                    "token_hash": token_hash,
                    "publication_id": candidate.publication_id,
                    "publication_revision": candidate.publication_revision,
                    "offering_version_id": slot.offering_version_id,
                    "location_id": slot.location_id,
                    "selection": json.dumps(_selection(slot), separators=(",", ":")),
                    "expires_at": expires_at,
                },
            )
        return f"{_PREFIX}.{secret}"


def _require_discoverable_slot(slot: AppointmentSlot) -> None:
    if slot.location_id is None or slot.configuration_fingerprint is None:
        raise ValueError("F2 discovery requires contextual appointment supply")
    if slot.amount is None or slot.currency is None or slot.planned_duration_minutes is None:
        raise ValueError("F2 discovery requires deterministic commercial terms")


def _selection(slot: AppointmentSlot) -> dict[str, object]:
    amount = slot.amount
    assert isinstance(amount, Decimal)
    return {
        "offering_version_id": str(slot.offering_version_id),
        "start_at": slot.start_at.isoformat(),
        "end_at": slot.end_at.isoformat(),
        "location_id": str(slot.location_id),
        "resources": [
            {
                "requirement_id": str(choice.requirement_id),
                "resource_id": str(choice.resource_id),
                "resource_location_assignment_id": (
                    str(choice.resource_location_assignment_id)
                    if choice.resource_location_assignment_id is not None
                    else None
                ),
                "assignment_revision": choice.assignment_revision,
                "availability_revision": choice.availability_revision,
            }
            for choice in slot.resources
        ],
        "planned_duration_minutes": slot.planned_duration_minutes,
        "amount": str(amount),
        "currency": slot.currency,
        "location_operational_revision": slot.location_operational_revision,
        "configuration_fingerprint": slot.configuration_fingerprint,
    }
