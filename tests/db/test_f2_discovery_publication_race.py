from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import psycopg
import pytest
from f2_discovery_fixture import create_discovery_fixture
from psycopg import Connection

PgConnection = Connection[Any]


def _publish(
    conninfo: str,
    barrier: Barrier,
    organization_id: object,
    offering_id: object,
    location_id: object,
    resource_id: object | None,
) -> str:
    try:
        with psycopg.connect(conninfo) as conn:
            barrier.wait()
            conn.execute(
                """
                INSERT INTO request_engine.discovery_publications (
                    organization_id, offering_id, location_id, resource_id, effective_during
                ) VALUES (
                    %s, %s, %s, %s,
                    tstzrange('2035-01-01T00:00:00+00','2036-01-01T00:00:00+00','[)')
                )
                """,
                (organization_id, offering_id, location_id, resource_id),
            )
        return "committed"
    except psycopg.errors.ExclusionViolation:
        return "rejected"


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_broad_vs_resource_specific_publication_race_has_one_winner_and_clean_loser(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    admin_conn.execute(
        "UPDATE request_engine.discovery_publications SET status='revoked', revision=revision+1 "
        "WHERE id=%s",
        (fixture.publication_id,),
    )
    barrier = Barrier(2)
    args = (fixture.organization_id, fixture.offering_id, fixture.location_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        broad = pool.submit(_publish, pg_conninfo, barrier, *args, None)
        specific = pool.submit(_publish, pg_conninfo, barrier, *args, fixture.resource_id)
        outcomes = sorted((broad.result(timeout=5), specific.result(timeout=5)))

    assert outcomes == ["committed", "rejected"]
    active = admin_conn.execute(
        """
        SELECT resource_id FROM request_engine.discovery_publications
         WHERE organization_id=%s AND offering_id=%s AND location_id=%s AND status='active'
        """,
        args,
    ).fetchall()
    assert len(active) == 1
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.discovery_publications "
        "WHERE organization_id=%s AND offering_id=%s AND location_id=%s",
        args,
    ).fetchone() == (2,)
