"""Close or reopen a ServiceQueue (``queue_service_queue_set_active``).

READ     exact Party authority (``operations.manage_supply``) inside the
         transaction, then idempotency/replay;
LOCK     the ``service_queues`` row ``FOR UPDATE`` -- the same first lock taken by
         join, check-in and call-next (queue -> intake control -> entries), so an
         admission either commits before the close (and is counted) or waits and
         then observes the queue inactive;
VALIDATE revision CAS, unchanged-state refusal, no waiting/called/serving entry
         when closing, active Location when reopening;
WRITE    ``service_queues.active`` (the revision trigger steps exactly once);
EMIT     audit + PII-free ``service_queue.deactivated.v1`` /
         ``service_queue.activated.v1`` outbox fact.

Intake control (``service_queue_intake_controls``) is deliberately untouched:
pausing intake and closing the queue are different decisions.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.commands.set_service_queue_active import (
    ServiceQueueActivationState,
    SetServiceQueueActiveCommand,
)
from request_engine.modules.queue.application.errors import (
    QueueConfigurationConflict,
    QueueNotFound,
    ServiceQueueHasActiveEntries,
    ServiceQueueRevisionConflict,
    ServiceQueueStateUnchanged,
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

_CAPABILITY = "queue.set_service_queue_active"
DEACTIVATED_EVENT = "service_queue.deactivated.v1"
ACTIVATED_EVENT = "service_queue.activated.v1"


class PostgresServiceQueueActivationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_service_queue_active(
        self, command: SetServiceQueueActiveCommand
    ) -> ServiceQueueActivationState:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "queue_id": command.queue_id,
                "expected_revision": command.expected_revision,
                "active": command.active,
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
            idem, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["service_queue"]))
            current = await _lock_queue(session, command.organization_id, command.queue_id)
            revision = cast(int, current["revision"])
            if revision != command.expected_revision:
                raise ServiceQueueRevisionConflict(
                    command.queue_id, command.expected_revision, revision
                )
            if cast(bool, current["active"]) == command.active:
                raise ServiceQueueStateUnchanged(command.queue_id, command.active)
            if command.active:
                await _require_active_location(session, command, current)
            else:
                await _require_drained(session, command)
            state = await _write_active(session, command)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="ServiceQueue",
                aggregate_id=command.queue_id,
                idempotency_id=idem,
                details={
                    "authority": authority.audit_details(),
                    "active": state.active,
                    "previous_revision": revision,
                    "new_revision": state.revision,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=ACTIVATED_EVENT if state.active else DEACTIVATED_EVENT,
                aggregate_kind="ServiceQueue",
                aggregate_id=command.queue_id,
                payload={
                    "queue_id": str(state.queue_id),
                    "location_id": str(state.location_id) if state.location_id else None,
                    "active": state.active,
                    "revision": state.revision,
                },
            )
            await complete_idempotency(session, idem, {"service_queue": _state_to_json(state)})
            return state


async def _lock_queue(session: AsyncSession, organization_id: UUID, queue_id: UUID) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT active, revision, location_id
                    FROM request_engine.service_queues
                    WHERE organization_id = :organization_id AND id = :queue_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "queue_id": queue_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise QueueNotFound(queue_id)
    return row


async def _require_drained(session: AsyncSession, command: SetServiceQueueActiveCommand) -> None:
    counts = (
        (
            await session.execute(
                text(
                    """
                    SELECT count(*) FILTER (WHERE status = 'waiting') AS waiting,
                           count(*) FILTER (WHERE status = 'called') AS called,
                           count(*) FILTER (WHERE status = 'serving') AS serving
                    FROM request_engine.queue_entries
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :queue_id
                      AND status IN ('waiting', 'called', 'serving')
                    """
                ),
                {"organization_id": command.organization_id, "queue_id": command.queue_id},
            )
        )
        .mappings()
        .one()
    )
    waiting, called, serving = (int(counts[key]) for key in ("waiting", "called", "serving"))
    if waiting or called or serving:
        raise ServiceQueueHasActiveEntries(command.queue_id, waiting, called, serving)


async def _require_active_location(
    session: AsyncSession, command: SetServiceQueueActiveCommand, current: RowMapping
) -> None:
    location_id = cast(UUID | None, current["location_id"])
    if location_id is None:
        return
    active = (
        await session.execute(
            text(
                """
                SELECT active FROM request_engine.locations
                WHERE organization_id = :organization_id AND id = :location_id
                """
            ),
            {"organization_id": command.organization_id, "location_id": location_id},
        )
    ).scalar_one_or_none()
    if active is not True:
        raise QueueConfigurationConflict("the queue Location is inactive; reactivate it first")


async def _write_active(
    session: AsyncSession, command: SetServiceQueueActiveCommand
) -> ServiceQueueActivationState:
    row = (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.service_queues
                       SET active = :active
                     WHERE organization_id = :organization_id AND id = :queue_id
                    RETURNING id, queue_key, display_name, location_id, offering_id,
                              active, revision
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "queue_id": command.queue_id,
                    "active": command.active,
                },
            )
        )
        .mappings()
        .one()
    )
    return ServiceQueueActivationState(
        queue_id=cast(UUID, row["id"]),
        queue_key=cast(str, row["queue_key"]),
        display_name=cast(str, row["display_name"]),
        location_id=cast(UUID | None, row["location_id"]),
        offering_id=cast(UUID | None, row["offering_id"]),
        active=cast(bool, row["active"]),
        revision=cast(int, row["revision"]),
    )


def _state_to_json(state: ServiceQueueActivationState) -> dict[str, object]:
    return {
        "queue_id": str(state.queue_id),
        "queue_key": state.queue_key,
        "display_name": state.display_name,
        "location_id": str(state.location_id) if state.location_id else None,
        "offering_id": str(state.offering_id) if state.offering_id else None,
        "active": state.active,
        "revision": state.revision,
    }


def _state_from_json(value: dict[str, object]) -> ServiceQueueActivationState:
    location_id = value.get("location_id")
    offering_id = value.get("offering_id")
    return ServiceQueueActivationState(
        queue_id=UUID(cast(str, value["queue_id"])),
        queue_key=cast(str, value["queue_key"]),
        display_name=cast(str, value["display_name"]),
        location_id=UUID(cast(str, location_id)) if location_id is not None else None,
        offering_id=UUID(cast(str, offering_id)) if offering_id is not None else None,
        active=cast(bool, value["active"]),
        revision=cast(int, value["revision"]),
    )
