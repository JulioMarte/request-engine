"""Resource label and capability-set Commands owned by Booking.

READ     authority (Principal/Party standing) then idempotency receipt
LOCK     the Resource row ``FOR UPDATE`` -- the capacity root that
         ``guard_capacity_claim`` also locks, so a replacement serializes with
         every Hold/Reservation claim insert or re-validation on the Resource
VALIDATE expected ``availability_revision``; capability ids active in the tenant;
         no live Hold depends on a removed capability
WRITE    ``resources.display_name`` (rename, revision unchanged) or the
         ``resource_capability_assignments`` delta plus one revision step
EMIT     audit + PII-free outbox fact (ids, revisions, counts; never labels)

Existing CapacityClaims are never touched: confirmed Reservations relying on a
removed capability are retained and only counted.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.commands.replace_resource_capabilities import (
    ReplaceResourceCapabilitiesCommand,
    ResourceCapabilitiesState,
)
from request_engine.modules.booking.application.commands.update_resource import (
    ResourceUpdateState,
    UpdateResourceCommand,
    normalize_resource_display_name,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
    ResourceCapabilityHeld,
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
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_operational_authority,
)

UPDATE_CAPABILITY = "booking.update_resource"
REPLACE_CAPABILITY = "booking.replace_resource_capabilities"
RESOURCE_UPDATED_EVENT = "resource.updated.v1"
CAPABILITIES_REPLACED_EVENT = "resource.capabilities_replaced.v1"


class PostgresResourceConfigurationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def update_resource(self, command: UpdateResourceCommand) -> ResourceUpdateState:
        display_name = normalize_resource_display_name(command.display_name)
        fingerprint = command_fingerprint(
            UPDATE_CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "display_name": display_name,
                "expected_resource_availability_revision": (
                    command.expected_resource_availability_revision
                ),
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=UPDATE_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _update_from_json(cast(dict[str, object], replay["resource"]))
            current = await _lock_resource(
                session,
                command.organization_id,
                command.resource_id,
                command.expected_resource_availability_revision,
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.resources
                               SET display_name = :display_name
                             WHERE organization_id = :organization_id AND id = :resource_id
                            RETURNING id, resource_key, display_name, active,
                                      availability_revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "resource_id": command.resource_id,
                            "display_name": display_name,
                        },
                    )
                )
                .mappings()
                .one()
            )
            state = ResourceUpdateState(
                resource_id=cast(UUID, row["id"]),
                resource_key=cast(str, row["resource_key"]),
                display_name=cast(str, row["display_name"]),
                active=cast(bool, row["active"]),
                availability_revision=cast(int, row["availability_revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=UPDATE_CAPABILITY,
                aggregate_kind="Resource",
                aggregate_id=command.resource_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "display_name_changed": current["display_name"] != display_name,
                    "resource_availability_revision": state.availability_revision,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=RESOURCE_UPDATED_EVENT,
                aggregate_kind="Resource",
                aggregate_id=command.resource_id,
                payload={
                    "resource_id": str(command.resource_id),
                    "availability_revision": state.availability_revision,
                },
            )
            await complete_idempotency(session, idempotency_id, {"resource": _update_json(state)})
            return state

    async def replace_resource_capabilities(
        self, command: ReplaceResourceCapabilitiesCommand
    ) -> ResourceCapabilitiesState:
        requested = tuple(sorted(set(command.capability_ids), key=str))
        fingerprint = command_fingerprint(
            REPLACE_CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "capability_ids": [str(value) for value in requested],
                "expected_resource_availability_revision": (
                    command.expected_resource_availability_revision
                ),
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=REPLACE_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _capabilities_from_json(cast(dict[str, object], replay["capabilities"]))
            current = await _lock_resource(
                session,
                command.organization_id,
                command.resource_id,
                command.expected_resource_availability_revision,
            )
            await _require_active_capabilities(session, command.organization_id, requested)
            previous = await _assigned_capabilities(
                session, command.organization_id, command.resource_id
            )
            added = tuple(value for value in requested if value not in previous)
            removed = tuple(value for value in sorted(previous, key=str) if value not in requested)
            if removed:
                await _refuse_live_holds(
                    session, command.organization_id, command.resource_id, removed
                )
            revision = cast(int, current["availability_revision"])
            if added or removed:
                revision = await _write_delta(
                    session, command.organization_id, command.resource_id, added, removed
                )
            retained = await _retained_commitments(
                session, command.organization_id, command.resource_id, removed
            )
            state = ResourceCapabilitiesState(
                resource_id=command.resource_id,
                capability_ids=requested,
                added_capability_ids=added,
                removed_capability_ids=removed,
                retained_commitment_count=retained,
                availability_revision=revision,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=REPLACE_CAPABILITY,
                aggregate_kind="Resource",
                aggregate_id=command.resource_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "previous_capability_ids": [str(v) for v in sorted(previous, key=str)],
                    "capability_ids": [str(v) for v in requested],
                    "added_capability_ids": [str(v) for v in added],
                    "removed_capability_ids": [str(v) for v in removed],
                    "retained_commitment_count": retained,
                    "previous_resource_availability_revision": current["availability_revision"],
                    "new_resource_availability_revision": revision,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=CAPABILITIES_REPLACED_EVENT,
                aggregate_kind="Resource",
                aggregate_id=command.resource_id,
                payload={
                    "resource_id": str(command.resource_id),
                    "added_capability_ids": [str(v) for v in added],
                    "removed_capability_ids": [str(v) for v in removed],
                    "retained_commitment_count": retained,
                    "availability_revision": revision,
                },
            )
            await complete_idempotency(
                session, idempotency_id, {"capabilities": _capabilities_json(state)}
            )
            return state


async def _lock_resource(
    session: AsyncSession, organization_id: UUID, resource_id: UUID, expected: int
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT display_name, availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id AND id = :resource_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ContextualConfigurationConflict(
            "Resource is missing or belongs to another Organization"
        )
    current = cast(int, row["availability_revision"])
    if current != expected:
        raise ResourceAvailabilityRevisionConflict(resource_id, expected, current)
    return row


async def _require_active_capabilities(
    session: AsyncSession, organization_id: UUID, capability_ids: tuple[UUID, ...]
) -> None:
    if not capability_ids:
        return
    found = (
        await session.execute(
            text(
                """
                SELECT count(*)
                FROM request_engine.resource_capabilities
                WHERE organization_id = :organization_id
                  AND active
                  AND id = ANY(CAST(:capability_ids AS uuid[]))
                """
            ),
            {
                "organization_id": organization_id,
                "capability_ids": [str(value) for value in capability_ids],
            },
        )
    ).scalar_one()
    if cast(int, found) != len(capability_ids):
        raise ContextualConfigurationConflict(
            "capability_ids contain an unknown, inactive or foreign ResourceCapability"
        )


async def _assigned_capabilities(
    session: AsyncSession, organization_id: UUID, resource_id: UUID
) -> frozenset[UUID]:
    rows = (
        await session.execute(
            text(
                """
                SELECT capability_id
                FROM request_engine.resource_capability_assignments
                WHERE organization_id = :organization_id AND resource_id = :resource_id
                """
            ),
            {"organization_id": organization_id, "resource_id": resource_id},
        )
    ).scalars()
    return frozenset(cast(UUID, value) for value in rows)


_DEPENDENT_CLAIMS = """
    FROM request_engine.capacity_claims c
    JOIN request_engine.offering_resource_requirements rr
      ON rr.organization_id = c.organization_id AND rr.id = c.requirement_id
    {owner_join}
    WHERE c.organization_id = :organization_id
      AND c.resource_id = :resource_id
      AND c.status = 'active'
      AND rr.capability_id = ANY(CAST(:capability_ids AS uuid[]))
      AND {owner_condition}
"""


async def _refuse_live_holds(
    session: AsyncSession, organization_id: UUID, resource_id: UUID, removed: tuple[UUID, ...]
) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT rr.capability_id"
                + _DEPENDENT_CLAIMS.format(
                    owner_join=(
                        "JOIN request_engine.capacity_holds h "
                        "ON h.organization_id = c.organization_id AND h.id = c.hold_id"
                    ),
                    owner_condition=(
                        "c.reservation_id IS NULL AND h.status = 'active' "
                        "AND h.expires_at > clock_timestamp()"
                    ),
                )
            ),
            {
                "organization_id": organization_id,
                "resource_id": resource_id,
                "capability_ids": [str(value) for value in removed],
            },
        )
    ).scalars()
    held = tuple(sorted((cast(UUID, value) for value in rows), key=str))
    if held:
        raise ResourceCapabilityHeld(resource_id, held)


async def _retained_commitments(
    session: AsyncSession, organization_id: UUID, resource_id: UUID, removed: tuple[UUID, ...]
) -> int:
    if not removed:
        return 0
    return cast(
        int,
        (
            await session.execute(
                text(
                    "SELECT count(DISTINCT c.reservation_id)"
                    + _DEPENDENT_CLAIMS.format(
                        owner_join=(
                            "JOIN request_engine.reservations r "
                            "ON r.organization_id = c.organization_id AND r.id = c.reservation_id"
                        ),
                        owner_condition=(
                            "r.status = 'confirmed' AND upper(c.during) > clock_timestamp()"
                        ),
                    )
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "capability_ids": [str(value) for value in removed],
                },
            )
        ).scalar_one(),
    )


async def _write_delta(
    session: AsyncSession,
    organization_id: UUID,
    resource_id: UUID,
    added: tuple[UUID, ...],
    removed: tuple[UUID, ...],
) -> int:
    params = {"organization_id": organization_id, "resource_id": resource_id}
    if removed:
        await session.execute(
            text(
                """
                DELETE FROM request_engine.resource_capability_assignments
                WHERE organization_id = :organization_id
                  AND resource_id = :resource_id
                  AND capability_id = ANY(CAST(:capability_ids AS uuid[]))
                """
            ),
            {**params, "capability_ids": [str(value) for value in removed]},
        )
    if added:
        await session.execute(
            text(
                """
                INSERT INTO request_engine.resource_capability_assignments (
                    organization_id, resource_id, capability_id
                )
                SELECT :organization_id, :resource_id, value
                FROM unnest(CAST(:capability_ids AS uuid[])) AS value
                """
            ),
            {**params, "capability_ids": [str(value) for value in added]},
        )
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.resources
                       SET availability_revision = availability_revision + 1
                     WHERE organization_id = :organization_id AND id = :resource_id
                    RETURNING availability_revision
                    """
                ),
                params,
            )
        ).scalar_one(),
    )


def _update_json(state: ResourceUpdateState) -> dict[str, object]:
    return {
        "resource_id": str(state.resource_id),
        "resource_key": state.resource_key,
        "display_name": state.display_name,
        "active": state.active,
        "availability_revision": state.availability_revision,
    }


def _update_from_json(value: dict[str, object]) -> ResourceUpdateState:
    return ResourceUpdateState(
        resource_id=UUID(cast(str, value["resource_id"])),
        resource_key=cast(str, value["resource_key"]),
        display_name=cast(str, value["display_name"]),
        active=cast(bool, value["active"]),
        availability_revision=cast(int, value["availability_revision"]),
    )


def _ids(values: tuple[UUID, ...]) -> list[str]:
    return [str(value) for value in values]


def _capabilities_json(state: ResourceCapabilitiesState) -> dict[str, object]:
    return {
        "resource_id": str(state.resource_id),
        "capability_ids": _ids(state.capability_ids),
        "added_capability_ids": _ids(state.added_capability_ids),
        "removed_capability_ids": _ids(state.removed_capability_ids),
        "retained_commitment_count": state.retained_commitment_count,
        "availability_revision": state.availability_revision,
    }


def _parse_ids(value: object) -> tuple[UUID, ...]:
    return tuple(UUID(item) for item in cast(list[str], value))


def _capabilities_from_json(value: dict[str, object]) -> ResourceCapabilitiesState:
    return ResourceCapabilitiesState(
        resource_id=UUID(cast(str, value["resource_id"])),
        capability_ids=_parse_ids(value["capability_ids"]),
        added_capability_ids=_parse_ids(value["added_capability_ids"]),
        removed_capability_ids=_parse_ids(value["removed_capability_ids"]),
        retained_commitment_count=cast(int, value["retained_commitment_count"]),
        availability_revision=cast(int, value["availability_revision"]),
    )
