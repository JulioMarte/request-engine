from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.reservation_commands import (
    load_bookable_offering,
    load_locked_profiles,
    load_requirements,
    lock_resource_ids,
    lock_resources,
    read_reservation,
    reservation_from_json,
    reservation_to_json,
    revalidate_exact_slot,
    validate_resource_capabilities,
)
from request_engine.modules.booking.application.waitlist import (
    AcceptSlotOfferCommand,
    CreateSlotOpportunityCommand,
    DeclineSlotOfferCommand,
    ExpireSlotOfferCommand,
    JoinWaitlistCommand,
    LeaveWaitlistCommand,
    OfferNextWaitlistCandidateCommand,
)
from request_engine.modules.booking.application.waitlist_errors import (
    ActiveSlotOfferExists,
    NoEligibleWaitlistCandidate,
    SlotOfferExpired,
    SlotOfferNotActive,
    SlotOfferNotFound,
    SlotOpportunityNotFound,
    SlotOpportunityNotOpen,
    SlotOpportunitySourceInvalid,
    WaitlistEntryNotActive,
    WaitlistEntryNotFound,
)
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.waitlist import (
    AcceptedSlotOffer,
    SlotOffer,
    SlotOfferStatus,
    SlotOpportunity,
    SlotOpportunityStatus,
    WaitlistEntry,
    WaitlistEntryStatus,
)
from request_engine.modules.booking.domain.policy import slot_step_minutes
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresWaitlistCommands:
    """Deep transactional executor for released appointment-capacity recovery.

    Waitlist/SlotOpportunity/SlotOffer are booking-owned because acceptance must
    atomically promote a booking CapacityHold into a Reservation while closing the
    standby coordination state. No network I/O occurs in these transactions.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def join_waitlist(self, command: JoinWaitlistCommand) -> WaitlistEntry:
        capability = "waitlist.join"
        fingerprint = command_fingerprint(
            capability,
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
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _waitlist_entry_from_json(cast(dict[str, object], replay["entry"]))

            await _validate_waitlist_scope(session, command)
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
                            RETURNING id, offering_id, subject_party_id, location_id,
                                      preferred_resource_id, earliest_start, latest_start,
                                      status, created_at, revision
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
            entry = _waitlist_entry_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="WaitlistEntry",
                aggregate_id=entry.id,
                idempotency_id=idempotency_id,
                details={"offering_id": str(entry.offering_id)},
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
                session, idempotency_id, {"entry": _waitlist_entry_to_json(entry)}
            )
            return entry

    async def leave_waitlist(self, command: LeaveWaitlistCommand) -> WaitlistEntry:
        capability = "waitlist.leave"
        fingerprint = command_fingerprint(
            capability, {"waitlist_entry_id": command.waitlist_entry_id}
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _waitlist_entry_from_json(cast(dict[str, object], replay["entry"]))

            # PLAN before locking so an active offer can preserve canonical order:
            # SlotOpportunity -> SlotOffer -> WaitlistEntry -> CapacityHold -> Resources.
            offer_plan = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT so.id AS offer_id, so.slot_opportunity_id, so.capacity_hold_id
                            FROM request_engine.slot_offers so
                            WHERE so.organization_id = :organization_id
                              AND so.waitlist_entry_id = :entry_id
                              AND so.status = 'offered'
                            ORDER BY so.created_at, so.id
                            LIMIT 1
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

            if offer_plan is not None:
                await _lock_opportunity(
                    session,
                    command.organization_id,
                    cast(UUID, offer_plan["slot_opportunity_id"]),
                )
                offer = await _lock_offer(
                    session,
                    command.organization_id,
                    cast(UUID, offer_plan["offer_id"]),
                )
                entry = await _lock_waitlist_entry(
                    session, command.organization_id, command.waitlist_entry_id
                )
                _require_active_entry(entry)
                hold = await _lock_hold(
                    session, command.organization_id, cast(UUID, offer["capacity_hold_id"])
                )
                resource_ids = await _active_hold_resource_ids(
                    session, command.organization_id, cast(UUID, hold["id"])
                )
                await lock_resource_ids(session, command.organization_id, resource_ids)
                await _release_hold(
                    session,
                    organization_id=command.organization_id,
                    hold_id=cast(UUID, hold["id"]),
                    terminal_status="released",
                )
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.slot_offers
                        SET status = 'cancelled', revision = revision + 1
                        WHERE organization_id = :organization_id
                          AND id = :offer_id
                          AND status = 'offered'
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "offer_id": cast(UUID, offer["id"]),
                    },
                )
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="slot_offer.cancelled.v1",
                    aggregate_kind="SlotOpportunity",
                    aggregate_id=cast(UUID, offer["slot_opportunity_id"]),
                    payload={
                        "slot_offer_id": str(offer["id"]),
                        "reason": "waitlist_left",
                    },
                )
            else:
                entry = await _lock_waitlist_entry(
                    session, command.organization_id, command.waitlist_entry_id
                )
                _require_active_entry(entry)

            await session.execute(
                text(
                    """
                    UPDATE request_engine.waitlist_entries
                    SET status = 'cancelled', revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :entry_id
                      AND status = 'active'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "entry_id": command.waitlist_entry_id,
                },
            )
            updated = await _read_waitlist_entry(
                session, command.organization_id, command.waitlist_entry_id
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="WaitlistEntry",
                aggregate_id=updated.id,
                idempotency_id=idempotency_id,
                details={},
            )
            await complete_idempotency(
                session, idempotency_id, {"entry": _waitlist_entry_to_json(updated)}
            )
            return updated

    async def create_slot_opportunity(
        self, command: CreateSlotOpportunityCommand
    ) -> SlotOpportunity:
        capability = "waitlist.create_opportunity"
        fingerprint = command_fingerprint(
            capability,
            {
                "source_event_id": command.source_event_id,
                "source_reservation_id": command.source_reservation_id,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _opportunity_from_json(cast(dict[str, object], replay["opportunity"]))

            source = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, offering_version_id, location_id,
                                   lower(during) AS start_at, upper(during) AS end_at, status
                            FROM request_engine.reservations
                            WHERE organization_id = :organization_id
                              AND id = :reservation_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "reservation_id": command.source_reservation_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if source is None or source["status"] != "cancelled":
                raise SlotOpportunitySourceInvalid(command.source_reservation_id)

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
                            ON CONFLICT (organization_id, source_event_id) DO UPDATE
                               SET source_event_id = EXCLUDED.source_event_id
                            RETURNING id, offering_version_id, location_id,
                                      source_reservation_id, source_event_id,
                                      lower(during) AS start_at, upper(during) AS end_at,
                                      status, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": source["offering_version_id"],
                            "location_id": source["location_id"],
                            "source_reservation_id": command.source_reservation_id,
                            "source_event_id": command.source_event_id,
                            "start_at": source["start_at"],
                            "end_at": source["end_at"],
                        },
                    )
                )
                .mappings()
                .one()
            )
            opportunity = _opportunity_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="SlotOpportunity",
                aggregate_id=opportunity.id,
                idempotency_id=idempotency_id,
                details={"source_reservation_id": str(command.source_reservation_id)},
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"opportunity": _opportunity_to_json(opportunity)},
            )
            return opportunity

    async def offer_next_waitlist_candidate(
        self, command: OfferNextWaitlistCandidateCommand
    ) -> SlotOffer:
        capability = "waitlist.offer_next"
        fingerprint = command_fingerprint(
            capability,
            {
                "slot_opportunity_id": command.slot_opportunity_id,
                "expires_at": command.expires_at,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _slot_offer_from_json(cast(dict[str, object], replay["offer"]))

            opportunity = await _lock_opportunity(
                session, command.organization_id, command.slot_opportunity_id
            )
            _require_open_opportunity(opportunity)
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM request_engine.slot_offers
                        WHERE organization_id = :organization_id
                          AND slot_opportunity_id = :opportunity_id
                          AND status = 'offered'
                        LIMIT 1
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "opportunity_id": command.slot_opportunity_id,
                    },
                )
            ).first()
            if existing is not None:
                raise ActiveSlotOfferExists(command.slot_opportunity_id)

            now = cast(
                datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            )
            if command.expires_at <= now:
                raise ValueError("slot offer expiration must be in the future")

            offering_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            SELECT offering_id
                            FROM request_engine.offering_versions
                            WHERE organization_id = :organization_id
                              AND id = :offering_version_id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": opportunity["offering_version_id"],
                        },
                    )
                ).scalar_one(),
            )
            source_choices = await _released_source_choices(
                session,
                command.organization_id,
                cast(UUID, opportunity["source_reservation_id"]),
            )
            source_resource_ids = {choice.resource_id for choice in source_choices}

            candidate = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT w.id, w.offering_id, w.subject_party_id, w.location_id,
                                   w.preferred_resource_id, w.earliest_start, w.latest_start,
                                   w.status, w.created_at, w.revision
                            FROM request_engine.waitlist_entries w
                            WHERE w.organization_id = :organization_id
                              AND w.offering_id = :offering_id
                              AND w.status = 'active'
                              AND (w.location_id IS NULL OR w.location_id IS NOT DISTINCT FROM :location_id)
                              AND (w.earliest_start IS NULL OR w.earliest_start <= :start_at)
                              AND (w.latest_start IS NULL OR w.latest_start >= :start_at)
                              AND (
                                  w.preferred_resource_id IS NULL
                                  OR w.preferred_resource_id = ANY(CAST(:resource_ids AS uuid[]))
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM request_engine.slot_offers previous
                                  WHERE previous.organization_id = w.organization_id
                                    AND previous.slot_opportunity_id = :opportunity_id
                                    AND previous.waitlist_entry_id = w.id
                              )
                            ORDER BY w.created_at, w.id
                            LIMIT 1
                            FOR UPDATE OF w
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_id": offering_id,
                            "location_id": opportunity["location_id"],
                            "start_at": opportunity["start_at"],
                            "opportunity_id": command.slot_opportunity_id,
                            "resource_ids": [str(value) for value in sorted(source_resource_ids, key=str)],
                        },
                    )
                )
                .mappings()
                .first()
            )
            if candidate is None:
                raise NoEligibleWaitlistCandidate(command.slot_opportunity_id)

            offering = await load_bookable_offering(
                session,
                command.organization_id,
                cast(UUID, opportunity["offering_version_id"]),
            )
            requirements = await load_requirements(
                session,
                command.organization_id,
                cast(UUID, opportunity["offering_version_id"]),
            )
            choices = {choice.requirement_id: choice for choice in source_choices}
            if set(choices) != set(requirements):
                raise SlotOpportunitySourceInvalid(cast(UUID, opportunity["source_reservation_id"]))
            resources = await lock_resources(
                session,
                organization_id=command.organization_id,
                resource_ids=tuple(choice.resource_id for choice in source_choices),
            )
            await validate_resource_capabilities(
                session,
                organization_id=command.organization_id,
                requirements=requirements,
                choices=choices,
                resources=resources,
                location_id=cast(UUID | None, opportunity["location_id"]),
            )
            start_at = cast(datetime, opportunity["start_at"])
            end_at = cast(datetime, opportunity["end_at"])
            profiles = await load_locked_profiles(
                session,
                organization_id=command.organization_id,
                resources=resources,
                start_at=start_at,
                end_at=end_at,
            )
            duration_minutes = cast(int, offering["duration_minutes"])
            revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=profiles,
                start_at=start_at,
                end_at=end_at,
                duration_minutes=duration_minutes,
                step_minutes=slot_step_minutes(
                    cast(dict[str, object], offering["booking_policy"]), duration_minutes
                ),
            )

            hold_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.capacity_holds (
                                organization_id, offering_version_id, subject_party_id,
                                location_id, during, expires_at
                            ) VALUES (
                                :organization_id, :offering_version_id, :subject_party_id,
                                :location_id, tstzrange(:start_at, :end_at, '[)'), :expires_at
                            ) RETURNING id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": opportunity["offering_version_id"],
                            "subject_party_id": candidate["subject_party_id"],
                            "location_id": opportunity["location_id"],
                            "start_at": start_at,
                            "end_at": end_at,
                            "expires_at": command.expires_at,
                        },
                    )
                ).scalar_one(),
            )
            for choice in sorted(source_choices, key=lambda item: str(item.requirement_id)):
                requirement = requirements[choice.requirement_id]
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.capacity_claims (
                            organization_id, resource_id, requirement_id, hold_id, during, quantity
                        ) VALUES (
                            :organization_id, :resource_id, :requirement_id, :hold_id,
                            tstzrange(:start_at, :end_at, '[)'), :quantity
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "resource_id": choice.resource_id,
                        "requirement_id": choice.requirement_id,
                        "hold_id": hold_id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "quantity": requirement.quantity,
                    },
                )

            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.slot_offers (
                                organization_id, slot_opportunity_id, waitlist_entry_id,
                                capacity_hold_id, expires_at
                            ) VALUES (
                                :organization_id, :opportunity_id, :entry_id, :hold_id, :expires_at
                            )
                            RETURNING id, slot_opportunity_id, waitlist_entry_id,
                                      capacity_hold_id, expires_at, status, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "opportunity_id": command.slot_opportunity_id,
                            "entry_id": candidate["id"],
                            "hold_id": hold_id,
                            "expires_at": command.expires_at,
                        },
                    )
                )
                .mappings()
                .one()
            )
            offer = _slot_offer_from_row(row)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="SlotOpportunity",
                aggregate_id=command.slot_opportunity_id,
                idempotency_id=idempotency_id,
                details={
                    "slot_offer_id": str(offer.id),
                    "waitlist_entry_id": str(offer.waitlist_entry_id),
                    "capacity_hold_id": str(offer.capacity_hold_id),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="slot_offer.created.v1",
                aggregate_kind="SlotOpportunity",
                aggregate_id=command.slot_opportunity_id,
                payload={
                    "slot_offer_id": str(offer.id),
                    "waitlist_entry_id": str(offer.waitlist_entry_id),
                    "expires_at": offer.expires_at.isoformat(),
                },
            )
            await complete_idempotency(
                session, idempotency_id, {"offer": _slot_offer_to_json(offer)}
            )
            return offer

    async def accept_slot_offer(self, command: AcceptSlotOfferCommand) -> AcceptedSlotOffer:
        capability = "waitlist.accept_offer"
        fingerprint = command_fingerprint(capability, {"slot_offer_id": command.slot_offer_id})
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return AcceptedSlotOffer(
                    offer=_slot_offer_from_json(cast(dict[str, object], replay["offer"])),
                    reservation=reservation_from_json(
                        cast(dict[str, object], replay["reservation"])
                    ),
                )

            plan = await _read_offer_plan(session, command.organization_id, command.slot_offer_id)
            if plan is None:
                raise SlotOfferNotFound(command.slot_offer_id)
            opportunity = await _lock_opportunity(
                session, command.organization_id, cast(UUID, plan["slot_opportunity_id"])
            )
            _require_open_opportunity(opportunity)
            offer = await _lock_offer(session, command.organization_id, command.slot_offer_id)
            _require_active_offer(offer)
            entry = await _lock_waitlist_entry(
                session, command.organization_id, cast(UUID, offer["waitlist_entry_id"])
            )
            _require_active_entry(entry)
            hold = await _lock_hold(
                session, command.organization_id, cast(UUID, offer["capacity_hold_id"])
            )
            now = cast(
                datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            )
            if cast(datetime, offer["expires_at"]) <= now:
                raise SlotOfferExpired(command.slot_offer_id)
            if hold["status"] != "active" or cast(datetime, hold["expires_at"]) <= now:
                raise SlotOfferExpired(command.slot_offer_id)

            resource_ids = await _active_hold_resource_ids(
                session, command.organization_id, cast(UUID, hold["id"])
            )
            await lock_resource_ids(session, command.organization_id, resource_ids)
            offering = await load_bookable_offering(
                session,
                command.organization_id,
                cast(UUID, hold["offering_version_id"]),
            )
            policy = cast(dict[str, object], offering["booking_policy"])
            reservation_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.reservations (
                                organization_id, offering_version_id, subject_party_id,
                                location_id, during, booking_policy_snapshot
                            ) VALUES (
                                :organization_id, :offering_version_id, :subject_party_id,
                                :location_id, :during, CAST(:booking_policy AS jsonb)
                            ) RETURNING id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": hold["offering_version_id"],
                            "subject_party_id": hold["subject_party_id"],
                            "location_id": hold["location_id"],
                            "during": hold["during"],
                            "booking_policy": json.dumps(policy, separators=(",", ":")),
                        },
                    )
                ).scalar_one(),
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_claims
                    SET reservation_id = :reservation_id
                    WHERE organization_id = :organization_id
                      AND hold_id = :hold_id
                      AND reservation_id IS NULL
                      AND status = 'active'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "hold_id": hold["id"],
                    "reservation_id": reservation_id,
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_holds
                    SET status = 'consumed', revision = revision + 1
                    WHERE organization_id = :organization_id AND id = :hold_id
                    """
                ),
                {"organization_id": command.organization_id, "hold_id": hold["id"]},
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.waitlist_entries
                    SET status = 'fulfilled', revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :entry_id AND status = 'active'
                    """
                ),
                {"organization_id": command.organization_id, "entry_id": entry["id"]},
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.slot_offers
                    SET status = 'accepted', revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :offer_id AND status = 'offered'
                    """
                ),
                {"organization_id": command.organization_id, "offer_id": offer["id"]},
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.slot_opportunities
                    SET status = 'filled', revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :opportunity_id AND status = 'open'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "opportunity_id": opportunity["id"],
                },
            )
            reservation = await read_reservation(
                session, command.organization_id, reservation_id
            )
            accepted_offer = await _read_slot_offer(
                session, command.organization_id, command.slot_offer_id
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="SlotOpportunity",
                aggregate_id=cast(UUID, opportunity["id"]),
                idempotency_id=idempotency_id,
                details={
                    "slot_offer_id": str(command.slot_offer_id),
                    "reservation_id": str(reservation.id),
                    "waitlist_entry_id": str(entry["id"]),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="slot_offer.accepted.v1",
                aggregate_kind="SlotOpportunity",
                aggregate_id=cast(UUID, opportunity["id"]),
                payload={
                    "slot_offer_id": str(command.slot_offer_id),
                    "reservation_id": str(reservation.id),
                    "waitlist_entry_id": str(entry["id"]),
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
                    "offering_version_id": str(reservation.offering_version_id),
                    "subject_party_id": str(reservation.subject_party_id),
                },
            )
            result = AcceptedSlotOffer(offer=accepted_offer, reservation=reservation)
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "offer": _slot_offer_to_json(accepted_offer),
                    "reservation": reservation_to_json(reservation),
                },
            )
            return result

    async def decline_slot_offer(self, command: DeclineSlotOfferCommand) -> SlotOffer:
        return await self._release_offer(
            command=command,
            capability="waitlist.decline_offer",
            offer_status="declined",
            hold_status="released",
            require_expired=False,
        )

    async def expire_slot_offer(self, command: ExpireSlotOfferCommand) -> SlotOffer:
        return await self._release_offer(
            command=command,
            capability="waitlist.expire_offer",
            offer_status="expired",
            hold_status="expired",
            require_expired=True,
        )

    async def _release_offer(
        self,
        *,
        command: DeclineSlotOfferCommand | ExpireSlotOfferCommand,
        capability: str,
        offer_status: str,
        hold_status: str,
        require_expired: bool,
    ) -> SlotOffer:
        fingerprint = command_fingerprint(capability, {"slot_offer_id": command.slot_offer_id})
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _slot_offer_from_json(cast(dict[str, object], replay["offer"]))

            plan = await _read_offer_plan(session, command.organization_id, command.slot_offer_id)
            if plan is None:
                raise SlotOfferNotFound(command.slot_offer_id)
            opportunity = await _lock_opportunity(
                session, command.organization_id, cast(UUID, plan["slot_opportunity_id"])
            )
            _require_open_opportunity(opportunity)
            offer = await _lock_offer(session, command.organization_id, command.slot_offer_id)
            _require_active_offer(offer)
            hold = await _lock_hold(
                session, command.organization_id, cast(UUID, offer["capacity_hold_id"])
            )
            now = cast(
                datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            )
            if require_expired and cast(datetime, offer["expires_at"]) > now:
                raise ValueError("SlotOffer is not due for expiry")

            resource_ids = await _active_hold_resource_ids(
                session, command.organization_id, cast(UUID, hold["id"])
            )
            await lock_resource_ids(session, command.organization_id, resource_ids)
            await _release_hold(
                session,
                organization_id=command.organization_id,
                hold_id=cast(UUID, hold["id"]),
                terminal_status=hold_status,
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.slot_offers
                    SET status = :status, revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :offer_id AND status = 'offered'
                    """
                ),
                {
                    "status": offer_status,
                    "organization_id": command.organization_id,
                    "offer_id": command.slot_offer_id,
                },
            )
            updated = await _read_slot_offer(
                session, command.organization_id, command.slot_offer_id
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="SlotOpportunity",
                aggregate_id=cast(UUID, opportunity["id"]),
                idempotency_id=idempotency_id,
                details={"slot_offer_id": str(command.slot_offer_id)},
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=f"slot_offer.{offer_status}.v1",
                aggregate_kind="SlotOpportunity",
                aggregate_id=cast(UUID, opportunity["id"]),
                payload={"slot_offer_id": str(command.slot_offer_id)},
            )
            await complete_idempotency(
                session, idempotency_id, {"offer": _slot_offer_to_json(updated)}
            )
            return updated


class PostgresWaitlistReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_waitlist_entry(
        self, *, organization_id: UUID, waitlist_entry_id: UUID
    ) -> WaitlistEntry | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = await _read_waitlist_entry_optional(session, organization_id, waitlist_entry_id)
            return _waitlist_entry_from_row(row) if row is not None else None

    async def get_slot_offer(
        self, *, organization_id: UUID, slot_offer_id: UUID
    ) -> SlotOffer | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = await _read_slot_offer_optional(session, organization_id, slot_offer_id)
            return _slot_offer_from_row(row) if row is not None else None


async def _validate_waitlist_scope(session: AsyncSession, command: JoinWaitlistCommand) -> None:
    offering = (
        await session.execute(
            text(
                """
                SELECT active FROM request_engine.offerings
                WHERE organization_id = :organization_id AND id = :offering_id
                """
            ),
            {"organization_id": command.organization_id, "offering_id": command.offering_id},
        )
    ).first()
    if offering is None or offering[0] is not True:
        raise ValueError("waitlist Offering does not exist or is inactive")
    party = (
        await session.execute(
            text(
                """
                SELECT active FROM request_engine.parties
                WHERE organization_id = :organization_id AND id = :party_id
                """
            ),
            {
                "organization_id": command.organization_id,
                "party_id": command.subject_party_id,
            },
        )
    ).first()
    if party is None or party[0] is not True:
        raise ValueError("waitlist subject Party does not exist or is inactive")
    if command.location_id is not None:
        location = (
            await session.execute(
                text(
                    """
                    SELECT active FROM request_engine.locations
                    WHERE organization_id = :organization_id AND id = :location_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "location_id": command.location_id,
                },
            )
        ).first()
        if location is None or location[0] is not True:
            raise ValueError("waitlist Location does not exist or is inactive")
    if command.preferred_resource_id is not None:
        resource = (
            await session.execute(
                text(
                    """
                    SELECT active FROM request_engine.resources
                    WHERE organization_id = :organization_id AND id = :resource_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "resource_id": command.preferred_resource_id,
                },
            )
        ).first()
        if resource is None or resource[0] is not True:
            raise ValueError("preferred Resource does not exist or is inactive")


async def _released_source_choices(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> tuple[ResourceChoice, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT requirement_id, resource_id
                FROM request_engine.capacity_claims
                WHERE organization_id = :organization_id
                  AND reservation_id = :reservation_id
                  AND status = 'released'
                ORDER BY requirement_id, id
                """
            ),
            {"organization_id": organization_id, "reservation_id": reservation_id},
        )
    ).all()
    by_requirement: dict[UUID, ResourceChoice] = {}
    for row in rows:
        requirement_id = cast(UUID, row[0])
        if requirement_id in by_requirement:
            raise SlotOpportunitySourceInvalid(reservation_id)
        by_requirement[requirement_id] = ResourceChoice(
            requirement_id=requirement_id,
            resource_id=cast(UUID, row[1]),
        )
    if not by_requirement:
        raise SlotOpportunitySourceInvalid(reservation_id)
    return tuple(by_requirement[key] for key in sorted(by_requirement, key=str))


async def _lock_opportunity(
    session: AsyncSession, organization_id: UUID, opportunity_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, location_id, source_reservation_id,
                           source_event_id, lower(during) AS start_at,
                           upper(during) AS end_at, status, revision
                    FROM request_engine.slot_opportunities
                    WHERE organization_id = :organization_id AND id = :opportunity_id
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


def _require_open_opportunity(row: RowMapping) -> None:
    if row["status"] != "open":
        raise SlotOpportunityNotOpen(cast(UUID, row["id"]))


async def _read_offer_plan(
    session: AsyncSession, organization_id: UUID, offer_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, slot_opportunity_id, waitlist_entry_id, capacity_hold_id
                    FROM request_engine.slot_offers
                    WHERE organization_id = :organization_id AND id = :offer_id
                    """
                ),
                {"organization_id": organization_id, "offer_id": offer_id},
            )
        )
        .mappings()
        .first()
    )


async def _lock_offer(session: AsyncSession, organization_id: UUID, offer_id: UUID) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, slot_opportunity_id, waitlist_entry_id, capacity_hold_id,
                           expires_at, status, revision
                    FROM request_engine.slot_offers
                    WHERE organization_id = :organization_id AND id = :offer_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "offer_id": offer_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SlotOfferNotFound(offer_id)
    return row


def _require_active_offer(row: RowMapping) -> None:
    if row["status"] != "offered":
        raise SlotOfferNotActive(cast(UUID, row["id"]))


async def _lock_waitlist_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_id, subject_party_id, location_id, preferred_resource_id,
                           earliest_start, latest_start, status, created_at, revision
                    FROM request_engine.waitlist_entries
                    WHERE organization_id = :organization_id AND id = :entry_id
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
    return row


def _require_active_entry(row: RowMapping) -> None:
    if row["status"] != "active":
        raise WaitlistEntryNotActive(cast(UUID, row["id"]))


async def _lock_hold(session: AsyncSession, organization_id: UUID, hold_id: UUID) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, subject_party_id, location_id, during,
                           expires_at, status, revision
                    FROM request_engine.capacity_holds
                    WHERE organization_id = :organization_id AND id = :hold_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "hold_id": hold_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SlotOfferNotActive(hold_id)
    return row


async def _active_hold_resource_ids(
    session: AsyncSession, organization_id: UUID, hold_id: UUID
) -> tuple[UUID, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT resource_id
                FROM request_engine.capacity_claims
                WHERE organization_id = :organization_id
                  AND hold_id = :hold_id
                  AND reservation_id IS NULL
                  AND status = 'active'
                ORDER BY resource_id
                """
            ),
            {"organization_id": organization_id, "hold_id": hold_id},
        )
    ).all()
    result = tuple(cast(UUID, row[0]) for row in rows)
    if not result:
        raise SlotOfferNotActive(hold_id)
    return result


async def _release_hold(
    session: AsyncSession,
    *,
    organization_id: UUID,
    hold_id: UUID,
    terminal_status: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released'
            WHERE organization_id = :organization_id
              AND hold_id = :hold_id
              AND reservation_id IS NULL
              AND status = 'active'
            """
        ),
        {"organization_id": organization_id, "hold_id": hold_id},
    )
    await session.execute(
        text(
            """
            UPDATE request_engine.capacity_holds
            SET status = :status, revision = revision + 1
            WHERE organization_id = :organization_id
              AND id = :hold_id
              AND status = 'active'
            """
        ),
        {
            "status": terminal_status,
            "organization_id": organization_id,
            "hold_id": hold_id,
        },
    )


async def _read_waitlist_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> WaitlistEntry:
    row = await _read_waitlist_entry_optional(session, organization_id, entry_id)
    if row is None:
        raise WaitlistEntryNotFound(entry_id)
    return _waitlist_entry_from_row(row)


async def _read_waitlist_entry_optional(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_id, subject_party_id, location_id, preferred_resource_id,
                           earliest_start, latest_start, status, created_at, revision
                    FROM request_engine.waitlist_entries
                    WHERE organization_id = :organization_id AND id = :entry_id
                    """
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .first()
    )


async def _read_slot_offer(
    session: AsyncSession, organization_id: UUID, offer_id: UUID
) -> SlotOffer:
    row = await _read_slot_offer_optional(session, organization_id, offer_id)
    if row is None:
        raise SlotOfferNotFound(offer_id)
    return _slot_offer_from_row(row)


async def _read_slot_offer_optional(
    session: AsyncSession, organization_id: UUID, offer_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, slot_opportunity_id, waitlist_entry_id, capacity_hold_id,
                           expires_at, status, revision
                    FROM request_engine.slot_offers
                    WHERE organization_id = :organization_id AND id = :offer_id
                    """
                ),
                {"organization_id": organization_id, "offer_id": offer_id},
            )
        )
        .mappings()
        .first()
    )


def _waitlist_entry_from_row(row: RowMapping) -> WaitlistEntry:
    return WaitlistEntry(
        id=cast(UUID, row["id"]),
        offering_id=cast(UUID, row["offering_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        preferred_resource_id=cast(UUID | None, row["preferred_resource_id"]),
        earliest_start=cast(datetime | None, row["earliest_start"]),
        latest_start=cast(datetime | None, row["latest_start"]),
        status=WaitlistEntryStatus(cast(str, row["status"])),
        created_at=cast(datetime, row["created_at"]),
        revision=cast(int, row["revision"]),
    )


def _opportunity_from_row(row: RowMapping) -> SlotOpportunity:
    return SlotOpportunity(
        id=cast(UUID, row["id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        source_reservation_id=cast(UUID | None, row["source_reservation_id"]),
        source_event_id=cast(UUID, row["source_event_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        status=SlotOpportunityStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )


def _slot_offer_from_row(row: RowMapping) -> SlotOffer:
    return SlotOffer(
        id=cast(UUID, row["id"]),
        slot_opportunity_id=cast(UUID, row["slot_opportunity_id"]),
        waitlist_entry_id=cast(UUID, row["waitlist_entry_id"]),
        capacity_hold_id=cast(UUID, row["capacity_hold_id"]),
        expires_at=cast(datetime, row["expires_at"]),
        status=SlotOfferStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )


def _waitlist_entry_to_json(entry: WaitlistEntry) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "offering_id": str(entry.offering_id),
        "subject_party_id": str(entry.subject_party_id),
        "location_id": str(entry.location_id) if entry.location_id else None,
        "preferred_resource_id": (
            str(entry.preferred_resource_id) if entry.preferred_resource_id else None
        ),
        "earliest_start": entry.earliest_start.isoformat() if entry.earliest_start else None,
        "latest_start": entry.latest_start.isoformat() if entry.latest_start else None,
        "status": entry.status.value,
        "created_at": entry.created_at.isoformat(),
        "revision": entry.revision,
    }


def _waitlist_entry_from_json(data: dict[str, object]) -> WaitlistEntry:
    return WaitlistEntry(
        id=UUID(cast(str, data["id"])),
        offering_id=UUID(cast(str, data["offering_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        location_id=UUID(cast(str, data["location_id"])) if data["location_id"] else None,
        preferred_resource_id=(
            UUID(cast(str, data["preferred_resource_id"]))
            if data["preferred_resource_id"]
            else None
        ),
        earliest_start=(
            datetime.fromisoformat(cast(str, data["earliest_start"]))
            if data["earliest_start"]
            else None
        ),
        latest_start=(
            datetime.fromisoformat(cast(str, data["latest_start"]))
            if data["latest_start"]
            else None
        ),
        status=WaitlistEntryStatus(cast(str, data["status"])),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
        revision=cast(int, data["revision"]),
    )


def _opportunity_to_json(opportunity: SlotOpportunity) -> dict[str, object]:
    return {
        "id": str(opportunity.id),
        "offering_version_id": str(opportunity.offering_version_id),
        "location_id": str(opportunity.location_id) if opportunity.location_id else None,
        "source_reservation_id": (
            str(opportunity.source_reservation_id) if opportunity.source_reservation_id else None
        ),
        "source_event_id": str(opportunity.source_event_id),
        "start_at": opportunity.start_at.isoformat(),
        "end_at": opportunity.end_at.isoformat(),
        "status": opportunity.status.value,
        "revision": opportunity.revision,
    }


def _opportunity_from_json(data: dict[str, object]) -> SlotOpportunity:
    return SlotOpportunity(
        id=UUID(cast(str, data["id"])),
        offering_version_id=UUID(cast(str, data["offering_version_id"])),
        location_id=UUID(cast(str, data["location_id"])) if data["location_id"] else None,
        source_reservation_id=(
            UUID(cast(str, data["source_reservation_id"]))
            if data["source_reservation_id"]
            else None
        ),
        source_event_id=UUID(cast(str, data["source_event_id"])),
        start_at=datetime.fromisoformat(cast(str, data["start_at"])),
        end_at=datetime.fromisoformat(cast(str, data["end_at"])),
        status=SlotOpportunityStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
    )


def _slot_offer_to_json(offer: SlotOffer) -> dict[str, object]:
    return {
        "id": str(offer.id),
        "slot_opportunity_id": str(offer.slot_opportunity_id),
        "waitlist_entry_id": str(offer.waitlist_entry_id),
        "capacity_hold_id": str(offer.capacity_hold_id),
        "expires_at": offer.expires_at.isoformat(),
        "status": offer.status.value,
        "revision": offer.revision,
    }


def _slot_offer_from_json(data: dict[str, object]) -> SlotOffer:
    return SlotOffer(
        id=UUID(cast(str, data["id"])),
        slot_opportunity_id=UUID(cast(str, data["slot_opportunity_id"])),
        waitlist_entry_id=UUID(cast(str, data["waitlist_entry_id"])),
        capacity_hold_id=UUID(cast(str, data["capacity_hold_id"])),
        expires_at=datetime.fromisoformat(cast(str, data["expires_at"])),
        status=SlotOfferStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
    )
