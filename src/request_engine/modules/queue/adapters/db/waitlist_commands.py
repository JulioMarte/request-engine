from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.adapters.db.tenant_references import (
    require_active_subject_party,
    require_tenant_reference,
)
from request_engine.modules.queue.application.authority import (
    JOIN_WAITLIST_SCOPE,
    MANAGE_WAITLIST_SCOPE,
)
from request_engine.modules.queue.application.commands.create_slot_opportunity import (
    CreateSlotOpportunityCommand,
)
from request_engine.modules.queue.application.commands.join_waitlist import JoinWaitlistCommand
from request_engine.modules.queue.application.commands.leave_waitlist import LeaveWaitlistCommand
from request_engine.modules.queue.application.errors import (
    AlreadyOnWaitlist,
    OfferingNotAvailableForWaitlist,
    SlotOpportunitySourceConflict,
    WaitlistEntryNotCancellable,
    WaitlistEntryNotFound,
    WaitlistEntryRevisionConflict,
)
from request_engine.modules.queue.contracts.waitlist import (
    SlotOpportunity,
    SlotOpportunityStatus,
    WaitlistEntry,
    WaitlistEntryStatus,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresWaitlistCommands:
    """Authoritative Waitlist and SlotOpportunity PostgreSQL commands."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def join_waitlist(self, command: JoinWaitlistCommand) -> WaitlistEntry:
        fingerprint = command_fingerprint(
            "waitlist.join",
            {
                "offering_id": command.offering_id,
                "subject_party_id": command.subject_party_id,
                "location_id": command.location_id,
                "preferred_resource_id": command.preferred_resource_id,
                "earliest_start": command.earliest_start,
                "latest_start": command.latest_start,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.join",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))

            await require_active_subject_party(
                session,
                organization_id=command.organization_id,
                subject_party_id=command.subject_party_id,
            )
            await require_tenant_reference(
                session,
                organization_id=command.organization_id,
                table_name="locations",
                reference_kind="location_id",
                reference_id=command.location_id,
            )
            await require_tenant_reference(
                session,
                organization_id=command.organization_id,
                table_name="resources",
                reference_kind="preferred_resource_id",
                reference_id=command.preferred_resource_id,
            )
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=command.subject_party_id,
                scope_key=JOIN_WAITLIST_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            await _lock_active_offering(
                session,
                command.organization_id,
                command.offering_id,
            )

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.waitlist_entries (
                                organization_id,
                                offering_id,
                                subject_party_id,
                                location_id,
                                preferred_resource_id,
                                earliest_start,
                                latest_start
                            ) VALUES (
                                :organization_id,
                                :offering_id,
                                :subject_party_id,
                                :location_id,
                                :preferred_resource_id,
                                :earliest_start,
                                :latest_start
                            )
                            ON CONFLICT (
                                organization_id,
                                offering_id,
                                subject_party_id
                            ) WHERE status = 'active'
                            DO NOTHING
                            RETURNING id, offering_id, subject_party_id, location_id,
                                      preferred_resource_id, earliest_start, latest_start,
                                      status, revision, created_at
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_id": command.offering_id,
                            "subject_party_id": command.subject_party_id,
                            "location_id": command.location_id,
                            "preferred_resource_id": command.preferred_resource_id,
                            "earliest_start": command.earliest_start,
                            "latest_start": command.latest_start,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AlreadyOnWaitlist(command.offering_id, command.subject_party_id)

            entry = _entry_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="waitlist.join",
                aggregate_kind="WaitlistEntry",
                aggregate_id=entry.id,
                idempotency_id=idempotency_id,
                details={
                    "offering_id": str(command.offering_id),
                    "subject_party_id": str(command.subject_party_id),
                    "subject_authority": authority.audit_details(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="waitlist.entry_joined.v1",
                aggregate_kind="WaitlistEntry",
                aggregate_id=entry.id,
                payload={
                    "waitlist_entry_id": str(entry.id),
                    "offering_id": str(entry.offering_id),
                    "subject_party_id": str(entry.subject_party_id),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"entry": _entry_to_json(entry)},
            )
            return entry

    async def leave_waitlist(self, command: LeaveWaitlistCommand) -> WaitlistEntry:
        fingerprint = command_fingerprint(
            "waitlist.leave",
            {
                "waitlist_entry_id": command.waitlist_entry_id,
                "expected_revision": command.expected_revision,
                "reason": command.reason,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.leave",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))

            locked = await _lock_waitlist_entry(
                session,
                command.organization_id,
                command.waitlist_entry_id,
            )
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=locked.subject_party_id,
                scope_key=MANAGE_WAITLIST_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            if locked.revision != command.expected_revision:
                raise WaitlistEntryRevisionConflict(
                    locked.id,
                    command.expected_revision,
                    locked.revision,
                )
            if locked.status is not WaitlistEntryStatus.ACTIVE:
                raise WaitlistEntryNotCancellable(locked.id, locked.status.value)

            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.waitlist_entries
                            SET status = 'cancelled',
                                revision = revision + 1,
                                updated_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND id = :entry_id
                              AND revision = :expected_revision
                              AND status = 'active'
                            RETURNING id, offering_id, subject_party_id, location_id,
                                      preferred_resource_id, earliest_start, latest_start,
                                      status, revision, created_at
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "entry_id": locked.id,
                            "expected_revision": command.expected_revision,
                        },
                    )
                )
                .mappings()
                .one()
            )
            entry = _entry_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="waitlist.leave",
                aggregate_kind="WaitlistEntry",
                aggregate_id=entry.id,
                idempotency_id=idempotency_id,
                details={
                    "reason": command.reason,
                    "subject_authority": authority.audit_details(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="waitlist.entry_cancelled.v1",
                aggregate_kind="WaitlistEntry",
                aggregate_id=entry.id,
                payload={
                    "waitlist_entry_id": str(entry.id),
                    "offering_id": str(entry.offering_id),
                    "subject_party_id": str(entry.subject_party_id),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"entry": _entry_to_json(entry)},
            )
            return entry

    async def create_slot_opportunity(
        self,
        command: CreateSlotOpportunityCommand,
    ) -> SlotOpportunity:
        fingerprint = command_fingerprint(
            "waitlist.create_opportunity",
            {
                "offering_version_id": command.offering_version_id,
                "source_event_id": command.source_event_id,
                "source_reservation_id": command.source_reservation_id,
                "location_id": command.location_id,
                "start_at": command.start_at,
                "end_at": command.end_at,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.create_opportunity",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _opportunity_from_json(cast(dict[str, object], replay["opportunity"]))

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.slot_opportunities (
                                organization_id,
                                offering_version_id,
                                location_id,
                                source_reservation_id,
                                source_event_id,
                                during
                            ) VALUES (
                                :organization_id,
                                :offering_version_id,
                                :location_id,
                                :source_reservation_id,
                                :source_event_id,
                                tstzrange(:start_at, :end_at, '[)')
                            )
                            ON CONFLICT (organization_id, source_event_id)
                            DO NOTHING
                            RETURNING id, offering_version_id, location_id, source_event_id,
                                      source_reservation_id, lower(during) AS start_at,
                                      upper(during) AS end_at, status, revision, created_at
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": command.offering_version_id,
                            "location_id": command.location_id,
                            "source_reservation_id": command.source_reservation_id,
                            "source_event_id": command.source_event_id,
                            "start_at": command.start_at,
                            "end_at": command.end_at,
                        },
                    )
                )
                .mappings()
                .first()
            )

            created = row is not None
            if row is None:
                row = await _lock_opportunity_by_source_event(
                    session,
                    command.organization_id,
                    command.source_event_id,
                )
            opportunity = _opportunity_from_row(row)
            if not _matches_opportunity(command, opportunity):
                raise SlotOpportunitySourceConflict(command.source_event_id)

            if created:
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="waitlist.create_opportunity",
                    aggregate_kind="SlotOpportunity",
                    aggregate_id=opportunity.id,
                    idempotency_id=idempotency_id,
                    details={"source_event_id": str(command.source_event_id)},
                )
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="waitlist.slot_opportunity_created.v1",
                    aggregate_kind="SlotOpportunity",
                    aggregate_id=opportunity.id,
                    payload={
                        "slot_opportunity_id": str(opportunity.id),
                        "source_event_id": str(opportunity.source_event_id),
                        "offering_version_id": str(opportunity.offering_version_id),
                        "start_at": opportunity.start_at.isoformat(),
                        "end_at": opportunity.end_at.isoformat(),
                    },
                )

            await complete_idempotency(
                session,
                idempotency_id,
                {"opportunity": _opportunity_to_json(opportunity)},
            )
            return opportunity


async def _lock_active_offering(
    session: AsyncSession,
    organization_id: UUID,
    offering_id: UUID,
) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT active
                FROM request_engine.offerings
                WHERE organization_id = :organization_id
                  AND id = :offering_id
                FOR SHARE
                """
            ),
            {"organization_id": organization_id, "offering_id": offering_id},
        )
    ).first()
    if row is None or row[0] is not True:
        raise OfferingNotAvailableForWaitlist(offering_id)


async def _lock_waitlist_entry(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> WaitlistEntry:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_id, subject_party_id, location_id,
                           preferred_resource_id, earliest_start, latest_start,
                           status, revision, created_at
                    FROM request_engine.waitlist_entries
                    WHERE organization_id = :organization_id
                      AND id = :entry_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise WaitlistEntryNotFound(entry_id)
    return _entry_from_row(row)


async def _lock_opportunity_by_source_event(
    session: AsyncSession,
    organization_id: UUID,
    source_event_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, location_id, source_event_id,
                           source_reservation_id, lower(during) AS start_at,
                           upper(during) AS end_at, status, revision, created_at
                    FROM request_engine.slot_opportunities
                    WHERE organization_id = :organization_id
                      AND source_event_id = :source_event_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "source_event_id": source_event_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return row


def _entry_from_row(row: RowMapping) -> WaitlistEntry:
    return WaitlistEntry(
        id=cast(UUID, row["id"]),
        offering_id=cast(UUID, row["offering_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        preferred_resource_id=cast(UUID | None, row["preferred_resource_id"]),
        earliest_start=cast(datetime | None, row["earliest_start"]),
        latest_start=cast(datetime | None, row["latest_start"]),
        status=WaitlistEntryStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _entry_to_json(entry: WaitlistEntry) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "offering_id": str(entry.offering_id),
        "subject_party_id": str(entry.subject_party_id),
        "location_id": str(entry.location_id) if entry.location_id is not None else None,
        "preferred_resource_id": (
            str(entry.preferred_resource_id) if entry.preferred_resource_id is not None else None
        ),
        "earliest_start": entry.earliest_start.isoformat() if entry.earliest_start else None,
        "latest_start": entry.latest_start.isoformat() if entry.latest_start else None,
        "status": entry.status.value,
        "revision": entry.revision,
        "created_at": entry.created_at.isoformat(),
    }


def _entry_from_json(data: dict[str, object]) -> WaitlistEntry:
    return WaitlistEntry(
        id=UUID(cast(str, data["id"])),
        offering_id=UUID(cast(str, data["offering_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        location_id=UUID(cast(str, data["location_id"])) if data.get("location_id") else None,
        preferred_resource_id=(
            UUID(cast(str, data["preferred_resource_id"]))
            if data.get("preferred_resource_id")
            else None
        ),
        earliest_start=(
            datetime.fromisoformat(cast(str, data["earliest_start"]))
            if data.get("earliest_start")
            else None
        ),
        latest_start=(
            datetime.fromisoformat(cast(str, data["latest_start"]))
            if data.get("latest_start")
            else None
        ),
        status=WaitlistEntryStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
    )


def _opportunity_from_row(row: RowMapping) -> SlotOpportunity:
    return SlotOpportunity(
        id=cast(UUID, row["id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        source_event_id=cast(UUID, row["source_event_id"]),
        source_reservation_id=cast(UUID | None, row["source_reservation_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        status=SlotOpportunityStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _opportunity_to_json(opportunity: SlotOpportunity) -> dict[str, object]:
    return {
        "id": str(opportunity.id),
        "offering_version_id": str(opportunity.offering_version_id),
        "location_id": str(opportunity.location_id) if opportunity.location_id else None,
        "source_event_id": str(opportunity.source_event_id),
        "source_reservation_id": (
            str(opportunity.source_reservation_id) if opportunity.source_reservation_id else None
        ),
        "start_at": opportunity.start_at.isoformat(),
        "end_at": opportunity.end_at.isoformat(),
        "status": opportunity.status.value,
        "revision": opportunity.revision,
        "created_at": opportunity.created_at.isoformat(),
    }


def _opportunity_from_json(data: dict[str, object]) -> SlotOpportunity:
    return SlotOpportunity(
        id=UUID(cast(str, data["id"])),
        offering_version_id=UUID(cast(str, data["offering_version_id"])),
        location_id=UUID(cast(str, data["location_id"])) if data.get("location_id") else None,
        source_event_id=UUID(cast(str, data["source_event_id"])),
        source_reservation_id=(
            UUID(cast(str, data["source_reservation_id"]))
            if data.get("source_reservation_id")
            else None
        ),
        start_at=datetime.fromisoformat(cast(str, data["start_at"])),
        end_at=datetime.fromisoformat(cast(str, data["end_at"])),
        status=SlotOpportunityStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
    )


def _matches_opportunity(
    command: CreateSlotOpportunityCommand,
    opportunity: SlotOpportunity,
) -> bool:
    return (
        opportunity.offering_version_id == command.offering_version_id
        and opportunity.location_id == command.location_id
        and opportunity.source_reservation_id == command.source_reservation_id
        and opportunity.start_at == command.start_at
        and opportunity.end_at == command.end_at
    )
