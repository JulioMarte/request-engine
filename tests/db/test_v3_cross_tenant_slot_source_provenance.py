from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _sources(conn: PgConnection) -> tuple[UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"source-provenance-{suffix}", f"Source provenance {suffix}"),
    )
    party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Subject') RETURNING id
        """,
        (organization_id,),
    )
    offering_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'Consult') RETURNING id
        """,
        (organization_id, f"offering-{suffix}"),
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
    waitlist_entry_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id,
            earliest_start, latest_start
        ) VALUES (
            %s, %s, %s,
            '2030-09-01T13:00:00+00'::timestamptz,
            '2030-09-01T17:00:00+00'::timestamptz
        ) RETURNING id
        """,
        (organization_id, offering_id, party_id),
    )
    opportunity_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-09-01T14:00:00+00'::timestamptz,
                      '2030-09-01T14:30:00+00'::timestamptz, '[)')
        ) RETURNING id
        """,
        (organization_id, offering_version_id, uuid4()),
    )
    conn.commit()

    # Capacity-owner completeness is a deferred invariant. Construct the Hold
    # and its mandatory claim as one authoritative unit before adding the Offer,
    # matching the canonical fixtures/production transaction boundary.
    with conn.transaction():
        hold_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id,
                during, expires_at
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-09-01T14:00:00+00'::timestamptz,
                          '2030-09-01T14:30:00+00'::timestamptz, '[)'),
                clock_timestamp() + interval '1 hour'
            ) RETURNING id
            """,
            (organization_id, offering_version_id, party_id),
        )
        conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, hold_id,
                during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2030-09-01T14:00:00+00'::timestamptz,
                          '2030-09-01T14:30:00+00'::timestamptz, '[)'), 1
            )
            """,
            (organization_id, resource_id, requirement_id, hold_id),
        )

    conn.execute(
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '5 minutes')
        """,
        (organization_id, opportunity_id, waitlist_entry_id, hold_id),
    )
    conn.commit()
    return organization_id, hold_id, waitlist_entry_id, opportunity_id


@pytest.mark.postgres
def test_capacity_hold_material_provenance_is_immutable_after_offer_reference(
    admin_conn: PgConnection,
) -> None:
    organization_id, hold_id, _, _ = _sources(admin_conn)

    with pytest.raises(Error) as rejected:
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_holds
            SET during = tstzrange(
                '2030-09-01T15:00:00+00'::timestamptz,
                '2030-09-01T15:30:00+00'::timestamptz, '[)'
            )
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, hold_id),
        )
    assert rejected.value.sqlstate == "23514"
    assert "CapacityHold booking provenance is immutable" in str(rejected.value)
    admin_conn.rollback()

    admin_conn.execute(
        """
        UPDATE request_engine.capacity_holds
        SET revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, hold_id),
    )
    admin_conn.commit()


@pytest.mark.postgres
def test_waitlist_entry_material_provenance_is_immutable_after_offer_reference(
    admin_conn: PgConnection,
) -> None:
    organization_id, _, waitlist_entry_id, _ = _sources(admin_conn)

    with pytest.raises(Error) as rejected:
        admin_conn.execute(
            """
            UPDATE request_engine.waitlist_entries
            SET latest_start = latest_start + interval '1 hour'
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, waitlist_entry_id),
        )
    assert rejected.value.sqlstate == "23514"
    assert "WaitlistEntry booking provenance is immutable" in str(rejected.value)
    admin_conn.rollback()

    admin_conn.execute(
        """
        UPDATE request_engine.waitlist_entries
        SET status = 'cancelled', revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, waitlist_entry_id),
    )
    admin_conn.commit()


@pytest.mark.postgres
def test_slot_opportunity_material_provenance_is_immutable_after_offer_reference(
    admin_conn: PgConnection,
) -> None:
    organization_id, _, _, opportunity_id = _sources(admin_conn)

    with pytest.raises(Error) as rejected:
        admin_conn.execute(
            """
            UPDATE request_engine.slot_opportunities
            SET source_event_id = %s
            WHERE organization_id = %s AND id = %s
            """,
            (uuid4(), organization_id, opportunity_id),
        )
    assert rejected.value.sqlstate == "23514"
    assert "SlotOpportunity booking provenance is immutable" in str(rejected.value)
    admin_conn.rollback()

    admin_conn.execute(
        """
        UPDATE request_engine.slot_opportunities
        SET status = 'closed', revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, opportunity_id),
    )
    admin_conn.commit()
