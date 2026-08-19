# pyright: reportPrivateUsage=false

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.platform.db.session import SessionFactory

from .test_slot_offer_recovery import _fixture, _prepare

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i36_waitlist_entry_alone_never_consumes_capacity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    waitlist = PostgresWaitlistCommands(session_factory)

    entry = await join_waitlist(
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
            idempotency_key=f"i36-join-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )

    assert entry.subject_party_id == fixture.first_subject_id
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_holds
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i37_slot_opportunity_revalidates_booking_capacity_before_offer(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, _first_entry_id, _second_entry_id = await _prepare(
        fixture,
        session_factory,
    )
    assert isinstance(commands, PostgresSlotOfferCommands)

    requirement_row = admin_conn.execute(
        """
        SELECT id, quantity
        FROM request_engine.offering_resource_requirements
        WHERE organization_id = %s
          AND offering_version_id = %s
        ORDER BY ordinal
        """,
        (fixture.organization_id, fixture.offering_version_id),
    ).fetchone()
    assert requirement_row is not None
    requirement_id = cast(UUID, requirement_row[0])
    quantity = cast(int, requirement_row[1])

    # The SlotOpportunity already exists. Occupy the exact Resource afterwards.
    # If Queue treated the Opportunity as capacity authority it could still issue
    # an offer; Booking's hold acquisition must instead re-read live capacity.
    with admin_conn.transaction():
        competing_hold_row = admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id,
                offering_version_id,
                subject_party_id,
                location_id,
                during,
                expires_at
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange(%s, %s, '[)'),
                clock_timestamp() + interval '10 minutes'
            )
            RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.second_subject_id,
                fixture.location_id,
                fixture.start_at,
                fixture.end_at,
            ),
        ).fetchone()
        assert competing_hold_row is not None
        competing_hold_id = cast(UUID, competing_hold_row[0])
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id,
                resource_id,
                requirement_id,
                hold_id,
                during,
                quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange(%s, %s, '[)'),
                %s
            )
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                requirement_id,
                competing_hold_id,
                fixture.start_at,
                fixture.end_at,
                quantity,
            ),
        )

    offer = await offer_next_waitlist_candidate(
        commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_opportunity_id=opportunity_id,
            offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"i37-offer-{uuid4().hex}",
        ),
    )

    assert offer is None
    assert admin_conn.execute(
        """
        SELECT status
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone() == ("closed",)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.slot_offers
        WHERE organization_id = %s AND slot_opportunity_id = %s
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT status
        FROM request_engine.capacity_holds
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, competing_hold_id),
    ).fetchone() == ("active",)
