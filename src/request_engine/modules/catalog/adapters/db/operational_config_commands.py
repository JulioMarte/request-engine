from datetime import date, time
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.catalog.application.commands.set_location_operational_hours import (
    LocationOperationalHoursInput,
    LocationOperationalHoursState,
    SetLocationOperationalHoursCommand,
)
from request_engine.modules.catalog.application.errors import LocationOperationalRevisionConflict
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


class PostgresOperationalConfigCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_location_operational_hours(
        self,
        command: SetLocationOperationalHoursCommand,
    ) -> LocationOperationalHoursState:
        windows = _validated_windows(command.windows)
        fingerprint = command_fingerprint(
            "catalog.set_location_operational_hours",
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "expected_operational_revision": command.expected_operational_revision,
                "windows": [
                    {
                        "weekday": item.weekday,
                        "local_start": item.local_start.isoformat(),
                        "local_end": item.local_end.isoformat(),
                        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                        "valid_until": item.valid_until.isoformat() if item.valid_until else None,
                    }
                    for item in windows
                ],
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="catalog.set_location_operational_hours",
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
            row = (
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
                .one()
            )
            current_revision = cast(int, row["operational_revision"])
            if current_revision != command.expected_operational_revision:
                raise LocationOperationalRevisionConflict(
                    command.location_id,
                    command.expected_operational_revision,
                    current_revision,
                )

            await session.execute(
                text(
                    """
                    UPDATE request_engine.location_operational_hours
                       SET active = false
                     WHERE organization_id = :organization_id
                       AND location_id = :location_id
                       AND active
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "location_id": command.location_id,
                },
            )
            for item in windows:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.location_operational_hours (
                            organization_id, location_id, weekday,
                            local_start, local_end, valid_from, valid_until
                        ) VALUES (
                            :organization_id, :location_id, :weekday,
                            :local_start, :local_end, :valid_from, :valid_until
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "location_id": command.location_id,
                        "weekday": item.weekday,
                        "local_start": item.local_start,
                        "local_end": item.local_end,
                        "valid_from": item.valid_from,
                        "valid_until": item.valid_until,
                    },
                )

            final_revision = cast(
                int,
                (
                    await session.execute(
                        text(
                            """
                            SELECT operational_revision
                            FROM request_engine.locations
                            WHERE organization_id = :organization_id
                              AND id = :location_id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                        },
                    )
                ).scalar_one(),
            )
            state = LocationOperationalHoursState(
                location_id=command.location_id,
                operational_revision=final_revision,
                windows=windows,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="catalog.set_location_operational_hours",
                aggregate_kind="Location",
                aggregate_id=command.location_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "previous_operational_revision": current_revision,
                    "new_operational_revision": final_revision,
                    "window_count": len(windows),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"state": _state_to_json(state)},
            )
            return state


def _validated_windows(
    windows: tuple[LocationOperationalHoursInput, ...],
) -> tuple[LocationOperationalHoursInput, ...]:
    seen: set[tuple[int, time, time, date | None, date | None]] = set()
    result: list[LocationOperationalHoursInput] = []
    for item in windows:
        if item.weekday < 0 or item.weekday > 6:
            raise ValueError("weekday must be between 0 and 6")
        if item.local_start >= item.local_end:
            raise ValueError("local_start must be before local_end")
        if (
            item.valid_from is not None
            and item.valid_until is not None
            and item.valid_until < item.valid_from
        ):
            raise ValueError("valid_until cannot be before valid_from")
        key = (
            item.weekday,
            item.local_start,
            item.local_end,
            item.valid_from,
            item.valid_until,
        )
        if key in seen:
            raise ValueError("duplicate operational-hours window")
        seen.add(key)
        result.append(item)
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.weekday,
                item.local_start,
                item.local_end,
                item.valid_from or date.min,
                item.valid_until or date.max,
            ),
        )
    )


def _state_to_json(state: LocationOperationalHoursState) -> dict[str, object]:
    return {
        "location_id": str(state.location_id),
        "operational_revision": state.operational_revision,
        "windows": [
            {
                "weekday": item.weekday,
                "local_start": item.local_start.isoformat(),
                "local_end": item.local_end.isoformat(),
                "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                "valid_until": item.valid_until.isoformat() if item.valid_until else None,
            }
            for item in state.windows
        ],
    }


def _state_from_json(value: dict[str, object]) -> LocationOperationalHoursState:
    raw_windows = cast(list[object], value["windows"])
    windows: list[LocationOperationalHoursInput] = []
    for raw in raw_windows:
        item = cast(dict[str, object], raw)
        valid_from = cast(str | None, item.get("valid_from"))
        valid_until = cast(str | None, item.get("valid_until"))
        windows.append(
            LocationOperationalHoursInput(
                weekday=cast(int, item["weekday"]),
                local_start=time.fromisoformat(cast(str, item["local_start"])),
                local_end=time.fromisoformat(cast(str, item["local_end"])),
                valid_from=date.fromisoformat(valid_from) if valid_from else None,
                valid_until=date.fromisoformat(valid_until) if valid_until else None,
            )
        )
    return LocationOperationalHoursState(
        location_id=UUID(cast(str, value["location_id"])),
        operational_revision=cast(int, value["operational_revision"]),
        windows=tuple(windows),
    )
