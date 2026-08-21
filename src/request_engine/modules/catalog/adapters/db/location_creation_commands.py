from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from request_engine.modules.catalog.application.commands.create_location import (
    CreateLocationCommand,
    CreatedLocationState,
)
from request_engine.modules.catalog.application.errors import CatalogConfigurationConflict
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_operational_authority,
)


class PostgresLocationCreationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_location(self, command: CreateLocationCommand) -> CreatedLocationState:
        _validate_timezone(command.timezone)
        geocoded_at = _aware_utc(command.geocoded_at, "geocoded_at")
        fingerprint = command_fingerprint(
            "catalog.create_location",
            {
                "authority_party_id": command.authority_party_id,
                "location_key": command.location_key,
                "display_name": command.display_name,
                "timezone": command.timezone,
                "active": command.active,
                "address_line1": command.address_line1,
                "address_line2": command.address_line2,
                "locality": command.locality,
                "administrative_area": command.administrative_area,
                "postal_code": command.postal_code,
                "country_code": command.country_code,
                "latitude": str(command.latitude) if command.latitude is not None else None,
                "longitude": str(command.longitude) if command.longitude is not None else None,
                "geocoding_source": command.geocoding_source,
                "geocoded_at": geocoded_at,
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="catalog.create_location",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(cast(dict[str, object], replay["location"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
                )
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.locations (
                                    organization_id,
                                    location_key,
                                    display_name,
                                    timezone,
                                    active,
                                    address_line1,
                                    address_line2,
                                    locality,
                                    administrative_area,
                                    postal_code,
                                    country_code,
                                    latitude,
                                    longitude,
                                    geocoding_source,
                                    geocoded_at
                                ) VALUES (
                                    :organization_id,
                                    :location_key,
                                    :display_name,
                                    :timezone,
                                    :active,
                                    :address_line1,
                                    :address_line2,
                                    :locality,
                                    :administrative_area,
                                    :postal_code,
                                    :country_code,
                                    :latitude,
                                    :longitude,
                                    :geocoding_source,
                                    :geocoded_at
                                )
                                RETURNING
                                    id,
                                    location_key,
                                    display_name,
                                    timezone,
                                    active,
                                    address_line1,
                                    address_line2,
                                    locality,
                                    administrative_area,
                                    postal_code,
                                    country_code,
                                    latitude,
                                    longitude,
                                    geocoding_source,
                                    geocoded_at,
                                    operational_revision
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "location_key": command.location_key.strip(),
                                "display_name": command.display_name.strip(),
                                "timezone": command.timezone,
                                "active": command.active,
                                "address_line1": _clean_optional(command.address_line1),
                                "address_line2": _clean_optional(command.address_line2),
                                "locality": _clean_optional(command.locality),
                                "administrative_area": _clean_optional(
                                    command.administrative_area
                                ),
                                "postal_code": _clean_optional(command.postal_code),
                                "country_code": command.country_code,
                                "latitude": command.latitude,
                                "longitude": command.longitude,
                                "geocoding_source": _clean_optional(command.geocoding_source),
                                "geocoded_at": geocoded_at,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = _state_from_row(row)
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="catalog.create_location",
                    aggregate_kind="Location",
                    aggregate_id=state.location_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "location_key": state.location_key,
                        "operational_revision": state.operational_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"location": _state_to_json(state)},
                )
                return state
        except IntegrityError as exc:
            raise CatalogConfigurationConflict(
                "Location conflicts with existing tenant configuration"
            ) from exc


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc


def _aware_utc(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _state_from_row(row: RowMapping) -> CreatedLocationState:
    return CreatedLocationState(
        location_id=cast(UUID, row["id"]),
        location_key=cast(str, row["location_key"]),
        display_name=cast(str, row["display_name"]),
        timezone=cast(str, row["timezone"]),
        active=cast(bool, row["active"]),
        address_line1=cast(str | None, row["address_line1"]),
        address_line2=cast(str | None, row["address_line2"]),
        locality=cast(str | None, row["locality"]),
        administrative_area=cast(str | None, row["administrative_area"]),
        postal_code=cast(str | None, row["postal_code"]),
        country_code=cast(str | None, row["country_code"]),
        latitude=cast(Decimal | None, row["latitude"]),
        longitude=cast(Decimal | None, row["longitude"]),
        geocoding_source=cast(str | None, row["geocoding_source"]),
        geocoded_at=cast(datetime | None, row["geocoded_at"]),
        operational_revision=cast(int, row["operational_revision"]),
    )


def _state_to_json(state: CreatedLocationState) -> dict[str, object]:
    return {
        "location_id": str(state.location_id),
        "location_key": state.location_key,
        "display_name": state.display_name,
        "timezone": state.timezone,
        "active": state.active,
        "address_line1": state.address_line1,
        "address_line2": state.address_line2,
        "locality": state.locality,
        "administrative_area": state.administrative_area,
        "postal_code": state.postal_code,
        "country_code": state.country_code,
        "latitude": str(state.latitude) if state.latitude is not None else None,
        "longitude": str(state.longitude) if state.longitude is not None else None,
        "geocoding_source": state.geocoding_source,
        "geocoded_at": state.geocoded_at.isoformat() if state.geocoded_at else None,
        "operational_revision": state.operational_revision,
    }


def _state_from_json(value: dict[str, object]) -> CreatedLocationState:
    latitude = value.get("latitude")
    longitude = value.get("longitude")
    geocoded_at = value.get("geocoded_at")
    return CreatedLocationState(
        location_id=UUID(cast(str, value["location_id"])),
        location_key=cast(str, value["location_key"]),
        display_name=cast(str, value["display_name"]),
        timezone=cast(str, value["timezone"]),
        active=cast(bool, value["active"]),
        address_line1=cast(str | None, value.get("address_line1")),
        address_line2=cast(str | None, value.get("address_line2")),
        locality=cast(str | None, value.get("locality")),
        administrative_area=cast(str | None, value.get("administrative_area")),
        postal_code=cast(str | None, value.get("postal_code")),
        country_code=cast(str | None, value.get("country_code")),
        latitude=Decimal(cast(str, latitude)) if latitude is not None else None,
        longitude=Decimal(cast(str, longitude)) if longitude is not None else None,
        geocoding_source=cast(str | None, value.get("geocoding_source")),
        geocoded_at=(
            datetime.fromisoformat(cast(str, geocoded_at)) if geocoded_at is not None else None
        ),
        operational_revision=cast(int, value["operational_revision"]),
    )
