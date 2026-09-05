from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]

pytestmark = [pytest.mark.postgres, pytest.mark.invariant]


def test_reservations_have_tenant_scoped_temporal_gist_index(
    admin_conn: PgConnection,
) -> None:
    row = admin_conn.execute(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'request_engine'
          AND tablename = 'reservations'
          AND indexname = 'reservations_org_during_gist'
        """
    ).fetchone()

    assert row == (
        "CREATE INDEX reservations_org_during_gist ON request_engine.reservations "
        "USING gist (organization_id, during)",
    )


def test_reservation_overlap_predicate_can_use_temporal_gist_access_path(
    admin_conn: PgConnection,
) -> None:
    admin_conn.execute("SET enable_seqscan = off")
    try:
        rows = admin_conn.execute(
            """
            EXPLAIN (COSTS OFF)
            SELECT id
            FROM request_engine.reservations
            WHERE during && tstzrange(
                '2030-01-01T00:00:00Z'::timestamptz,
                '2030-01-02T00:00:00Z'::timestamptz,
                '[)'
            )
            """
        ).fetchall()
    finally:
        admin_conn.execute("RESET enable_seqscan")

    plan = "\n".join(str(row[0]) for row in rows)
    assert "reservations_org_during_gist" in plan
