from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error, sql

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class Fixture:
    organization_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    other_party_id: UUID
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
        (f"slot-offer-integrity-{suffix}", f"SlotOffer integrity {suffix}"),
    )
    subject_party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Intended subject') RETURNING id
        """,
        (organization_id,),
    )
    other_party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Different subject') RETURNING id
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
        other_party_id=other_party_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _hold_with_claim(conn: PgConnection, fixture: Fixture) -> UUID:
    with conn.transaction():
        hold_id = _uuid(
            conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id,
                during, expires_at
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-07-01T14:00:00+00'::timestamptz,
                          '2030-07-01T14:30:00+00'::timestamptz, '[)'),
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
                tstzrange('2030-07-01T14:00:00+00'::timestamptz,
                          '2030-07-01T14:30:00+00'::timestamptz, '[)'), 1
            )
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                hold_id,
            ),
        )
    return hold_id


def _waitlist_entry(conn: PgConnection, fixture: Fixture, party_id: UUID) -> UUID:
    return _uuid(
        conn,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id
        ) VALUES (%s, %s, %s) RETURNING id
        """,
        (fixture.organization_id, fixture.offering_id, party_id),
    )


def _opportunity(conn: PgConnection, fixture: Fixture) -> UUID:
    return _uuid(
        conn,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-07-01T14:00:00+00'::timestamptz,
                      '2030-07-01T14:30:00+00'::timestamptz, '[)')
        ) RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, uuid4()),
    )


def _offer(
    conn: PgConnection,
    fixture: Fixture,
    opportunity_id: UUID,
    waitlist_entry_id: UUID,
    hold_id: UUID,
) -> UUID:
    return _uuid(
        conn,
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '5 minutes')
        RETURNING id
        """,
        (
            fixture.organization_id,
            opportunity_id,
            waitlist_entry_id,
            hold_id,
        ),
    )


@pytest.mark.postgres
def test_slot_offer_rejects_waitlist_subject_different_from_hold(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn)
    hold_id = _hold_with_claim(admin_conn, fixture)
    wrong_entry_id = _waitlist_entry(admin_conn, fixture, fixture.other_party_id)
    opportunity_id = _opportunity(admin_conn, fixture)

    with pytest.raises(Error) as mismatch:
        _offer(admin_conn, fixture, opportunity_id, wrong_entry_id, hold_id)
    assert mismatch.value.sqlstate == "23514"
    assert "provenance mismatch" in str(mismatch.value)


@pytest.mark.postgres
def test_slot_offer_cannot_retarget_booking_provenance_after_creation(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn)
    hold_id = _hold_with_claim(admin_conn, fixture)
    valid_entry_id = _waitlist_entry(admin_conn, fixture, fixture.subject_party_id)
    other_entry_id = _waitlist_entry(admin_conn, fixture, fixture.other_party_id)
    opportunity_id = _opportunity(admin_conn, fixture)
    offer_id = _offer(admin_conn, fixture, opportunity_id, valid_entry_id, hold_id)

    with pytest.raises(Error) as rewritten:
        admin_conn.execute(
            """
            UPDATE request_engine.slot_offers
            SET waitlist_entry_id = %s
            WHERE organization_id = %s AND id = %s
            """,
            (other_entry_id, fixture.organization_id, offer_id),
        )
    assert rewritten.value.sqlstate == "55000"
    assert "booking provenance is immutable" in str(rewritten.value)

    stored = admin_conn.execute(
        """
        SELECT waitlist_entry_id, capacity_hold_id, slot_opportunity_id
        FROM request_engine.slot_offers
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, offer_id),
    ).fetchone()
    assert stored == (valid_entry_id, hold_id, opportunity_id)


@pytest.mark.postgres
def test_slot_offer_status_transition_requires_revision_advance(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn)
    hold_id = _hold_with_claim(admin_conn, fixture)
    entry_id = _waitlist_entry(admin_conn, fixture, fixture.subject_party_id)
    opportunity_id = _opportunity(admin_conn, fixture)
    offer_id = _offer(admin_conn, fixture, opportunity_id, entry_id, hold_id)

    with pytest.raises(Error) as stale_revision:
        admin_conn.execute(
            """
            UPDATE request_engine.slot_offers
            SET status = 'declined'
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, offer_id),
        )
    assert stale_revision.value.sqlstate == "23514"
    assert "revision advance" in str(stale_revision.value)


@pytest.mark.postgres
def test_slot_offer_insert_locks_semantic_source_rows_until_commit(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    fixture = _fixture(admin_conn)
    hold_id = _hold_with_claim(admin_conn, fixture)
    entry_id = _waitlist_entry(admin_conn, fixture, fixture.subject_party_id)
    opportunity_id = _opportunity(admin_conn, fixture)

    issuer: PgConnection = psycopg.connect(pg_conninfo)
    observer: PgConnection = psycopg.connect(pg_conninfo)
    try:
        _offer(issuer, fixture, opportunity_id, entry_id, hold_id)

        probes = (
            ("slot_opportunities", opportunity_id),
            ("waitlist_entries", entry_id),
            ("capacity_holds", hold_id),
        )
        for table_name, row_id in probes:
            statement = sql.SQL(
                "SELECT id FROM request_engine.{} WHERE id = %s FOR UPDATE NOWAIT"
            ).format(sql.Identifier(table_name))
            with pytest.raises(Error) as blocked:
                observer.execute(statement, (row_id,)).fetchone()
            assert blocked.value.sqlstate == "55P03"
            observer.rollback()
    finally:
        issuer.rollback()
        observer.close()
        issuer.close()
