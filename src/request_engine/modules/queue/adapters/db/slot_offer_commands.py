from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.slot_offer_capacity import (
    AcquireSlotOfferHold,
    ConsumeSlotOfferHold,
    ReleaseSlotOfferHold,
    SlotOfferCandidatePreferenceUnavailable,
    SlotOfferCapacityPort,
    SlotOfferCapacityUnavailable,
)
from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.application.authority import MANAGE_WAITLIST_SCOPE
from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
)
from request_engine.modules.queue.application.commands.decline_slot_offer import (
    DeclineSlotOfferCommand,
)
from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
)
from request_engine.modules.queue.application.errors import (
    SlotOfferExpired,
    SlotOfferNotActionable,
    SlotOfferNotFound,
    SlotOfferRevisionConflict,
    SlotOpportunityNotFound,
    SlotOpportunityNotOpen,
)
from request_engine.modules.queue.application.slot_offer_notifications import (
    SlotOfferNotificationPort,
)
from request_engine.modules.queue.contracts.waitlist import (
    AcceptedSlotOffer,
    SlotOffer,
    SlotOfferResolution,
    SlotOfferStatus,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action


class PostgresSlotOfferCommands:
    """Queue-owned orchestration for released-slot recovery."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        capacity: SlotOfferCapacityPort,
        notification: SlotOfferNotificationPort,
    ) -> None:
        self._session_factory = session_factory
        self._capacity = capacity
        self._notification = notification

    async def offer_next_waitlist_candidate(
        self,
        command: OfferNextWaitlistCandidateCommand,
    ) -> SlotOffer | None:
        fingerprint = command_fingerprint(
            "waitlist.offer_next_candidate",
            {
                "slot_opportunity_id": command.slot_opportunity_id,
                "offer_expires_at": command.offer_expires_at,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.offer_next_candidate",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                raw = cast(dict[str, object] | None, replay.get("offer"))
                return _offer_from_json(raw) if raw is not None else None

            opportunity = await _lock_opportunity(
                session,
                command.organization_id,
                command.slot_opportunity_id,
            )
            if cast(str, opportunity["status"]) != "open":
                raise SlotOpportunityNotOpen(
                    command.slot_opportunity_id,
                    cast(str, opportunity["status"]),
                )

            existing = await _active_offer_for_opportunity(
                session,
                command.organization_id,
                command.slot_opportunity_id,
            )
            if existing is not None:
                offer = _offer_from_row(existing)
                await complete_idempotency(
                    session, idempotency_id, {"offer": _offer_to_json(offer)}
                )
                return offer

            offer = await self._issue_next_locked(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                opportunity=opportunity,
                requested_expires_at=command.offer_expires_at,
                idempotency_id=idempotency_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"offer": _offer_to_json(offer) if offer is not None else None},
            )
            return offer

    async def accept_slot_offer(self, command: AcceptSlotOfferCommand) -> AcceptedSlotOffer:
        fingerprint = command_fingerprint(
            "waitlist.accept_offer",
            {
                "slot_offer_id": command.slot_offer_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.accept_offer",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return AcceptedSlotOffer(
                    offer=_offer_from_json(cast(dict[str, object], replay["offer"])),
                    reservation=_reservation_from_json(
                        cast(dict[str, object], replay["reservation"])
                    ),
                )

            offer_probe = await _read_offer(session, command.organization_id, command.slot_offer_id)
            opportunity = await _lock_opportunity(
                session,
                command.organization_id,
                cast(UUID, offer_probe["slot_opportunity_id"]),
            )
            offer_row = await _lock_offer(session, command.organization_id, command.slot_offer_id)
            _ensure_offer_revision(offer_row, command.slot_offer_id, command.expected_revision)
            offer_status = cast(str, offer_row["status"])
            if offer_status != "offered":
                raise SlotOfferNotActionable(command.slot_offer_id, offer_status)
            if cast(datetime, offer_row["expires_at"]) <= cast(datetime, offer_row["db_now"]):
                raise SlotOfferExpired(command.slot_offer_id)
            if cast(str, opportunity["status"]) != "open":
                raise SlotOpportunityNotOpen(
                    cast(UUID, opportunity["id"]),
                    cast(str, opportunity["status"]),
                )

            subject_party_id = cast(UUID, offer_row["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_WAITLIST_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            reservation = await self._capacity.consume_slot_offer_hold(
                session,
                ConsumeSlotOfferHold(
                    organization_id=command.organization_id,
                    hold_id=cast(UUID, offer_row["capacity_hold_id"]),
                ),
            )
            updated_offer = await _transition_offer(
                session,
                organization_id=command.organization_id,
                slot_offer_id=command.slot_offer_id,
                from_status="offered",
                to_status="accepted",
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.slot_opportunities
                    SET status = 'filled',
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :opportunity_id
                      AND status = 'open'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "opportunity_id": offer_row["slot_opportunity_id"],
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.waitlist_entries
                    SET status = 'fulfilled',
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :waitlist_entry_id
                      AND status = 'active'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "waitlist_entry_id": offer_row["waitlist_entry_id"],
                },
            )
            await self._notification.cancel_slot_offer_notification(
                session,
                organization_id=command.organization_id,
                slot_offer_id=command.slot_offer_id,
            )
            await _cancel_expiry_action(session, command.organization_id, command.slot_offer_id)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="waitlist.accept_offer",
                aggregate_kind="SlotOffer",
                aggregate_id=command.slot_offer_id,
                idempotency_id=idempotency_id,
                details={
                    "reservation_id": str(reservation.id),
                    "waitlist_entry_id": str(offer_row["waitlist_entry_id"]),
                    "subject_authority": authority.audit_details(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="waitlist.slot_offer_accepted.v1",
                aggregate_kind="SlotOffer",
                aggregate_id=command.slot_offer_id,
                payload={
                    "slot_offer_id": str(command.slot_offer_id),
                    "slot_opportunity_id": str(offer_row["slot_opportunity_id"]),
                    "reservation_id": str(reservation.id),
                    "waitlist_entry_id": str(offer_row["waitlist_entry_id"]),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.created.v1",
                aggregate_kind="Reservation",
                aggregate_id=reservation.id,
                payload={
                    "reservation_id": str(reservation.id),
                    "hold_id": str(offer_row["capacity_hold_id"]),
                    "subject_party_id": str(subject_party_id),
                    "start_at": reservation.start_at.isoformat(),
                    "end_at": reservation.end_at.isoformat(),
                },
            )
            result = AcceptedSlotOffer(
                offer=_offer_from_row(updated_offer),
                reservation=reservation,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "offer": _offer_to_json(result.offer),
                    "reservation": _reservation_to_json(result.reservation),
                },
            )
            return result

    async def decline_slot_offer(
        self,
        command: DeclineSlotOfferCommand,
    ) -> SlotOfferResolution:
        fingerprint = command_fingerprint(
            "waitlist.decline_offer",
            {
                "slot_offer_id": command.slot_offer_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.decline_offer",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _resolution_from_json(replay)

            resolution = await self._resolve_offer(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                slot_offer_id=command.slot_offer_id,
                expected_revision=command.expected_revision,
                terminal_status="declined",
                hold_terminal_status="released",
                idempotency_id=idempotency_id,
                require_authority=True,
                allow_subject_override=command.allow_subject_override,
            )
            await complete_idempotency(session, idempotency_id, _resolution_to_json(resolution))
            return resolution

    async def expire_slot_offer(
        self,
        command: ExpireSlotOfferCommand,
    ) -> SlotOfferResolution:
        fingerprint = command_fingerprint(
            "waitlist.expire_offer",
            {
                "slot_offer_id": command.slot_offer_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="waitlist.expire_offer",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _resolution_from_json(replay)

            probe = await _read_offer(session, command.organization_id, command.slot_offer_id)
            opportunity = await _lock_opportunity(
                session,
                command.organization_id,
                cast(UUID, probe["slot_opportunity_id"]),
            )
            offer_row = await _lock_offer(session, command.organization_id, command.slot_offer_id)
            current_status = cast(str, offer_row["status"])
            if current_status != "offered":
                resolution = SlotOfferResolution(offer=_offer_from_row(offer_row), next_offer=None)
                await complete_idempotency(session, idempotency_id, _resolution_to_json(resolution))
                return resolution
            _ensure_offer_revision(offer_row, command.slot_offer_id, command.expected_revision)
            if cast(datetime, offer_row["expires_at"]) > cast(datetime, offer_row["db_now"]):
                raise SlotOfferNotActionable(command.slot_offer_id, "offered_not_expired")
            resolution = await self._resolve_locked_offer(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                opportunity=opportunity,
                offer_row=offer_row,
                terminal_status="expired",
                hold_terminal_status="expired",
                idempotency_id=idempotency_id,
                authority_details=None,
            )
            await complete_idempotency(session, idempotency_id, _resolution_to_json(resolution))
            return resolution

    async def _resolve_offer(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        principal_id: UUID,
        slot_offer_id: UUID,
        expected_revision: int,
        terminal_status: str,
        hold_terminal_status: Literal["released", "expired"],
        idempotency_id: UUID,
        require_authority: bool,
        allow_subject_override: bool,
    ) -> SlotOfferResolution:
        probe = await _read_offer(session, organization_id, slot_offer_id)
        opportunity = await _lock_opportunity(
            session,
            organization_id,
            cast(UUID, probe["slot_opportunity_id"]),
        )
        offer_row = await _lock_offer(session, organization_id, slot_offer_id)
        _ensure_offer_revision(offer_row, slot_offer_id, expected_revision)
        current_status = cast(str, offer_row["status"])
        if current_status != "offered":
            raise SlotOfferNotActionable(slot_offer_id, current_status)
        if terminal_status == "declined" and cast(datetime, offer_row["expires_at"]) <= cast(
            datetime, offer_row["db_now"]
        ):
            raise SlotOfferExpired(slot_offer_id)

        authority_details: dict[str, object] | None = None
        if require_authority:
            authority = await require_subject_authority(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                subject_party_id=cast(UUID, offer_row["subject_party_id"]),
                scope_key=MANAGE_WAITLIST_SCOPE,
                allow_operator_override=allow_subject_override,
            )
            authority_details = authority.audit_details()
        return await self._resolve_locked_offer(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            opportunity=opportunity,
            offer_row=offer_row,
            terminal_status=terminal_status,
            hold_terminal_status=hold_terminal_status,
            idempotency_id=idempotency_id,
            authority_details=authority_details,
        )

    async def _resolve_locked_offer(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        principal_id: UUID,
        opportunity: RowMapping,
        offer_row: RowMapping,
        terminal_status: str,
        hold_terminal_status: Literal["released", "expired"],
        idempotency_id: UUID,
        authority_details: dict[str, object] | None,
    ) -> SlotOfferResolution:
        slot_offer_id = cast(UUID, offer_row["id"])
        await self._capacity.release_slot_offer_hold(
            session,
            ReleaseSlotOfferHold(
                organization_id=organization_id,
                hold_id=cast(UUID, offer_row["capacity_hold_id"]),
                terminal_status=hold_terminal_status,
            ),
        )
        updated = await _transition_offer(
            session,
            organization_id=organization_id,
            slot_offer_id=slot_offer_id,
            from_status="offered",
            to_status=terminal_status,
        )
        await self._notification.cancel_slot_offer_notification(
            session,
            organization_id=organization_id,
            slot_offer_id=slot_offer_id,
        )
        await _cancel_expiry_action(session, organization_id, slot_offer_id)

        created_at = cast(datetime, offer_row["created_at"])
        old_expires_at = cast(datetime, offer_row["expires_at"])
        ttl = max(old_expires_at - created_at, timedelta(seconds=30))
        db_now = cast(datetime, offer_row["db_now"])
        next_offer = await self._issue_next_locked(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            opportunity=opportunity,
            requested_expires_at=db_now + ttl,
            idempotency_id=idempotency_id,
        )
        await append_audit(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            command_name=f"waitlist.{terminal_status}_offer",
            aggregate_kind="SlotOffer",
            aggregate_id=slot_offer_id,
            idempotency_id=idempotency_id,
            details={
                "waitlist_entry_id": str(offer_row["waitlist_entry_id"]),
                "next_slot_offer_id": str(next_offer.id) if next_offer is not None else None,
                "subject_authority": authority_details,
            },
        )
        await append_outbox(
            session,
            organization_id=organization_id,
            event_type=f"waitlist.slot_offer_{terminal_status}.v1",
            aggregate_kind="SlotOffer",
            aggregate_id=slot_offer_id,
            payload={
                "slot_offer_id": str(slot_offer_id),
                "slot_opportunity_id": str(offer_row["slot_opportunity_id"]),
                "waitlist_entry_id": str(offer_row["waitlist_entry_id"]),
                "next_slot_offer_id": str(next_offer.id) if next_offer is not None else None,
            },
        )
        return SlotOfferResolution(offer=_offer_from_row(updated), next_offer=next_offer)

    async def _issue_next_locked(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        principal_id: UUID,
        opportunity: RowMapping,
        requested_expires_at: datetime,
        idempotency_id: UUID,
    ) -> SlotOffer | None:
        if cast(str, opportunity["status"]) != "open":
            return None
        db_now = cast(
            datetime,
            (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
        )
        start_at = cast(datetime, opportunity["start_at"])
        if start_at <= db_now:
            await _close_opportunity(
                session,
                organization_id,
                cast(UUID, opportunity["id"]),
                "expired",
            )
            return None

        effective_expires_at = min(requested_expires_at, start_at)
        if effective_expires_at <= db_now:
            effective_expires_at = min(db_now + timedelta(seconds=30), start_at)
        skipped: set[UUID] = set()

        while True:
            candidate = await _select_candidate(
                session,
                organization_id=organization_id,
                opportunity=opportunity,
                skipped=skipped,
            )
            if candidate is None:
                return None
            try:
                hold = await self._capacity.acquire_slot_offer_hold(
                    session,
                    AcquireSlotOfferHold(
                        organization_id=organization_id,
                        offering_version_id=cast(UUID, opportunity["offering_version_id"]),
                        subject_party_id=cast(UUID, candidate["subject_party_id"]),
                        location_id=cast(UUID | None, opportunity["location_id"]),
                        preferred_resource_id=cast(UUID | None, candidate["preferred_resource_id"]),
                        start_at=start_at,
                        end_at=cast(datetime, opportunity["end_at"]),
                        expires_at=effective_expires_at,
                    ),
                )
            except SlotOfferCandidatePreferenceUnavailable:
                skipped.add(cast(UUID, candidate["id"]))
                continue
            except SlotOfferCapacityUnavailable:
                await _close_opportunity(
                    session,
                    organization_id,
                    cast(UUID, opportunity["id"]),
                    "closed",
                )
                await append_outbox(
                    session,
                    organization_id=organization_id,
                    event_type="waitlist.slot_opportunity_closed.v1",
                    aggregate_kind="SlotOpportunity",
                    aggregate_id=cast(UUID, opportunity["id"]),
                    payload={
                        "slot_opportunity_id": str(opportunity["id"]),
                        "reason": "capacity_unavailable",
                    },
                )
                return None

            offer_row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.slot_offers (
                                organization_id,
                                slot_opportunity_id,
                                waitlist_entry_id,
                                capacity_hold_id,
                                expires_at
                            ) VALUES (
                                :organization_id,
                                :slot_opportunity_id,
                                :waitlist_entry_id,
                                :capacity_hold_id,
                                :expires_at
                            )
                            RETURNING id, slot_opportunity_id, waitlist_entry_id,
                                      capacity_hold_id, expires_at, status, revision, created_at
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "slot_opportunity_id": opportunity["id"],
                            "waitlist_entry_id": candidate["id"],
                            "capacity_hold_id": hold.id,
                            "expires_at": hold.expires_at,
                        },
                    )
                )
                .mappings()
                .one()
            )
            offer = _offer_from_row(offer_row)
            await schedule_action(
                session,
                organization_id=organization_id,
                owner_module="queue",
                action_type="waitlist.expire_slot_offer",
                action_version=1,
                subject_kind="SlotOffer",
                subject_id=offer.id,
                dedupe_key=f"slot-offer-expiry:{offer.id}",
                execute_at=offer.expires_at,
                payload={
                    "slot_offer_id": str(offer.id),
                    "expected_revision": offer.revision,
                    "principal_id": str(principal_id),
                },
                max_attempts=8,
            )
            await self._notification.create_slot_offer_notification(
                session,
                organization_id=organization_id,
                recipient_party_id=cast(UUID, candidate["subject_party_id"]),
                slot_offer_id=offer.id,
                slot_opportunity_id=offer.slot_opportunity_id,
                start_at=start_at,
                end_at=cast(datetime, opportunity["end_at"]),
                expires_at=offer.expires_at,
            )
            await append_audit(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                command_name="waitlist.offer_next_candidate",
                aggregate_kind="SlotOffer",
                aggregate_id=offer.id,
                idempotency_id=idempotency_id,
                details={
                    "slot_opportunity_id": str(offer.slot_opportunity_id),
                    "waitlist_entry_id": str(offer.waitlist_entry_id),
                    "capacity_hold_id": str(offer.capacity_hold_id),
                    "expires_at": offer.expires_at.isoformat(),
                },
            )
            await append_outbox(
                session,
                organization_id=organization_id,
                event_type="waitlist.slot_offer_created.v1",
                aggregate_kind="SlotOffer",
                aggregate_id=offer.id,
                payload={
                    "slot_offer_id": str(offer.id),
                    "slot_opportunity_id": str(offer.slot_opportunity_id),
                    "waitlist_entry_id": str(offer.waitlist_entry_id),
                    "capacity_hold_id": str(offer.capacity_hold_id),
                    "expires_at": offer.expires_at.isoformat(),
                },
            )
            return offer


async def _lock_opportunity(
    session: AsyncSession,
    organization_id: UUID,
    opportunity_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, location_id,
                           lower(during) AS start_at,
                           upper(during) AS end_at,
                           status, revision
                    FROM request_engine.slot_opportunities
                    WHERE organization_id = :organization_id
                      AND id = :opportunity_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "opportunity_id": opportunity_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SlotOpportunityNotFound(opportunity_id)
    return row


async def _active_offer_for_opportunity(
    session: AsyncSession,
    organization_id: UUID,
    opportunity_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, slot_opportunity_id, waitlist_entry_id,
                           capacity_hold_id, expires_at, status, revision, created_at
                    FROM request_engine.slot_offers
                    WHERE organization_id = :organization_id
                      AND slot_opportunity_id = :opportunity_id
                      AND status = 'offered'
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "opportunity_id": opportunity_id},
            )
        )
        .mappings()
        .first()
    )


async def _read_offer(
    session: AsyncSession,
    organization_id: UUID,
    slot_offer_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT so.id, so.slot_opportunity_id, so.waitlist_entry_id,
                           so.capacity_hold_id, so.expires_at, so.status,
                           so.revision, so.created_at, w.subject_party_id
                    FROM request_engine.slot_offers so
                    JOIN request_engine.waitlist_entries w
                      ON w.organization_id = so.organization_id
                     AND w.id = so.waitlist_entry_id
                    WHERE so.organization_id = :organization_id
                      AND so.id = :slot_offer_id
                    """
                ),
                {"organization_id": organization_id, "slot_offer_id": slot_offer_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SlotOfferNotFound(slot_offer_id)
    return row


async def _lock_offer(
    session: AsyncSession,
    organization_id: UUID,
    slot_offer_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT so.id, so.slot_opportunity_id, so.waitlist_entry_id,
                           so.capacity_hold_id, so.expires_at, so.status,
                           so.revision, so.created_at, w.subject_party_id,
                           clock_timestamp() AS db_now
                    FROM request_engine.slot_offers so
                    JOIN request_engine.waitlist_entries w
                      ON w.organization_id = so.organization_id
                     AND w.id = so.waitlist_entry_id
                    WHERE so.organization_id = :organization_id
                      AND so.id = :slot_offer_id
                    FOR UPDATE OF so
                    """
                ),
                {"organization_id": organization_id, "slot_offer_id": slot_offer_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SlotOfferNotFound(slot_offer_id)
    return row


async def _select_candidate(
    session: AsyncSession,
    *,
    organization_id: UUID,
    opportunity: RowMapping,
    skipped: set[UUID],
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT w.id, w.subject_party_id, w.preferred_resource_id, w.created_at
                    FROM request_engine.waitlist_entries w
                    JOIN request_engine.offering_versions ov
                      ON ov.organization_id = w.organization_id
                     AND ov.offering_id = w.offering_id
                    WHERE w.organization_id = :organization_id
                      AND ov.id = :offering_version_id
                      AND w.status = 'active'
                      AND (
                          w.location_id IS NULL
                          OR w.location_id IS NOT DISTINCT FROM CAST(:location_id AS uuid)
                      )
                      AND (w.earliest_start IS NULL OR w.earliest_start <= :start_at)
                      AND (w.latest_start IS NULL OR w.latest_start >= :start_at)
                      AND NOT (w.id = ANY(CAST(:skipped AS uuid[])))
                      AND NOT EXISTS (
                          SELECT 1
                          FROM request_engine.slot_offers active_offer
                          WHERE active_offer.organization_id = w.organization_id
                            AND active_offer.waitlist_entry_id = w.id
                            AND active_offer.status = 'offered'
                      )
                    ORDER BY w.created_at, w.id
                    FOR UPDATE OF w SKIP LOCKED
                    LIMIT 1
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": opportunity["offering_version_id"],
                    "location_id": opportunity["location_id"],
                    "start_at": opportunity["start_at"],
                    "skipped": [str(value) for value in sorted(skipped, key=str)],
                },
            )
        )
        .mappings()
        .first()
    )


async def _transition_offer(
    session: AsyncSession,
    *,
    organization_id: UUID,
    slot_offer_id: UUID,
    from_status: str,
    to_status: str,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.slot_offers
                    SET status = :to_status,
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :slot_offer_id
                      AND status = :from_status
                    RETURNING id, slot_opportunity_id, waitlist_entry_id,
                              capacity_hold_id, expires_at, status, revision, created_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "slot_offer_id": slot_offer_id,
                    "from_status": from_status,
                    "to_status": to_status,
                },
            )
        )
        .mappings()
        .one()
    )


async def _close_opportunity(
    session: AsyncSession,
    organization_id: UUID,
    opportunity_id: UUID,
    status: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.slot_opportunities
            SET status = :status,
                revision = revision + 1,
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND id = :opportunity_id
              AND status = 'open'
            """
        ),
        {"organization_id": organization_id, "opportunity_id": opportunity_id, "status": status},
    )


async def _cancel_expiry_action(
    session: AsyncSession,
    organization_id: UUID,
    slot_offer_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.scheduled_actions
            SET status = 'cancelled',
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND dedupe_key = :dedupe_key
              AND status = 'pending'
            """
        ),
        {"organization_id": organization_id, "dedupe_key": f"slot-offer-expiry:{slot_offer_id}"},
    )


def _ensure_offer_revision(row: RowMapping, offer_id: UUID, expected_revision: int) -> None:
    actual = cast(int, row["revision"])
    if actual != expected_revision:
        raise SlotOfferRevisionConflict(offer_id, expected_revision, actual)


def _offer_from_row(row: RowMapping) -> SlotOffer:
    return SlotOffer(
        id=cast(UUID, row["id"]),
        slot_opportunity_id=cast(UUID, row["slot_opportunity_id"]),
        waitlist_entry_id=cast(UUID, row["waitlist_entry_id"]),
        capacity_hold_id=cast(UUID, row["capacity_hold_id"]),
        expires_at=cast(datetime, row["expires_at"]),
        status=SlotOfferStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
    )


def _offer_to_json(offer: SlotOffer) -> dict[str, object]:
    return {
        "id": str(offer.id),
        "slot_opportunity_id": str(offer.slot_opportunity_id),
        "waitlist_entry_id": str(offer.waitlist_entry_id),
        "capacity_hold_id": str(offer.capacity_hold_id),
        "expires_at": offer.expires_at.isoformat(),
        "status": offer.status.value,
        "revision": offer.revision,
        "created_at": offer.created_at.isoformat(),
    }


def _offer_from_json(data: dict[str, object]) -> SlotOffer:
    return SlotOffer(
        id=UUID(cast(str, data["id"])),
        slot_opportunity_id=UUID(cast(str, data["slot_opportunity_id"])),
        waitlist_entry_id=UUID(cast(str, data["waitlist_entry_id"])),
        capacity_hold_id=UUID(cast(str, data["capacity_hold_id"])),
        expires_at=datetime.fromisoformat(cast(str, data["expires_at"])),
        status=SlotOfferStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
    )


def _reservation_to_json(reservation: Reservation) -> dict[str, object]:
    return {
        "id": str(reservation.id),
        "offering_version_id": str(reservation.offering_version_id),
        "subject_party_id": str(reservation.subject_party_id),
        "location_id": str(reservation.location_id) if reservation.location_id else None,
        "start_at": reservation.start_at.isoformat(),
        "end_at": reservation.end_at.isoformat(),
        "status": reservation.status.value,
        "revision": reservation.revision,
        "attendance_status": reservation.attendance_status.value,
    }


def _reservation_from_json(data: dict[str, object]) -> Reservation:
    from request_engine.modules.booking.contracts.appointments import (
        AttendanceStatus,
        ReservationStatus,
    )

    location_raw = cast(str | None, data["location_id"])
    return Reservation(
        id=UUID(cast(str, data["id"])),
        offering_version_id=UUID(cast(str, data["offering_version_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        location_id=UUID(location_raw) if location_raw else None,
        start_at=datetime.fromisoformat(cast(str, data["start_at"])),
        end_at=datetime.fromisoformat(cast(str, data["end_at"])),
        status=ReservationStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
        attendance_status=AttendanceStatus(cast(str, data["attendance_status"])),
    )


def _resolution_to_json(result: SlotOfferResolution) -> dict[str, object]:
    return {
        "offer": _offer_to_json(result.offer),
        "next_offer": _offer_to_json(result.next_offer) if result.next_offer is not None else None,
    }


def _resolution_from_json(data: dict[str, object]) -> SlotOfferResolution:
    next_raw = cast(dict[str, object] | None, data["next_offer"])
    return SlotOfferResolution(
        offer=_offer_from_json(cast(dict[str, object], data["offer"])),
        next_offer=_offer_from_json(next_raw) if next_raw is not None else None,
    )
