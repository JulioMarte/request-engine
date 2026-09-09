from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.commands.configure_offering_version_booking_terms import (  # noqa: E501
    ConfigureOfferingVersionBookingTermsCommand,
    OfferingVersionBookingTermsState,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    LocationHoursExceptionState,
    SetLocationHoursExceptionCommand,
)
from request_engine.modules.catalog.application.commands.set_location_public_contacts import (
    LocationPublicContactInput,
    LocationPublicContactsState,
    SetLocationPublicContactsCommand,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    LocationOperationalInfoState,
    UpdateLocationOperationalInfoCommand,
)
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    LocationOperationalRevisionConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_operational_authority,
)


class PostgresOperationalProfileCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def update_location_operational_info(
        self,
        command: UpdateLocationOperationalInfoCommand,
    ) -> LocationOperationalInfoState:
        _validate_timezone(command.timezone)
        geocoded_at = _aware_utc(command.geocoded_at, "geocoded_at")
        fingerprint = command_fingerprint(
            "catalog.update_location_operational_info",
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
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
                "expected_operational_revision": command.expected_operational_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="catalog.update_location_operational_info",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _location_state_from_json(cast(dict[str, object], replay["location"]))

            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            current = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT operational_revision
                            FROM request_engine.locations
                            WHERE organization_id = :organization_id
                              AND id = :location_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                raise CatalogConfigurationConflict(
                    "Location is missing or belongs to another Organization"
                )
            current_revision = cast(int, current["operational_revision"])
            if current_revision != command.expected_operational_revision:
                raise LocationOperationalRevisionConflict(
                    command.location_id,
                    command.expected_operational_revision,
                    current_revision,
                )

            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.locations
                               SET timezone = :timezone,
                                   active = :active,
                                   address_line1 = :address_line1,
                                   address_line2 = :address_line2,
                                   locality = :locality,
                                   administrative_area = :administrative_area,
                                   postal_code = :postal_code,
                                   country_code = :country_code,
                                   latitude = :latitude,
                                   longitude = :longitude,
                                   geocoding_source = :geocoding_source,
                                   geocoded_at = :geocoded_at,
                                   updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id
                               AND id = :location_id
                            RETURNING id, timezone, active,
                                      address_line1, address_line2, locality,
                                      administrative_area, postal_code, country_code,
                                      latitude, longitude, geocoding_source, geocoded_at,
                                      operational_revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                            "timezone": command.timezone,
                            "active": command.active,
                            "address_line1": _clean_optional(command.address_line1),
                            "address_line2": _clean_optional(command.address_line2),
                            "locality": _clean_optional(command.locality),
                            "administrative_area": _clean_optional(command.administrative_area),
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
            state = _location_state_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="catalog.update_location_operational_info",
                aggregate_kind="Location",
                aggregate_id=command.location_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "previous_operational_revision": current_revision,
                    "new_operational_revision": state.operational_revision,
                    "booking_material_change": (state.operational_revision != current_revision),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"location": _location_state_to_json(state)},
            )
            return state

    async def set_location_public_contacts(
        self,
        command: SetLocationPublicContactsCommand,
    ) -> LocationPublicContactsState:
        contacts = tuple(
            sorted(command.contacts, key=lambda item: (item.channel, item.normalized_value))
        )
        fingerprint = command_fingerprint(
            "catalog.set_location_public_contacts",
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "contacts": [_contact_to_json(item) for item in contacts],
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="catalog.set_location_public_contacts",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _contacts_state_from_json(cast(dict[str, object], replay["contacts"]))

            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            exists = (
                await session.execute(
                    text(
                        """
                        SELECT id
                        FROM request_engine.locations
                        WHERE organization_id = :organization_id
                          AND id = :location_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "location_id": command.location_id,
                    },
                )
            ).first()
            if exists is None:
                raise CatalogConfigurationConflict(
                    "Location is missing or belongs to another Organization"
                )

            await session.execute(
                text(
                    """
                    UPDATE request_engine.location_public_contact_endpoints
                       SET active = false,
                           is_public = false,
                           updated_at = clock_timestamp()
                     WHERE organization_id = :organization_id
                       AND location_id = :location_id
                       AND (active OR is_public)
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "location_id": command.location_id,
                },
            )
            for contact in contacts:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.location_public_contact_endpoints (
                            organization_id,
                            location_id,
                            channel,
                            normalized_value,
                            label,
                            active,
                            is_public
                        ) VALUES (
                            :organization_id,
                            :location_id,
                            :channel,
                            :normalized_value,
                            :label,
                            true,
                            true
                        )
                        ON CONFLICT (
                            organization_id, location_id, channel, normalized_value
                        ) DO UPDATE
                           SET label = EXCLUDED.label,
                               active = true,
                               is_public = true,
                               updated_at = clock_timestamp()
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "location_id": command.location_id,
                        "channel": contact.channel,
                        "normalized_value": contact.normalized_value,
                        "label": contact.label,
                    },
                )
            state = LocationPublicContactsState(
                location_id=command.location_id,
                contacts=contacts,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="catalog.set_location_public_contacts",
                aggregate_kind="Location",
                aggregate_id=command.location_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "public_contact_count": len(contacts),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"contacts": _contacts_state_to_json(state)},
            )
            return state

    async def set_location_hours_exception(
        self,
        command: SetLocationHoursExceptionCommand,
    ) -> LocationHoursExceptionState:
        start_at = command.start_at.astimezone(UTC)
        end_at = command.end_at.astimezone(UTC)
        fingerprint = command_fingerprint(
            "catalog.set_location_hours_exception",
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "exception_id": command.exception_id,
                "start_at": start_at,
                "end_at": end_at,
                "exception_kind": command.exception_kind,
                "reason": command.reason,
                "active": command.active,
                "expected_operational_revision": command.expected_operational_revision,
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
                    capability="catalog.set_location_hours_exception",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _hours_exception_from_json(cast(dict[str, object], replay["exception"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
                )
                current_revision = await _lock_location_revision(
                    session,
                    command.organization_id,
                    command.location_id,
                )
                if current_revision != command.expected_operational_revision:
                    raise LocationOperationalRevisionConflict(
                        command.location_id,
                        command.expected_operational_revision,
                        current_revision,
                    )

                if command.exception_id is None:
                    exception_id = cast(
                        UUID,
                        (
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO request_engine.location_hours_exceptions (
                                        organization_id,
                                        location_id,
                                        during,
                                        exception_kind,
                                        reason,
                                        active
                                    ) VALUES (
                                        :organization_id,
                                        :location_id,
                                        tstzrange(:start_at, :end_at, '[)'),
                                        :exception_kind,
                                        :reason,
                                        :active
                                    )
                                    RETURNING id
                                    """
                                ),
                                {
                                    "organization_id": command.organization_id,
                                    "location_id": command.location_id,
                                    "start_at": start_at,
                                    "end_at": end_at,
                                    "exception_kind": command.exception_kind,
                                    "reason": command.reason,
                                    "active": command.active,
                                },
                            )
                        ).scalar_one(),
                    )
                else:
                    row = (
                        await session.execute(
                            text(
                                """
                                UPDATE request_engine.location_hours_exceptions
                                   SET during = tstzrange(:start_at, :end_at, '[)'),
                                       exception_kind = :exception_kind,
                                       reason = :reason,
                                       active = :active,
                                       updated_at = clock_timestamp()
                                 WHERE organization_id = :organization_id
                                   AND location_id = :location_id
                                   AND id = :exception_id
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "location_id": command.location_id,
                                "exception_id": command.exception_id,
                                "start_at": start_at,
                                "end_at": end_at,
                                "exception_kind": command.exception_kind,
                                "reason": command.reason,
                                "active": command.active,
                            },
                        )
                    ).first()
                    if row is None:
                        raise CatalogConfigurationConflict(
                            "Location hours exception is missing or belongs to another Location"
                        )
                    exception_id = command.exception_id

                final_revision = await _location_revision(
                    session,
                    command.organization_id,
                    command.location_id,
                )
                state = LocationHoursExceptionState(
                    exception_id=exception_id,
                    location_id=command.location_id,
                    start_at=start_at,
                    end_at=end_at,
                    exception_kind=command.exception_kind,
                    reason=command.reason,
                    active=command.active,
                    operational_revision=final_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="catalog.set_location_hours_exception",
                    aggregate_kind="LocationHoursException",
                    aggregate_id=exception_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "location_id": str(command.location_id),
                        "exception_kind": command.exception_kind,
                        "active": command.active,
                        "previous_operational_revision": current_revision,
                        "new_operational_revision": final_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"exception": _hours_exception_to_json(state)},
                )
                return state
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise CatalogConfigurationConflict(
                    "Location hours exception overlaps active effective configuration"
                ) from None
            raise

    async def configure_offering_version_booking_terms(
        self,
        command: ConfigureOfferingVersionBookingTermsCommand,
    ) -> OfferingVersionBookingTermsState:
        fingerprint = command_fingerprint(
            "catalog.configure_offering_version_booking_terms",
            {
                "authority_party_id": command.authority_party_id,
                "offering_version_id": command.offering_version_id,
                "amount": str(command.amount),
                "currency": command.currency,
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
                    capability="catalog.configure_offering_version_booking_terms",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _base_terms_from_json(cast(dict[str, object], replay["terms"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                offering = (
                    await session.execute(
                        text(
                            """
                            SELECT ov.id
                            FROM request_engine.offering_versions ov
                            JOIN request_engine.offerings o
                              ON o.organization_id = ov.organization_id
                             AND o.id = ov.offering_id
                            WHERE ov.organization_id = :organization_id
                              AND ov.id = :offering_version_id
                              AND o.active
                            FOR UPDATE OF o
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": command.offering_version_id,
                        },
                    )
                ).first()
                if offering is None:
                    raise CatalogConfigurationConflict(
                        "OfferingVersion is missing or belongs to another Organization"
                    )
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.offering_version_booking_terms (
                                    organization_id,
                                    offering_version_id,
                                    amount,
                                    currency
                                ) VALUES (
                                    :organization_id,
                                    :offering_version_id,
                                    :amount,
                                    :currency
                                )
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_version_id": command.offering_version_id,
                                "amount": command.amount,
                                "currency": command.currency,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = OfferingVersionBookingTermsState(
                    terms_id=cast(UUID, row["id"]),
                    offering_version_id=command.offering_version_id,
                    amount=command.amount,
                    currency=command.currency,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="catalog.configure_offering_version_booking_terms",
                    aggregate_kind="OfferingVersionBookingTerms",
                    aggregate_id=state.terms_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "offering_version_id": str(command.offering_version_id),
                        "amount": str(command.amount),
                        "currency": command.currency,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"terms": _base_terms_to_json(state)},
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict(
                    "OfferingVersion booking terms are already configured; create a new "
                    "OfferingVersion to change immutable defaults"
                ) from None
            raise


async def _lock_location_revision(
    session: AsyncSession,
    organization_id: UUID,
    location_id: UUID,
) -> int:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT operational_revision
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id AND id = :location_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "location_id": location_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise CatalogConfigurationConflict("Location is missing or belongs to another Organization")
    return cast(int, row["operational_revision"])


async def _location_revision(
    session: AsyncSession,
    organization_id: UUID,
    location_id: UUID,
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT operational_revision
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id AND id = :location_id
                    """
                ),
                {"organization_id": organization_id, "location_id": location_id},
            )
        ).scalar_one(),
    )


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


def _location_state_from_row(row: RowMapping) -> LocationOperationalInfoState:
    return LocationOperationalInfoState(
        location_id=cast(UUID, row["id"]),
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


def _location_state_to_json(state: LocationOperationalInfoState) -> dict[str, object]:
    return {
        "location_id": str(state.location_id),
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


def _location_state_from_json(value: dict[str, object]) -> LocationOperationalInfoState:
    latitude = cast(str | None, value.get("latitude"))
    longitude = cast(str | None, value.get("longitude"))
    geocoded_at = cast(str | None, value.get("geocoded_at"))
    return LocationOperationalInfoState(
        location_id=UUID(cast(str, value["location_id"])),
        timezone=cast(str, value["timezone"]),
        active=cast(bool, value["active"]),
        address_line1=cast(str | None, value.get("address_line1")),
        address_line2=cast(str | None, value.get("address_line2")),
        locality=cast(str | None, value.get("locality")),
        administrative_area=cast(str | None, value.get("administrative_area")),
        postal_code=cast(str | None, value.get("postal_code")),
        country_code=cast(str | None, value.get("country_code")),
        latitude=Decimal(latitude) if latitude else None,
        longitude=Decimal(longitude) if longitude else None,
        geocoding_source=cast(str | None, value.get("geocoding_source")),
        geocoded_at=datetime.fromisoformat(geocoded_at) if geocoded_at else None,
        operational_revision=cast(int, value["operational_revision"]),
    )


def _contact_to_json(contact: LocationPublicContactInput) -> dict[str, object]:
    return {
        "channel": contact.channel,
        "normalized_value": contact.normalized_value,
        "label": contact.label,
    }


def _contacts_state_to_json(state: LocationPublicContactsState) -> dict[str, object]:
    return {
        "location_id": str(state.location_id),
        "contacts": [_contact_to_json(item) for item in state.contacts],
    }


def _contacts_state_from_json(value: dict[str, object]) -> LocationPublicContactsState:
    raw = cast(list[dict[str, object]], value["contacts"])
    contacts: list[LocationPublicContactInput] = []
    for item in raw:
        channel = cast(str, item["channel"])
        if channel not in ("phone", "whatsapp", "email"):
            raise ValueError("stored public contact channel is invalid")
        contacts.append(
            LocationPublicContactInput(
                channel=channel,
                normalized_value=cast(str, item["normalized_value"]),
                label=cast(str | None, item.get("label")),
            )
        )
    return LocationPublicContactsState(
        location_id=UUID(cast(str, value["location_id"])),
        contacts=tuple(contacts),
    )


def _hours_exception_to_json(state: LocationHoursExceptionState) -> dict[str, object]:
    return {
        "exception_id": str(state.exception_id),
        "location_id": str(state.location_id),
        "start_at": state.start_at.isoformat(),
        "end_at": state.end_at.isoformat(),
        "exception_kind": state.exception_kind,
        "reason": state.reason,
        "active": state.active,
        "operational_revision": state.operational_revision,
    }


def _hours_exception_from_json(value: dict[str, object]) -> LocationHoursExceptionState:
    kind = cast(str, value["exception_kind"])
    if kind not in ("available", "unavailable"):
        raise ValueError("stored Location hours exception kind is invalid")
    return LocationHoursExceptionState(
        exception_id=UUID(cast(str, value["exception_id"])),
        location_id=UUID(cast(str, value["location_id"])),
        start_at=datetime.fromisoformat(cast(str, value["start_at"])),
        end_at=datetime.fromisoformat(cast(str, value["end_at"])),
        exception_kind=kind,
        reason=cast(str | None, value.get("reason")),
        active=cast(bool, value["active"]),
        operational_revision=cast(int, value["operational_revision"]),
    )


def _base_terms_to_json(state: OfferingVersionBookingTermsState) -> dict[str, object]:
    return {
        "terms_id": str(state.terms_id),
        "offering_version_id": str(state.offering_version_id),
        "amount": str(state.amount),
        "currency": state.currency,
    }


def _base_terms_from_json(value: dict[str, object]) -> OfferingVersionBookingTermsState:
    return OfferingVersionBookingTermsState(
        terms_id=UUID(cast(str, value["terms_id"])),
        offering_version_id=UUID(cast(str, value["offering_version_id"])),
        amount=Decimal(cast(str, value["amount"])),
        currency=cast(str, value["currency"]),
    )
