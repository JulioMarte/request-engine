from typing import Any

import pytest
from f2_discovery_fixture import create_discovery_fixture
from psycopg import Connection

PgConnection = Connection[Any]


def _classification_key(conn: PgConnection, mapping_id: object) -> str:
    row = conn.execute(
        """
        SELECT sc.classification_key
          FROM request_engine.offering_service_classifications m
          JOIN request_engine.service_classifications sc ON sc.id = m.service_classification_id
         WHERE m.id = %s
        """,
        (mapping_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _search(conn: PgConnection, key: str) -> list[tuple[object, ...]]:
    return conn.execute(
        """
        SELECT location_address_line1, location_locality, location_country_code,
               provider_key, provider_display_name, provider_role_label
          FROM request_engine.search_discovery_candidates_v2(
              %s, 19.8, -70.7, 2000,
              '2035-06-01T00:00:00+00', '2035-06-02T00:00:00+00', 20
          )
        """,
        (key,),
    ).fetchall()


@pytest.mark.postgres
@pytest.mark.security
def test_public_provider_projection_requires_explicit_profile_and_publication(
    admin_conn: PgConnection,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    key = _classification_key(admin_conn, fixture.mapping_id)
    admin_conn.execute(
        """
        UPDATE request_engine.locations
           SET address_line1 = '27 de Febrero 10', locality = 'Puerto Plata', country_code = 'DO'
         WHERE id = %s
        """,
        (fixture.location_id,),
    )
    assert _search(admin_conn, key) == [
        ("27 de Febrero 10", "Puerto Plata", "DO", None, None, None)
    ]

    admin_conn.execute(
        "UPDATE request_engine.discovery_publications "
        "SET status='revoked', revision=revision+1 WHERE id=%s",
        (fixture.publication_id,),
    )
    assert _search(admin_conn, key) == []

    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_public_profiles (
            organization_id, resource_id, display_name, role_label
        ) VALUES (%s, %s, 'Dr. A', 'Cardiologist')
        """,
        (fixture.organization_id, fixture.resource_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.discovery_publications (
            organization_id, offering_id, location_id, resource_id,
            effective_during, provider_visibility
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2035-01-01T00:00:00+00','2036-01-01T00:00:00+00','[)'), 'public'
        )
        """,
        (fixture.organization_id, fixture.offering_id, fixture.location_id, fixture.resource_id),
    )
    row = _search(admin_conn, key)
    assert len(row) == 1
    assert row[0][0:3] == ("27 de Febrero 10", "Puerto Plata", "DO")
    assert row[0][4:6] == ("Dr. A", "Cardiologist")
    assert row[0][3] is not None
