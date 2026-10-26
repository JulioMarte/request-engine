"""Deactivate saved Location hours exceptions and organization holidays.

READ     idempotency receipt after exact ``operations.manage_profile`` authority;
LOCK     Location rows ``FOR UPDATE`` (one Location, or every Location of the
         tenant in id order — the order used by holiday declaration);
VALIDATE operational revision (single exception) and the exception's ownership;
WRITE    ``active = false`` (never DELETE); the row trigger advances the
         Location ``operational_revision``;
EMIT     audit plus a PII-free ``catalog.*`` outbox fact (ids/counts only).
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.commands.remove_location_closures import (
    DeactivateLocationHoursExceptionCommand,
    RemovedOrganizationHolidaysState,
    RemoveOrganizationHolidaysCommand,
    validate_holiday_removal,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    LocationHoursExceptionState,
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
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.security.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_operational_authority,
)

_DEACTIVATE = "catalog.deactivate_location_hours_exception"
_REMOVE_HOLIDAYS = "catalog.remove_organization_holidays"


class PostgresLocationClosureCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def deactivate_location_hours_exception(
        self, command: DeactivateLocationHoursExceptionCommand
    ) -> LocationHoursExceptionState:
        fingerprint = command_fingerprint(
            _DEACTIVATE,
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "exception_id": command.exception_id,
                "expected_operational_revision": command.expected_operational_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_DEACTIVATE,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _exception_from_json(cast(dict[str, object], replay["exception"]))
            current_revision = await _lock_location(
                session, command.organization_id, command.location_id
            )
            if current_revision != command.expected_operational_revision:
                raise LocationOperationalRevisionConflict(
                    command.location_id, command.expected_operational_revision, current_revision
                )
            existing = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT active
                            FROM request_engine.location_hours_exceptions
                            WHERE organization_id = :organization_id
                              AND location_id = :location_id
                              AND id = :exception_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                            "exception_id": command.exception_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                raise CatalogConfigurationConflict(
                    "Location hours exception is missing or belongs to another Location"
                )
            if existing["active"] is not True:
                raise CatalogConfigurationConflict("Location hours exception is already inactive")
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.location_hours_exceptions
                               SET active = false, updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id
                               AND location_id = :location_id
                               AND id = :exception_id
                            RETURNING id, lower(during) AS start_at, upper(during) AS end_at,
                                      exception_kind, reason
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                            "exception_id": command.exception_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            final_revision = await _location_revision(
                session, command.organization_id, command.location_id
            )
            kind = cast(str, row["exception_kind"])
            state = LocationHoursExceptionState(
                exception_id=command.exception_id,
                location_id=command.location_id,
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                exception_kind="available" if kind == "available" else "unavailable",
                reason=cast(str | None, row["reason"]),
                active=False,
                operational_revision=final_revision,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_DEACTIVATE,
                aggregate_kind="LocationHoursException",
                aggregate_id=command.exception_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "location_id": str(command.location_id),
                    "exception_kind": kind,
                    "previous_operational_revision": current_revision,
                    "new_operational_revision": final_revision,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="catalog.location_hours_exception_deactivated.v1",
                aggregate_kind="Location",
                aggregate_id=command.location_id,
                payload={
                    "location_id": str(command.location_id),
                    "exception_id": str(command.exception_id),
                    "operational_revision": final_revision,
                },
            )
            await complete_idempotency(
                session, idempotency_id, {"exception": _exception_to_json(state)}
            )
            return state

    async def remove_organization_holidays(
        self, command: RemoveOrganizationHolidaysCommand
    ) -> RemovedOrganizationHolidaysState:
        validate_holiday_removal(command)
        dates = tuple(sorted(command.dates))
        fingerprint = command_fingerprint(
            _REMOVE_HOLIDAYS,
            {
                "authority_party_id": command.authority_party_id,
                "dates": [item.isoformat() for item in dates],
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_REMOVE_HOLIDAYS,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _holidays_from_json(cast(dict[str, object], replay["state"]))
            locations = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, timezone
                            FROM request_engine.locations
                            WHERE organization_id = :organization_id
                            ORDER BY id
                            FOR UPDATE
                            """
                        ),
                        {"organization_id": command.organization_id},
                    )
                )
                .mappings()
                .all()
            )
            deactivated = 0
            found: set[date] = set()
            for location in locations:
                timezone = ZoneInfo(cast(str, location["timezone"]))
                for holiday in dates:
                    count = await _deactivate_full_day(
                        session,
                        organization_id=command.organization_id,
                        location_id=cast(UUID, location["id"]),
                        holiday=holiday,
                        timezone=timezone,
                    )
                    if count:
                        found.add(holiday)
                        deactivated += count
            state = RemovedOrganizationHolidaysState(
                dates=dates,
                locations_examined=len(locations),
                exceptions_deactivated=deactivated,
                dates_not_found=tuple(item for item in dates if item not in found),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_REMOVE_HOLIDAYS,
                aggregate_kind="OrganizationHoliday",
                aggregate_id=command.organization_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "dates": [item.isoformat() for item in dates],
                    "locations_examined": state.locations_examined,
                    "exceptions_deactivated": deactivated,
                    "dates_not_found": [item.isoformat() for item in state.dates_not_found],
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="catalog.organization_holidays_removed.v1",
                aggregate_kind="Organization",
                aggregate_id=command.organization_id,
                payload={
                    "dates": [item.isoformat() for item in dates],
                    "exceptions_deactivated": deactivated,
                },
            )
            await complete_idempotency(session, idempotency_id, {"state": _holidays_to_json(state)})
            return state


async def _lock_location(session: AsyncSession, organization_id: UUID, location_id: UUID) -> int:
    row = (
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
    ).first()
    if row is None:
        raise CatalogConfigurationConflict("Location is missing or belongs to another Organization")
    return cast(int, row[0])


async def _location_revision(
    session: AsyncSession, organization_id: UUID, location_id: UUID
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


async def _deactivate_full_day(
    session: AsyncSession,
    *,
    organization_id: UUID,
    location_id: UUID,
    holiday: date,
    timezone: ZoneInfo,
) -> int:
    """Deactivate the active full local-day closure; same range as declaration."""

    day_start = datetime.combine(holiday, time(0, 0), tzinfo=timezone).astimezone(UTC)
    day_end = (day_start + timedelta(days=1)).astimezone(UTC)
    result = await session.execute(
        text(
            """
            UPDATE request_engine.location_hours_exceptions
               SET active = false, updated_at = clock_timestamp()
             WHERE organization_id = :organization_id
               AND location_id = :location_id
               AND active
               AND exception_kind = 'unavailable'
               AND during = tstzrange(:day_start, :day_end, '[)')
            RETURNING id
            """
        ),
        {
            "organization_id": organization_id,
            "location_id": location_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    return len(result.all())


def _exception_to_json(state: LocationHoursExceptionState) -> dict[str, object]:
    return {
        "exception_id": str(state.exception_id),
        "location_id": str(state.location_id),
        "start_at": state.start_at.isoformat(),
        "end_at": state.end_at.isoformat(),
        "exception_kind": state.exception_kind,
        "reason": state.reason,
        "operational_revision": state.operational_revision,
    }


def _exception_from_json(value: dict[str, object]) -> LocationHoursExceptionState:
    kind = cast(str, value["exception_kind"])
    return LocationHoursExceptionState(
        exception_id=UUID(cast(str, value["exception_id"])),
        location_id=UUID(cast(str, value["location_id"])),
        start_at=datetime.fromisoformat(cast(str, value["start_at"])),
        end_at=datetime.fromisoformat(cast(str, value["end_at"])),
        exception_kind="available" if kind == "available" else "unavailable",
        reason=cast(str | None, value.get("reason")),
        active=False,
        operational_revision=cast(int, value["operational_revision"]),
    )


def _holidays_to_json(state: RemovedOrganizationHolidaysState) -> dict[str, object]:
    return {
        "dates": [item.isoformat() for item in state.dates],
        "locations_examined": state.locations_examined,
        "exceptions_deactivated": state.exceptions_deactivated,
        "dates_not_found": [item.isoformat() for item in state.dates_not_found],
    }


def _holidays_from_json(value: dict[str, object]) -> RemovedOrganizationHolidaysState:
    return RemovedOrganizationHolidaysState(
        dates=tuple(date.fromisoformat(item) for item in cast(list[str], value["dates"])),
        locations_examined=cast(int, value["locations_examined"]),
        exceptions_deactivated=cast(int, value["exceptions_deactivated"]),
        dates_not_found=tuple(
            date.fromisoformat(item) for item in cast(list[str], value["dates_not_found"])
        ),
    )
