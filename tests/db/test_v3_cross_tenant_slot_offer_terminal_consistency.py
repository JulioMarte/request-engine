from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class Fixture:
    organization_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> Fixture:
    suffix = uuid4().hex
    organization_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"slot-offer-terminal-{suffix}", f"SlotOffer terminal {suffix}"),
    )
    subject_party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Terminal subject') RETURNING id
        """,
        (organization_id,),
    )
    offering_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'Consult') RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true) RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Provider') RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    requirement_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Provider', 'exclusive', 1) RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    return Fixture(
        organization_id=organization_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        subject_party_id=subject_party_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _offered_graph(conn: PgConnection, fixture: Fixture) -> tuple[UUID, UUID, UUID, UUID]:
    waitlist_entry_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id
        ) VALUES (%s, %s, %s) RETURNING id
        """,
        (fixture.organization_id, fixture.offering_id, fixture.subject_party_id),
    )
    opportunity_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                      '2030-08-01T14:30:00+00'::timestamptz, '[)')
        ) RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, uuid4()),
    )
    with conn.transaction():
        hold_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id,
                during, expires_at
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                          '2030-08-01T14:30:00+00'::timestamptz, '[)'),
                clock_timestamp() + interval '1 hour'
            ) RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.subject_party_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, hold_id,
                during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                          '2030-08-01T14:30:00+00'::timestamptz, '[)'), 1
            )
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                hold_id,
            ),
        )

    # Offer expiry may be stricter than Hold expiry; it just may not outlive it.
    offer_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '5 minutes')
        RETURNING id
        """,
        (fixture.organization_id, opportunity_id, waitlist_entry_id, hold_id),
    )
    conn.commit()
    return offer_id, hold_id, opportunity_id, waitlist_entry_id


def _promote_hold_to_reservation(
    conn: PgConnection,
    fixture: Fixture,
    hold_id: UUID,
) -> UUID:
    reservation_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id, during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                      '2030-08-01T14:30:00+00'::timestamptz, '[)')
        ) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.subject_party_id,
        ),
    )
    conn.execute(
        """
        UPDATE request_engine.capacity_claims
        SET reservation_id = %s
        WHERE organization_id = %s AND hold_id = %s AND status = 'active'
        """,
        (reservation_id, fixture.organization_id, hold_id),
    )
    conn.execute(
        """
        UPDATE request_engine.capacity_holds
        SET status = 'consumed', revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, hold_id),
    )
    return reservation_id


@pytest.mark.postgres
def test_accepted_slot_offer_rejects_incomplete_queue_terminal_state(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn)
    offer_id, hold_id, _, _ = _offered_graph(admin_conn, fixture)

    with pytest.raises(Error) as rejected, admin_conn.transaction():
        _promote_hold_to_reservation(admin_conn, fixture, hold_id)
        admin_conn.execute(
            """
            UPDATE request_engine.slot_offers
            SET status = 'accepted', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, offer_id),
        )

    assert rejected.value.sqlstate == "23514"
    assert "filled Opportunity and fulfilled WaitlistEntry" in str(rejected.value)

    state = admin_conn.execute(
        """
        SELECT so.status, h.status
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id
         AND h.id = so.capacity_hold_id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (fixture.organization_id, offer_id),
    ).fetchone()
    assert state == ("offered", "active")


@pytest.mark.postgres
def test_accepted_slot_offer_requires_real_hold_to_reservation_promotion(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn)
    offer_id, hold_id, opportunity_id, waitlist_entry_id = _offered_graph(admin_conn, fixture)

    with pytest.raises(Error) as rejected, admin_conn.transaction():
        # Satisfy the pre-existing terminal-Hold invariant without fabricating a
        # Reservation: retire the Hold claim, then forge the Queue terminal rows.
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp()
            WHERE organization_id = %s AND hold_id = %s
            """,
            (fixture.organization_id, hold_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_holds
            SET status = 'consumed', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, hold_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.slot_opportunities
            SET status = 'filled', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, opportunity_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.waitlist_entries
            SET status = 'fulfilled', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, waitlist_entry_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.slot_offers
            SET status = 'accepted', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, offer_id),
        )

    assert rejected.value.sqlstate == "23514"
    assert "complete Hold-to-Reservation claim promotion" in str(rejected.value)
