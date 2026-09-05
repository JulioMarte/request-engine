from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

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

from .contextual_booking_support import (
    ContextualTenantFixture,
    contextual_book_command,
    contextual_slot_at,
    create_contextual_tenant,
    uuid_row,
)

PgConnection = Connection[Any]


def _shared_root(conn: PgConnection) -> UUID:
    identity_id = uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", "slot-offer fallback shared professional"),
    )
    return uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", "slot-offer fallback serialization"),
    )


def _bind_resource(
    conn: PgConnection,
    fixture: ContextualTenantFixture,
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


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_offer_retries_free_resource_after_hidden_shared_root_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = create_contextual_tenant(admin_conn, "fallback-a", resource_count=2)
    tenant_b = create_contextual_tenant(admin_conn, "fallback-b")
    root_id = _shared_root(admin_conn)

    ordered_resources = tuple(sorted((resource.resource_id for resource in tenant_a.resources), key=str))
    blocked_resource, free_resource = ordered_resources
    foreign_resource = tenant_b.resources[0].resource_id
    _bind_resource(admin_conn, tenant_a, blocked_resource, root_id)
    _bind_resource(admin_conn, tenant_b, foreign_resource, root_id)

    reservations = CapacitySafeReservationCommands(session_factory)
    waitlist = PostgresWaitlistCommands(session_factory)
    slot_commands = PostgresSlotOfferCommands(
        session_factory,
        capacity=CapacitySafeSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    start_at = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)

    foreign_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=foreign_resource,
        start_at=start_at,
    )
    await book_appointment(
        reservations,
        contextual_book_command(
            tenant_b,
            foreign_slot,
            key_prefix="fallback-foreign-book",
        ),
    )
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
