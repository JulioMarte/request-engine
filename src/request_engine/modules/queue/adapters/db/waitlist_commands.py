import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
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
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresWaitlistCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def join_waitlist(self, command: JoinWaitlistCommand) -> WaitlistEntry:
        fingerprint = _fingerprint(
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
            idempotency_id, replay = await _acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.join",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))

            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=command.subject_party_id,
                scope_key=JOIN_WAITLIST_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            await _lock_active_offering(session, command.organization_id, command.offering_id)

            existing = (
                await session.execute(
                    text(
                        """
                        SELECT id
                        FROM request_engine.waitlist_entries
                        WHERE organization_id = :organization_id
                          AND offering_id = :offering_id
                          AND subject_party_id = :subject_party_id
                          AND status = 'active'
                        LIMIT 1
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "offering_id": command.offering_id,
                        "subject_party_id": command.subject_party_id,
                    },
                )
            ).first()
            if existing is not None:
                raise AlreadyOnWaitlist(command.offering_id, command.subject_party_id)

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.waitlist_entries (
                                organization_id, offering_id, subject_party_id,
                                location_id, preferred_resource_id,
                                earliest_start, latest_start
                            ) VALUES (
                                :organization_id, :offering_id, :subject_party_id,
                                :location_id, :preferred_resource_id,
                                :earliest_start, :latest_start
                            )
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
                .one()
            )
            entry = _entry_from_row(row)
            await _audit(
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
            await _outbox(
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
            await _complete_idempotency(session, idempotency_id, {"entry": _entry_to_json(entry)})
            return entry

    async def leave_waitlist(self, command: LeaveWaitlistCommand) -> WaitlistEntry:
        fingerprint = _fingerprint(
            "waitlist.leave",
            {
                "waitlist_entry_id": command.waitlist_entry_id,
                "expected_revision": command.expected_revision,
                "reason": command.reason,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await _acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.leave",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _entry_from_json(cast(dict[str, object], replay["entry"]))

            locked = (
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
                        {
                            "organization_id": command.organization_id,
                            "entry_id": command.waitlist_entry_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if locked is None:
                raise WaitlistEntryNotFound(command.waitlist_entry_id)
            current = _entry_from_row(locked)

            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=current.subject_party_id,
                scope_key=MANAGE_WAITLIST_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            if current.revision != command.expected_revision:
                raise WaitlistEntryRevisionConflict(
                    current.id,
                    command.expected_revision,
                    current.revision,
                )
            if current.status is not WaitlistEntryStatus.ACTIVE:
                raise WaitlistEntryNotCancellable(current.id, current.status.value)

            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.waitlist_entries
                            SET status = 'cancelled', revision = revision + 1
                            WHERE organization_id = :organization_id
                              AND id = :entry_id
                              AND revision = :expected_revision
                            RETURNING id, offering_id, subject_party_id, location_id,
                                      preferred_resource_id, earliest_start, latest_start,
                                      status, revision, created_at
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "entry_id": current.id,
                            "expected_revision": command.expected_revision,
                        },
                    )
                )
                .mappings()
                .one()
            )
            entry = _entry_from_row(row)
            await _audit(
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
            await _outbox(
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
            await _complete_idempotency(session, idempotency_id, {"entry": _entry_to_json(entry)})
            return entry

    async def create_slot_opportunity(
        self,
        command: CreateSlotOpportunityCommand,
    ) -> SlotOpportunity:
        fingerprint = _fingerprint(
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
            idempotency_id, replay = await _acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.create_opportunity",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _opportunity_from_json(cast(dict[str, object], replay["opportunity"]))

            existing = (
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
                            "organization_id": command.organization_id,
                            "source_event_id": command.source_event_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                opportunity = _opportunity_from_row(existing)
                if not _matches_opportunity(command, opportunity):
                    raise SlotOpportunitySourceConflict(command.source_event_id)
                await _complete_idempotency(
                    session,
                    idempotency_id,
                    {"opportunity": _opportunity_to_json(opportunity)},
                )
                return opportunity

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.slot_opportunities (
                                organization_id, offering_version_id, location_id,
                                source_reservation_id, source_event_id, during
                            ) VALUES (
                                :organization_id, :offering_version_id, :location_id,
                                :source_reservation_id, :source_event_id,
                                tstzrange(:start_at, :end_at, '[)')
                            )
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
                .one()
            )
            opportunity = _opportunity_from_row(row)
            await _audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="waitlist.create_opportunity",
                aggregate_kind="SlotOpportunity",
                aggregate_id=opportunity.id,
                idempotency_id=idempotency_id,
                details={"source_event_id": str(command.source_event_id)},
            )
            await _outbox(
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
            await _complete_idempotency(
                session,
                idempotency_id,
                {"opportunity": _opportunity_to_json(opportunity)},
            )
            return opportunity


async def _lock_active_offering(session: AsyncSession, organization_id: UUID, offering_id: UUID) -> None:
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


async def _acquire_idempotency(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[UUID, dict[str, object] | None]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT idempotency_id, result_data, replay
                    FROM request_cmd.acquire_idempotency(
                        :organization_id, :principal_id, :capability,
                        :idempotency_key, :fingerprint
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "capability": capability,
                    "idempotency_key": idempotency_key,
                    "fingerprint": fingerprint,
                },
            )
        )
        .mappings()
        .one()
    )
    idempotency_id = cast(UUID, row["idempotency_id"])
    if cast(bool, row["replay"]):
        return idempotency_id, cast(dict[str, object], row["result_data"])
    return idempotency_id, None


async def _complete_idempotency(
    session: AsyncSession,
    idempotency_id: UUID,
    result: dict[str, object],
) -> None:
    completed = (
        await session.execute(
            text("SELECT request_cmd.complete_idempotency(:id, CAST(:result AS jsonb))"),
            {"id": idempotency_id, "result": json.dumps(result, separators=(",", ":"))},
        )
    ).scalar_one()
    if completed is not True:
        raise RuntimeError(f"idempotency record {idempotency_id} could not be completed")


async def _audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    command_name: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    idempotency_id: UUID,
    details: dict[str, object],
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.audit_records (
                organization_id, actor_principal_id, command_name,
                aggregate_kind, aggregate_id, idempotency_record_id, details
            ) VALUES (
                :organization_id, :principal_id, :command_name,
                :aggregate_kind, :aggregate_id, :idempotency_id, CAST(:details AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "principal_id": principal_id,
            "command_name": command_name,
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "idempotency_id": idempotency_id,
            "details": json.dumps(details, separators=(",", ":")),
        },
    )


async def _outbox(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    payload: dict[str, object],
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id, event_type, schema_version,
                aggregate_kind, aggregate_id, payload
            ) VALUES (
                :organization_id, :event_type, 1,
                :aggregate_kind, :aggregate_id, CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "event_type": event_type,
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "payload": json.dumps(payload, separators=(",", ":")),
        },
    )


def _fingerprint(capability: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"capability": capability, **values},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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
