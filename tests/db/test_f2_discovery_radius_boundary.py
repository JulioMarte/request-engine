from typing import Any

import pytest
from f2_discovery_fixture import create_discovery_fixture
from psycopg import Connection

PgConnection = Connection[Any]


def _key(conn: PgConnection, mapping_id: object) -> str:
    row = conn.execute(
        """
        SELECT sc.classification_key
          FROM request_engine.offering_service_classifications m
          JOIN request_engine.service_classifications sc ON sc.id=m.service_classification_id
         WHERE m.id=%s
        """,
        (mapping_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _count(conn: PgConnection, key: str, location_id: object, longitude: float) -> int:
    conn.execute(
        "UPDATE request_engine.locations SET latitude=0, longitude=%s WHERE id=%s",
        (longitude, location_id),
    )
    row = conn.execute(
        """
        SELECT count(*)
          FROM request_engine.search_discovery_candidates_v2(
              %s, 0, 0, 74893,
              '2035-06-01T00:00:00+00', '2035-06-02T00:00:00+00', 20
          )
        """,
        (key,),
    ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.postgres
@pytest.mark.temporal
def test_radius_boundary_is_inclusive_and_rejects_first_point_beyond_it(
    admin_conn: PgConnection,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    key = _key(admin_conn, fixture.mapping_id)

    # At the equator, one micro-degree is a fixed arc under the same mean-earth
    # radius used by the F2 contract. 0.673528 degrees is 74892.9999995 m.
    assert _count(admin_conn, key, fixture.location_id, 0.673527) == 1
    assert _count(admin_conn, key, fixture.location_id, 0.673528) == 1
    assert _count(admin_conn, key, fixture.location_id, 0.673529) == 0
