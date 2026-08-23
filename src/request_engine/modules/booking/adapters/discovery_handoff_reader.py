import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.application.errors import (
    AppointmentOptionInvalid,
    AppointmentOptionStale,
)
from request_engine.modules.booking.contracts.appointment_options import DecodedAppointmentOption
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.discovery import DecodedDiscoveryHandoff
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_PREFIX = "discoopt_v1"


class PostgresDiscoveryHandoffReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_handoff(
        self,
        organization_id: UUID,
        token: str,
    ) -> DecodedDiscoveryHandoff:
        secret = _secret(token)
        token_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.read_discovery_booking_handoff(:token_hash)
                            """
                        ),
                        {"token_hash": token_hash},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["organization_id"] != organization_id:
            raise AppointmentOptionStale("discovery publication or handoff changed")
        selection = row["selection"]
        if not isinstance(selection, dict):
            raise AppointmentOptionInvalid("discovery handoff payload is malformed")
        try:
            option = _decode_selection(selection, organization_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppointmentOptionInvalid("discovery handoff payload is malformed") from exc
        return DecodedDiscoveryHandoff(
            handoff_id=row["handoff_id"],
            organization_id=organization_id,
            option=option,
        )


def _secret(token: str) -> str:
    prefix, separator, secret = token.partition(".")
    if separator != "." or prefix != _PREFIX or len(secret) < 32:
        raise AppointmentOptionInvalid("unsupported discovery option format")
    return secret


def _decode_selection(
    data: dict[str, object],
    organization_id: UUID,
) -> DecodedAppointmentOption:
    resources_raw = data.get("resources")
    if not isinstance(resources_raw, list) or not resources_raw:
        raise ValueError("resources are malformed")
    return DecodedAppointmentOption(
        organization_id=organization_id,
        offering_version_id=UUID(str(data["offering_version_id"])),
        start_at=datetime.fromisoformat(str(data["start_at"])),
        end_at=datetime.fromisoformat(str(data["end_at"])),
        location_id=UUID(str(data["location_id"])),
        resources=tuple(_resource(item) for item in resources_raw),
        expires_at=datetime.max.replace(tzinfo=UTC),
        planned_duration_minutes=int(str(data["planned_duration_minutes"])),
        amount=Decimal(str(data["amount"])),
        currency=str(data["currency"]),
        location_operational_revision=int(str(data["location_operational_revision"])),
        configuration_fingerprint=str(data["configuration_fingerprint"]),
    )


def _resource(raw: object) -> ResourceChoice:
    if not isinstance(raw, dict):
        raise ValueError("resource is malformed")
    assignment_raw = raw.get("resource_location_assignment_id")
    assignment_revision = raw.get("assignment_revision")
    availability_revision = raw.get("availability_revision")
    return ResourceChoice(
        requirement_id=UUID(str(raw["requirement_id"])),
        resource_id=UUID(str(raw["resource_id"])),
        resource_location_assignment_id=(UUID(str(assignment_raw)) if assignment_raw else None),
        assignment_revision=(int(str(assignment_revision)) if assignment_revision else None),
        availability_revision=(int(str(availability_revision)) if availability_revision else None),
    )
