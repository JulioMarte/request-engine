from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.create_slot_opportunity import (
    CreateSlotOpportunityCommand,
    create_slot_opportunity,
)
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.platform.db.session import SessionFactory

from . import test_cross_tenant_shared_capacity as shared_capacity_support
from .test_cross_tenant_shared_capacity import PgConnection, TenantBookingFixture

support = cast(Any, shared_capacity_support)


def _bind_resource(
    conn: PgConnection,
    fixture: TenantBookingFixture,
    resource_id: UUID,
    root_id: UUID,
) -> None:
    conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            resource_id,
            root_id,
            "test.control-plane",
            "slot-offer alternate-resource proof",
        ),
    )


def _add_alternate_resource(conn: PgConnection, fixture: TenantBookingFixture) -> UUID:
    capability_row = conn.execute(
        """
        SELECT capability_id
        FROM request_engine.offering_resource_requirements
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.requirement_id),
    ).fetchone()
    assert capability_row is not None
    capability_id = cast(UUID, capability_row[0])
    resource_row = conn.execute(
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.location_id,
            f"alternate-{uuid4().hex}",
            "Alternate provider",
        ),
    ).fetchone()
    assert resource_row is not None
    resource_id = cast(UUID, resource_row[0])
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (fixture.organization_id, resource_id, capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (fixture.organization_id, resource_id),
    )
    return resource_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_offer_retries_free_resource_after_hidden_shared_root_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = support._fixture(admin_conn, "fallback-a")
    tenant_b = support._fixture(admin_conn, "fallback-b")
    alternate_id = _add_alternate_resource(admin_conn, tenant_a)
    root_id = support._shared_root(admin_conn)

    ordered_resources = tuple(
        cast(UUID, row[0])
        for row in admin_conn.execute(
            """
            SELECT r.id
            FROM request_engine.resources r
            JOIN request_engine.resource_capability_assignments a
              ON a.organization_id = r.organization_id
             AND a.resource_id = r.id
            JOIN request_engine.offering_resource_requirements rr
              ON rr.organization_id = a.organization_id
             AND rr.capability_id = a.capability_id
            WHERE r.organization_id = %s
              AND rr.id = %s
            ORDER BY r.id
            """,
            (tenant_a.organization_id, tenant_a.requirement_id),
        ).fetchall()
    )
    assert set(ordered_resources) == {tenant_a.resource_id, alternate_id}
    blocked_resource, free_resource = ordered_resources

    _bind_resource(admin_conn, tenant_a, blocked_resource, root_id)
    _bind_resource(admin_conn, tenant_b, tenant_b.resource_id, root_id)

    reservations = CapacitySafeReservationCommands(session_factory)
    waitlist = PostgresWaitlistCommands(session_factory)
    slot_commands = PostgresSlotOfferCommands(
        session_factory,
        capacity=CapacitySafeSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    start_at = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)

    await book_appointment(reservations, support._book(tenant_b, start_at))
    entry = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_id=tenant_a.offering_id,
            subject_party_id=tenant_a.subject_party_id,
            location_id=tenant_a.location_id,
            preferred_resource_id=None,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"join-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    opportunity = await create_slot_opportunity(
        waitlist,
        CreateSlotOpportunityCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_version_id=tenant_a.offering_version_id,
            location_id=tenant_a.location_id,
            source_event_id=uuid4(),
            start_at=start_at,
            end_at=end_at,
            idempotency_key=f"opportunity-{uuid4().hex}",
        ),
    )

    offer = await offer_next_waitlist_candidate(
        slot_commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            slot_opportunity_id=opportunity.id,
            offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"offer-{uuid4().hex}",
        ),
    )
    assert offer is not None
    assert offer.waitlist_entry_id == entry.id

    claim_rows = admin_conn.execute(
        """
        SELECT c.resource_id
        FROM request_engine.capacity_claims c
        WHERE c.organization_id = %s
          AND c.hold_id = %s
          AND c.status = 'active'
        """,
        (tenant_a.organization_id, offer.capacity_hold_id),
    ).fetchall()
    assert claim_rows == [(free_resource,)]

    stale = admin_conn.execute(
        """
        SELECT
            (SELECT count(*) FROM request_engine.capacity_holds
              WHERE organization_id = %s AND during = tstzrange(%s, %s, '[)')),
            (SELECT count(*) FROM request_engine.capacity_claims
              WHERE organization_id = %s AND during = tstzrange(%s, %s, '[)'))
        """,
        (
            tenant_a.organization_id,
            start_at,
            end_at,
            tenant_a.organization_id,
            start_at,
            end_at,
        ),
    ).fetchone()
    assert stale == (1, 1)
