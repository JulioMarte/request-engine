import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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
    ) -> str | None:
        selection = _selection(slot)
        secret = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        expires_at = datetime.now(UTC) + _TTL
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    text(
                        """
                        SELECT request_engine.issue_discovery_booking_handoff(
                            :token_hash,
                            :publication_id,
                            :publication_revision,
                            :mapping_id,
                            :mapping_revision,
                            :offering_version_id,
                            :location_id,
                            CAST(:selection AS jsonb),
                            :expires_at
                        )
                        """
                    ),
                    {
                        "token_hash": token_hash,
                        "publication_id": candidate.publication_id,
                        "publication_revision": candidate.publication_revision,
                        "mapping_id": candidate.mapping_id,
                        "mapping_revision": candidate.mapping_revision,
                        "offering_version_id": slot.offering_version_id,
                        "location_id": cast(UUID, slot.location_id),
                        "selection": json.dumps(selection, separators=(",", ":")),
                        "expires_at": expires_at,
                    },
                )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "40001":
                return None
            raise
        return f"{_PREFIX}.{secret}"


def _selection(slot: AppointmentSlot) -> dict[str, object]:
    if slot.location_id is None or slot.configuration_fingerprint is None:
        raise ValueError("F2 discovery requires contextual appointment supply")
    if slot.amount is None or slot.currency is None or slot.planned_duration_minutes is None:
        raise ValueError("F2 discovery requires deterministic commercial terms")
    if slot.location_operational_revision is None:
        raise ValueError("F2 discovery requires Location revision")
    for choice in slot.resources:
        if choice.resource_location_assignment_id is None:
            raise ValueError("F2 discovery requires ResourceLocationAssignment provenance")
        if choice.assignment_revision is None or choice.assignment_revision <= 0:
            raise ValueError("F2 discovery requires positive assignment revision")
        if choice.availability_revision is None or choice.availability_revision <= 0:
            raise ValueError("F2 discovery requires Resource availability revision")
    amount = slot.amount
    return {
        "offering_version_id": str(slot.offering_version_id),
        "start_at": slot.start_at.isoformat(),
        "end_at": slot.end_at.isoformat(),
        "location_id": str(slot.location_id),
        "resources": [
            {
                "requirement_id": str(choice.requirement_id),
                "resource_id": str(choice.resource_id),
                "resource_location_assignment_id": str(
                    cast(UUID, choice.resource_location_assignment_id)
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
