from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _uuid(conn: PgConnection, statement: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid(
        conn,
        "INSERT INTO request_engine.organizations (organization_key, display_name) VALUES (%s, %s) RETURNING id",
        (f"org-{suffix}", "Discovery Org"),
    )
    party_id = _uuid(
        conn,
        "INSERT INTO request_engine.parties (organization_id, party_kind, display_name) VALUES (%s, 'person', 'Subject') RETURNING id",
        (organization_id,),
    )
    location_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, latitude, longitude
        ) VALUES (%s, %s, 'Clinic', 'UTC', 19.8, -70.7) RETURNING id
        """,
        (organization_id, f"loc-{suffix}"),
    )
    offering_id = _uuid(
        conn,
        "INSERT INTO request_engine.offerings (organization_id, offering_key, display_name) VALUES (%s, %s, 'Cardiology') RETURNING id",
        (organization_id, f"offering-{suffix}"),
    )
    offering_version_id = _uuid(
        conn,
        "INSERT INTO request_engine.offering_versions (organization_id, offering_id, version, duration_minutes, bookable) VALUES (%s, %s, 1, 30, true) RETURNING id",
        (organization_id, offering_id),
    )
    classification_id = _uuid(
        conn,
        "INSERT INTO request_engine.service_classifications (classification_key, canonical_name) VALUES (%s, 'Cardiology') RETURNING id",
        (f"cardiology_{suffix}",),
    )
    mapping_id = _uuid(
        conn,
        "INSERT INTO request_engine.offering_service_classifications (organization_id, offering_id, service_classification_id) VALUES (%s, %s, %s) RETURNING id",
        (organization_id, offering_id, classification_id),
    )
    publication_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.discovery_publications (
            organization_id, offering_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2035-01-01T00:00:00+00', '2036-01-01T00:00:00+00', '[)')
        ) RETURNING id
        """,
        (organization_id, offering_id, location_id),
    )
    return (
        organization_id,
        party_id,
        location_id,
        offering_version_id,
        mapping_id,
        publication_id,
    )


def _issue_handoff(
    conn: PgConnection,
    publication_id: UUID,
    offering_version_id: UUID,
    location_id: UUID,
) -> UUID:
    selection = """
    {
      "offering_version_id": "%s",
      "start_at": "2035-06-01T14:00:00+00:00",
      "end_at": "2035-06-01T14:30:00+00:00",
      "location_id": "%s",
      "resources": [],
      "planned_duration_minutes": 30,
      "amount": "3500",
      "currency": "DOP",
      "location_operational_revision": 1,
      "configuration_fingerprint": "sha256:test"
    }
    """ % (offering_version_id, location_id)
    return _uuid(
        conn,
        """
        SELECT request_engine.issue_discovery_booking_handoff(
            repeat('a', 64), %s, 1, %s, %s, %s::jsonb,
            clock_timestamp() + interval '10 minutes'
        )
        """,
        (publication_id, offering_version_id, location_id, selection),
    )


@pytest.mark.postgres
@pytest.mark.security
def test_revoked_publication_cannot_commit_discovered_reservation(
    admin_conn: PgConnection,
) -> None:
    org_id, party_id, location_id, version_id, _, publication_id = _fixture(admin_conn)
    handoff_id = _issue_handoff(admin_conn, publication_id, version_id, location_id)
    admin_conn.execute(
        "UPDATE request_engine.discovery_publications SET status = 'revoked' WHERE id = %s",
        (publication_id,),
    )

    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        admin_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, true)",
            (str(org_id),),
        )
        admin_conn.execute(
            "SELECT set_config('request_engine.discovery_handoff_id', %s, true)",
            (str(handoff_id),),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, location_id, during
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2035-06-01T14:00:00+00', '2035-06-01T14:30:00+00', '[)')
            )
            """,
            (org_id, version_id, party_id, location_id),
        )

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
        (org_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT consumed_reservation_id FROM request_engine.discovery_booking_handoffs WHERE id = %s",
        (handoff_id,),
    ).fetchone() == (None,)


@pytest.mark.postgres
@pytest.mark.security
def test_mapping_replacement_stales_existing_handoff(admin_conn: PgConnection) -> None:
    org_id, party_id, location_id, version_id, mapping_id, publication_id = _fixture(admin_conn)
    handoff_id = _issue_handoff(admin_conn, publication_id, version_id, location_id)
    admin_conn.execute(
        "UPDATE request_engine.offering_service_classifications SET status = 'revoked' WHERE id = %s",
        (mapping_id,),
    )

    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        admin_conn.execute("SELECT set_config('request_engine.organization_id', %s, true)", (str(org_id),))
        admin_conn.execute("SELECT set_config('request_engine.discovery_handoff_id', %s, true)", (str(handoff_id),))
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, location_id, during
            ) VALUES (%s, %s, %s, %s, tstzrange('2035-06-01T14:00:00+00', '2035-06-01T14:30:00+00', '[)'))
            """,
            (org_id, version_id, party_id, location_id),
        )
