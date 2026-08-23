from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from tests.fixtures.f2_discovery import DiscoveryFixture, create_discovery_fixture, uuid_row

PgConnection = Connection[Any]


def _issue_handoff(conn: PgConnection, fixture: DiscoveryFixture) -> UUID:
    resource_id = uuid4()
    selection = f"""
    {{
      "offering_version_id": "{fixture.offering_version_id}",
      "location_id": "{fixture.location_id}",
      "start_at": "2035-06-01T14:00:00+00:00",
      "end_at": "2035-06-01T14:30:00+00:00",
      "resources": [{{"resource_id": "{resource_id}"}}],
      "planned_duration_minutes": 30,
      "amount": "3500",
      "currency": "DOP",
      "location_operational_revision": 1,
      "configuration_fingerprint": "sha256:test"
    }}
    """
    return uuid_row(
        conn,
        """
        SELECT request_engine.issue_discovery_booking_handoff(
            repeat('a', 64), %s, 1, %s, 1, %s, %s, %s::jsonb,
            clock_timestamp() + interval '10 minutes'
        )
        """,
        (
            fixture.publication_id,
            fixture.mapping_id,
            fixture.offering_version_id,
            fixture.location_id,
            selection,
        ),
    )


def _attempt_reservation(conn: PgConnection, fixture: DiscoveryFixture, handoff_id: UUID) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, true)",
        (str(fixture.organization_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.discovery_handoff_id', %s, true)",
        (str(handoff_id),),
    )
    conn.execute(
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id, location_id, during
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2035-06-01T14:00:00+00', '2035-06-01T14:30:00+00', '[)')
        )
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
def test_revoked_publication_cannot_commit_discovered_reservation(
    admin_conn: PgConnection,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    handoff_id = _issue_handoff(admin_conn, fixture)
    admin_conn.execute(
        "UPDATE request_engine.discovery_publications SET status = 'revoked' WHERE id = %s",
        (fixture.publication_id,),
    )
    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        _attempt_reservation(admin_conn, fixture, handoff_id)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
        (fixture.organization_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT consumed_reservation_id
        FROM request_engine.discovery_booking_handoffs
        WHERE id = %s
        """,
        (handoff_id,),
    ).fetchone() == (None,)


@pytest.mark.postgres
@pytest.mark.security
def test_mapping_replacement_stales_existing_handoff(admin_conn: PgConnection) -> None:
    fixture = create_discovery_fixture(admin_conn)
    handoff_id = _issue_handoff(admin_conn, fixture)
    admin_conn.execute(
        """
        UPDATE request_engine.offering_service_classifications
        SET status = 'revoked'
        WHERE id = %s
        """,
        (fixture.mapping_id,),
    )
    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        _attempt_reservation(admin_conn, fixture, handoff_id)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
        (fixture.organization_id,),
    ).fetchone() == (0,)
