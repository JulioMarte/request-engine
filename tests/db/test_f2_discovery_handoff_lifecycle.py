from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import Connection

from tests.fixtures.f2_discovery import DiscoveryFixture, create_discovery_fixture, uuid_row

PgConnection = Connection[Any]


def _handoff(conn: PgConnection, fixture: DiscoveryFixture, token_hash: str) -> UUID:
    selection = """
    {
      "start_at":"2035-06-01T14:00:00+00:00",
      "end_at":"2035-06-01T14:30:00+00:00",
      "resources":[],
      "planned_duration_minutes":30,
      "amount":"3500",
      "currency":"DOP",
      "location_operational_revision":1,
      "configuration_fingerprint":"sha256:test"
    }
    """
    return uuid_row(
        conn,
        """
        SELECT request_engine.issue_discovery_booking_handoff(
            %s, %s, 1, %s, %s, %s::jsonb,
            clock_timestamp() + interval '10 minutes'
        )
        """,
        (
            token_hash,
            fixture.publication_id,
            fixture.offering_version_id,
            fixture.location_id,
            selection,
        ),
    )


def _insert_reservation(conn: PgConnection, fixture: DiscoveryFixture, handoff_id: UUID) -> UUID:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, true)",
        (str(fixture.organization_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.discovery_handoff_id', %s, true)",
        (str(handoff_id),),
    )
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id, location_id, during
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2035-06-01T14:00:00+00', '2035-06-01T14:30:00+00', '[)')
        ) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.party_id,
            fixture.location_id,
        ),
    )


@pytest.mark.postgres
@pytest.mark.security
def test_consumed_handoff_remains_resolvable_for_idempotent_replay(
    admin_conn: PgConnection,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    token_hash = "b" * 64
    handoff_id = _handoff(admin_conn, fixture, token_hash)
    reservation_id = _insert_reservation(admin_conn, fixture, handoff_id)

    assert admin_conn.execute(
        "SELECT consumed_reservation_id FROM request_engine.discovery_booking_handoffs WHERE id=%s",
        (handoff_id,),
    ).fetchone() == (reservation_id,)
    admin_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(fixture.organization_id),),
    )
    assert admin_conn.execute(
        "SELECT handoff_id FROM request_engine.read_discovery_booking_handoff(%s)",
        (token_hash,),
    ).fetchone() == (handoff_id,)


@pytest.mark.postgres
@pytest.mark.security
def test_new_offering_version_stales_existing_handoff(admin_conn: PgConnection) -> None:
    fixture = create_discovery_fixture(admin_conn)
    handoff_id = _handoff(admin_conn, fixture, "c" * 64)
    admin_conn.execute(
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 2, 30, true)
        """,
        (fixture.organization_id, fixture.offering_id),
    )

    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        _insert_reservation(admin_conn, fixture, handoff_id)

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id=%s",
        (fixture.organization_id,),
    ).fetchone() == (0,)
