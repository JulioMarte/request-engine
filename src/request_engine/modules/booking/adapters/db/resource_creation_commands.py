from datetime import date, time
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.application.commands.create_resource import (
    CapacityModel,
    CreateResourceCommand,
    ResourceBootstrapState,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_operational_authority,
)

_CAPABILITY = "booking.create_resource"


class PostgresResourceCreationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_resource(self, command: CreateResourceCommand) -> ResourceBootstrapState:
        windows = tuple(sorted(command.weekly_availability, key=_window_sort_key))
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "resource_key": command.resource_key.strip(),
                "display_name": command.display_name.strip(),
                "capacity_model": command.capacity_model,
                "capacity_units": command.capacity_units,
                "capability_ids": list(command.capability_ids),
                "weekly_availability": [_window_to_json(window) for window in windows],
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(cast(dict[str, object], replay["resource"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                location_exists = (
                    await session.execute(
                        text(
                            """
                            SELECT 1 FROM request_engine.locations
                            WHERE organization_id = :organization_id
                              AND id = :location_id AND active
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                        },
                    )
                ).first()
                if location_exists is None:
                    raise ContextualConfigurationConflict(
                        "Location is missing, inactive, or foreign"
                    )
                if command.capability_ids:
                    count = cast(
                        int,
                        (
                            await session.execute(
                                text(
                                    """
                                    SELECT count(*)
                                    FROM request_engine.resource_capabilities
                                    WHERE organization_id = :organization_id
                                      AND id = ANY(CAST(:capability_ids AS uuid[]))
                                    """
                                ),
                                {
                                    "organization_id": command.organization_id,
                                    "capability_ids": [
                                        str(value) for value in command.capability_ids
                                    ],
                                },
                            )
                        ).scalar_one(),
                    )
                    if count != len(command.capability_ids):
                        raise ContextualConfigurationConflict(
                            "Resource capabilities are missing or foreign"
                        )
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.resources (
                                    organization_id, location_id, resource_key, display_name,
                                    capacity_model, capacity_units
                                ) VALUES (
                                    :organization_id, :location_id, :resource_key, :display_name,
                                    :capacity_model, :capacity_units
                                )
                                RETURNING id, resource_key, display_name, capacity_model,
                                          capacity_units
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "location_id": command.location_id,
                                "resource_key": command.resource_key.strip(),
                                "display_name": command.display_name.strip(),
                                "capacity_model": command.capacity_model,
                                "capacity_units": command.capacity_units,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                resource_id = cast(UUID, row["id"])
                for capability_id in command.capability_ids:
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.resource_capability_assignments (
                                organization_id, resource_id, capability_id
                            ) VALUES (:organization_id, :resource_id, :capability_id)
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "resource_id": resource_id,
                            "capability_id": capability_id,
                        },
                    )

                assignment_id = cast(
                    UUID,
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.resource_location_assignments (
                                    organization_id, resource_id, location_id,
                                    effective_during
                                ) VALUES (
                                    :organization_id, :resource_id, :location_id,
                                    tstzrange(clock_timestamp(), NULL, '[)')
                                )
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": resource_id,
                                "location_id": command.location_id,
                            },
                        )
                    ).scalar_one(),
                )
                for window in windows:
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.resource_location_availability (
                                organization_id,
                                resource_location_assignment_id,
                                weekday,
                                local_start,
                                local_end,
                                valid_from,
                                valid_until
                            ) VALUES (
                                :organization_id,
                                :assignment_id,
                                :weekday,
                                :local_start,
                                :local_end,
                                :valid_from,
                                :valid_until
                            )
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "assignment_id": assignment_id,
                            "weekday": window.weekday,
                            "local_start": window.local_start,
                            "local_end": window.local_end,
                            "valid_from": window.valid_from,
                            "valid_until": window.valid_until,
                        },
                    )
                # The assignment insert bumps the Resource availability revision;
                # bootstrap reports the final revision even when no schedule
                # windows were supplied.
                final_revision = cast(
                    int,
                    (
                        await session.execute(
                            text(
                                """
                                SELECT availability_revision
                                FROM request_engine.resources
                                WHERE organization_id = :organization_id
                                  AND id = :resource_id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": resource_id,
                            },
                        )
                    ).scalar_one(),
                )
                state = ResourceBootstrapState(
                    resource_id=resource_id,
                    resource_key=cast(str, row["resource_key"]),
                    display_name=cast(str, row["display_name"]),
                    capacity_model=cast(CapacityModel, row["capacity_model"]),
                    capacity_units=cast(int, row["capacity_units"]),
                    availability_revision=final_revision,
                    capability_ids=command.capability_ids,
                    weekly_availability=windows,
                    resource_location_assignment_id=assignment_id,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="Resource",
                    aggregate_id=resource_id,
                    idempotency_id=idem,
                    details={
                        "authority": authority.audit_details(),
                        "location_id": str(command.location_id),
                        "capability_count": len(command.capability_ids),
                        "weekly_availability_window_count": len(windows),
                        "resource_location_assignment_id": str(assignment_id),
                    },
                )
                await complete_idempotency(session, idem, {"resource": _state_to_json(state)})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ContextualConfigurationConflict(
                    "Resource conflicts with tenant configuration"
                ) from None
            raise


def _window_sort_key(window: ResourceLocationAvailabilityWindow) -> tuple[object, ...]:
    return (
        window.weekday,
        window.local_start,
        window.local_end,
        window.valid_from or date.min,
        window.valid_until or date.max,
    )


def _window_to_json(window: ResourceLocationAvailabilityWindow) -> dict[str, object]:
    return {
        "weekday": window.weekday,
        "local_start": window.local_start.isoformat(),
        "local_end": window.local_end.isoformat(),
        "valid_from": window.valid_from.isoformat() if window.valid_from else None,
        "valid_until": window.valid_until.isoformat() if window.valid_until else None,
    }


def _window_from_json(value: dict[str, object]) -> ResourceLocationAvailabilityWindow:
    valid_from = cast(str | None, value.get("valid_from"))
    valid_until = cast(str | None, value.get("valid_until"))
    return ResourceLocationAvailabilityWindow(
        weekday=cast(int, value["weekday"]),
        local_start=time.fromisoformat(cast(str, value["local_start"])),
        local_end=time.fromisoformat(cast(str, value["local_end"])),
        valid_from=date.fromisoformat(valid_from) if valid_from else None,
        valid_until=date.fromisoformat(valid_until) if valid_until else None,
    )


def _state_to_json(state: ResourceBootstrapState) -> dict[str, object]:
    return {
        "resource_id": str(state.resource_id),
        "resource_key": state.resource_key,
        "display_name": state.display_name,
        "capacity_model": state.capacity_model,
        "capacity_units": state.capacity_units,
        "availability_revision": state.availability_revision,
        "capability_ids": [str(value) for value in state.capability_ids],
        "weekly_availability": [_window_to_json(window) for window in state.weekly_availability],
        "resource_location_assignment_id": (
            str(state.resource_location_assignment_id)
            if state.resource_location_assignment_id is not None
            else None
        ),
    }


def _state_from_json(value: dict[str, object]) -> ResourceBootstrapState:
    windows_raw = cast(list[dict[str, object]], value.get("weekly_availability", []))
    assignment_id = cast(str | None, value.get("resource_location_assignment_id"))
    return ResourceBootstrapState(
        resource_id=UUID(cast(str, value["resource_id"])),
        resource_key=cast(str, value["resource_key"]),
        display_name=cast(str, value["display_name"]),
        capacity_model=cast(CapacityModel, value["capacity_model"]),
        capacity_units=cast(int, value["capacity_units"]),
        availability_revision=cast(int, value["availability_revision"]),
        capability_ids=tuple(UUID(item) for item in cast(list[str], value["capability_ids"])),
        weekly_availability=tuple(_window_from_json(item) for item in windows_raw),
        resource_location_assignment_id=UUID(assignment_id) if assignment_id else None,
    )