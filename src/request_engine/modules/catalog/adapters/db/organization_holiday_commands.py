from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.commands.declare_organization_holidays import (
    DeclaredOrganizationHolidaysState,
    DeclareOrganizationHolidaysCommand,
    OrganizationHolidayInput,
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

_CAPABILITY = "catalog.declare_organization_holidays"


class PostgresOrganizationHolidayCommands:
    """Declare organization-wide closure days as Location hours exceptions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def declare_organization_holidays(
        self, command: DeclareOrganizationHolidaysCommand
    ) -> DeclaredOrganizationHolidaysState:
        holidays = tuple(sorted(command.holidays, key=lambda item: (item.date, item.reason or "")))
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "holidays": [
                    {"date": item.date.isoformat(), "reason": item.reason} for item in holidays
                ],
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
                    capability=_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(cast(dict[str, object], replay["state"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
                )
                locations = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT id, timezone
                                FROM request_engine.locations
                                WHERE organization_id = :organization_id
                                  AND active
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
                if not locations:
                    raise CatalogConfigurationConflict(
                        "Organization has no active Location to close"
                    )

                created = 0
                already_declared = 0
                for location in locations:
                    location_id = cast(UUID, location["id"])
                    timezone = ZoneInfo(cast(str, location["timezone"]))
                    for holiday in holidays:
                        outcome = await _declare_location_holiday(
                            session,
                            organization_id=command.organization_id,
                            location_id=location_id,
                            holiday_date=holiday.date,
                            reason=holiday.reason,
                            timezone=timezone,
                        )
                        if outcome:
                            created += 1
                        else:
                            already_declared += 1

                state = DeclaredOrganizationHolidaysState(
                    holidays=holidays,
                    locations_covered=len(locations),
                    exceptions_created=created,
                    exceptions_already_declared=already_declared,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="OrganizationHoliday",
                    aggregate_id=command.organization_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "holidays": [item.date.isoformat() for item in holidays],
                        "locations_covered": len(locations),
                        "exceptions_created": created,
                        "exceptions_already_declared": already_declared,
                    },
                )
                await complete_idempotency(
                    session, idempotency_id, {"state": _state_to_json(state)}
                )
                return state
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise CatalogConfigurationConflict(
                    "an active Location hours exception overlaps a declared holiday"
                ) from None
            raise


async def _declare_location_holiday(
    session: AsyncSession,
    *,
    organization_id: UUID,
    location_id: UUID,
    holiday_date: date,
    reason: str | None,
    timezone: ZoneInfo,
) -> bool:
    """Materialize one full-day closure; return False when already declared."""

    day_start = datetime.combine(holiday_date, time(0, 0), tzinfo=timezone).astimezone(UTC)
    day_end = (day_start + timedelta(days=1)).astimezone(UTC)

    overlapping = (
        (
            await session.execute(
                text(
                    """
                    SELECT during
                    FROM request_engine.location_hours_exceptions
                    WHERE organization_id = :organization_id
                      AND location_id = :location_id
                      AND active
                      AND during && tstzrange(:day_start, :day_end, '[)')
                    """
                ),
                {
                    "organization_id": organization_id,
                    "location_id": location_id,
                    "day_start": day_start,
                    "day_end": day_end,
                },
            )
        )
        .scalars()
        .all()
    )
    for during in overlapping:
        if _is_same_range(cast(object, during), day_start, day_end):
            return False
    if overlapping:
        raise CatalogConfigurationConflict(
            "Location has an active hours exception overlapping the "
            f"holiday {holiday_date.isoformat()}; resolve it before declaring the closure"
        )

    await session.execute(
        text(
            """
            INSERT INTO request_engine.location_hours_exceptions (
                organization_id, location_id, during, exception_kind, reason, active
            ) VALUES (
                :organization_id, :location_id,
                tstzrange(:day_start, :day_end, '[)'),
                'unavailable', :reason, true
            )
            """
        ),
        {
            "organization_id": organization_id,
            "location_id": location_id,
            "day_start": day_start,
            "day_end": day_end,
            "reason": reason,
        },
    )
    return True


def _is_same_range(during: object, day_start: datetime, day_end: datetime) -> bool:
    lower = getattr(during, "lower", None)
    upper = getattr(during, "upper", None)
    return lower == day_start and upper == day_end


def _state_to_json(state: DeclaredOrganizationHolidaysState) -> dict[str, object]:
    return {
        "holidays": [
            {"date": item.date.isoformat(), "reason": item.reason} for item in state.holidays
        ],
        "locations_covered": state.locations_covered,
        "exceptions_created": state.exceptions_created,
        "exceptions_already_declared": state.exceptions_already_declared,
    }


def _state_from_json(value: dict[str, object]) -> DeclaredOrganizationHolidaysState:
    raw_holidays = cast(list[dict[str, object]], value["holidays"])
    return DeclaredOrganizationHolidaysState(
        holidays=tuple(
            OrganizationHolidayInput(
                date=date.fromisoformat(cast(str, item["date"])),
                reason=cast(str | None, item.get("reason")),
            )
            for item in raw_holidays
        ),
        locations_covered=cast(int, value["locations_covered"]),
        exceptions_created=cast(int, value["exceptions_created"]),
        exceptions_already_declared=cast(int, value["exceptions_already_declared"]),
    )
