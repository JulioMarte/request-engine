import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from psycopg.errors import CheckViolation

from request_engine.modules.booking.adapters.db.slot_offer_capacity import (
    PostgresSlotOfferCapacity,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
    accept_slot_offer,
)
from request_engine.modules.queue.application.commands.create_slot_opportunity import (
    CreateSlotOpportunityCommand,
    create_slot_opportunity,
)
from request_engine.modules.queue.application.commands.decline_slot_offer import (
    DeclineSlotOfferCommand,
    decline_slot_offer,
)
from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
    expire_slot_offer,
)
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.modules.queue.contracts.waitlist import SlotOfferStatus
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class SlotRecoveryFixture:
    organization_id: UUID
    principal_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    location_id: UUID
    resource_id: UUID
    first_subject_id: UUID
    second_subject_id: UUID
    start_at: datetime
    end_at: datetime


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _party(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, label),
    )


def _fixture(conn: PgConnection) -> SlotRecoveryFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"slot-recovery-{suffix}", f"Slot Recovery {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    first_subject_id = _party(conn, organization_id, f"First {suffix}")
    second_subject_id = _party(conn, organization_id, f"Second {suffix}")
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Doctor')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Doctor', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id),
    )
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    return SlotRecoveryFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        location_id=location_id,
        resource_id=resource_id,
        first_subject_id=first_subject_id,
        second_subject_id=second_subject_id,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )


async def _prepare(
    fixture: SlotRecoveryFixture,
    session_factory: SessionFactory,
) -> tuple[PostgresSlotOfferCommands, UUID, UUID, UUID]:
    waitlist = PostgresWaitlistCommands(session_factory)
    first = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_id=fixture.offering_id,
            subject_party_id=fixture.first_subject_id,
            location_id=fixture.location_id,
            preferred_resource_id=None,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"join-first-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    second = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_id=fixture.offering_id,
            subject_party_id=fixture.second_subject_id,
            location_id=fixture.location_id,
            preferred_resource_id=None,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"join-second-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    opportunity = await create_slot_opportunity(
        waitlist,
        CreateSlotOpportunityCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            source_event_id=uuid4(),
            start_at=fixture.start_at,
            end_at=fixture.end_at,
            idempotency_key=f"opportunity-{uuid4().hex}",
        ),
    )
    commands = PostgresSlotOfferCommands(
        session_factory,
        capacity=PostgresSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    return commands, opportunity.id, first.id, second.id


def _offer_command(
    fixture: SlotRecoveryFixture,
    opportunity_id: UUID,
    *,
    key: str,
) -> OfferNextWaitlistCandidateCommand:
    return OfferNextWaitlistCandidateCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        slot_opportunity_id=opportunity_id,
        offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_offer_creation_is_atomic_and_fifo(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, _ = await _prepare(fixture, session_factory)
    offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(fixture, opportunity_id, key=f"offer-{uuid4().hex}"),
    )
    assert offer is not None
    assert offer.waitlist_entry_id == first_entry_id
    assert offer.status is SlotOfferStatus.OFFERED

    graph = admin_conn.execute(
        """
        SELECT so.status, h.status, h.expires_at = so.expires_at,
               sa.status, ct.status, ct.purpose
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id
         AND h.id = so.capacity_hold_id
        JOIN request_engine.scheduled_actions sa
          ON sa.organization_id = so.organization_id
         AND sa.subject_kind = 'SlotOffer'
         AND sa.subject_id = so.id
        JOIN request_engine.communication_tasks ct
          ON ct.organization_id = so.organization_id
         AND ct.source_kind = 'SlotOffer'
         AND ct.source_id = so.id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone()
    assert graph == ("offered", "active", True, "pending", "pending", "slot_offer_available")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_decline_releases_hold_and_advances_fifo(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, second_entry_id = await _prepare(
        fixture, session_factory
    )
    first_offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(fixture, opportunity_id, key=f"offer-{uuid4().hex}"),
    )
    assert first_offer is not None
    assert first_offer.waitlist_entry_id == first_entry_id
    result = await decline_slot_offer(
        commands,
        DeclineSlotOfferCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_offer_id=first_offer.id,
            expected_revision=first_offer.revision,
            idempotency_key=f"decline-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    assert result.offer.status is SlotOfferStatus.DECLINED
    assert result.next_offer is not None
    assert result.next_offer.waitlist_entry_id == second_entry_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_accept_promotes_hold_and_fills_all_authoritative_state(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, _ = await _prepare(fixture, session_factory)
    offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(fixture, opportunity_id, key=f"offer-{uuid4().hex}"),
    )
    assert offer is not None
    accepted = await accept_slot_offer(
        commands,
        AcceptSlotOfferCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_offer_id=offer.id,
            expected_revision=offer.revision,
            idempotency_key=f"accept-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    assert accepted.offer.status is SlotOfferStatus.ACCEPTED
    assert accepted.reservation.subject_party_id == fixture.first_subject_id
    assert first_entry_id == offer.waitlist_entry_id
    state = admin_conn.execute(
        """
        SELECT so.status, o.status, w.status, h.status,
               cc.reservation_id = %s, ct.status, sa.status
        FROM request_engine.slot_offers so
        JOIN request_engine.slot_opportunities o
          ON o.organization_id = so.organization_id AND o.id = so.slot_opportunity_id
        JOIN request_engine.waitlist_entries w
          ON w.organization_id = so.organization_id AND w.id = so.waitlist_entry_id
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id AND h.id = so.capacity_hold_id
        JOIN request_engine.capacity_claims cc
          ON cc.organization_id = so.organization_id
         AND cc.hold_id = so.capacity_hold_id AND cc.status = 'active'
        JOIN request_engine.communication_tasks ct
          ON ct.organization_id = so.organization_id
         AND ct.source_kind = 'SlotOffer' AND ct.source_id = so.id
        JOIN request_engine.scheduled_actions sa
          ON sa.organization_id = so.organization_id
         AND sa.subject_kind = 'SlotOffer' AND sa.subject_id = so.id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (accepted.reservation.id, fixture.organization_id, offer.id),
    ).fetchone()
    assert state == ("accepted", "filled", "fulfilled", "consumed", True, "cancelled", "cancelled")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_two_offer_workers_serialize_to_one_active_offer(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, _ = await _prepare(fixture, session_factory)
    first, second = await asyncio.gather(
        offer_next_waitlist_candidate(
            commands,
            _offer_command(fixture, opportunity_id, key=f"worker-a-{uuid4().hex}"),
        ),
        offer_next_waitlist_candidate(
            commands,
            _offer_command(fixture, opportunity_id, key=f"worker-b-{uuid4().hex}"),
        ),
    )
    assert first is not None and second is not None
    assert first.id == second.id
    assert first.waitlist_entry_id == first_entry_id
    count = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.slot_offers
        WHERE organization_id = %s AND slot_opportunity_id = %s AND status = 'offered'
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone()
    assert count == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_expiry_releases_hold_and_advances_candidate(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, second_entry_id = await _prepare(
        fixture, session_factory
    )
    offer = await offer_next_waitlist_candidate(
        commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_opportunity_id=opportunity_id,
            offer_expires_at=datetime.now(UTC) + timedelta(seconds=1),
            idempotency_key=f"short-offer-{uuid4().hex}",
        ),
    )
    assert offer is not None and offer.waitlist_entry_id == first_entry_id
    await asyncio.sleep(1.1)
    result = await expire_slot_offer(
        commands,
        ExpireSlotOfferCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_offer_id=offer.id,
            expected_revision=offer.revision,
            idempotency_key=f"expire-{uuid4().hex}",
        ),
    )
    assert result.offer.status is SlotOfferStatus.EXPIRED
    assert result.next_offer is not None
    assert result.next_offer.waitlist_entry_id == second_entry_id


@pytest.mark.integration
@pytest.mark.postgres
def test_database_rejects_offer_hold_graph_mismatch(admin_conn: PgConnection) -> None:
    fixture = _fixture(admin_conn)
    wrong_subject = _party(admin_conn, fixture.organization_id, "Wrong subject")
    waitlist_entry_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id, location_id
        ) VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_id,
            fixture.first_subject_id,
            fixture.location_id,
        ),
    )
    opportunity_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, location_id, source_event_id, during
        ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)')) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.location_id,
            uuid4(),
            fixture.start_at,
            fixture.end_at,
        ),
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    hold_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id, offering_version_id, subject_party_id,
            location_id, during, expires_at
        ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), %s) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            wrong_subject,
            fixture.location_id,
            fixture.start_at,
            fixture.end_at,
            expires_at,
        ),
    )
    with (
        pytest.raises(CheckViolation, match="Hold subject does not match"),
        admin_conn.transaction(),
    ):
        admin_conn.execute(
            """
                INSERT INTO request_engine.slot_offers (
                    organization_id, slot_opportunity_id, waitlist_entry_id,
                    capacity_hold_id, expires_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
            (
                fixture.organization_id,
                opportunity_id,
                waitlist_entry_id,
                hold_id,
                expires_at,
            ),
        )
