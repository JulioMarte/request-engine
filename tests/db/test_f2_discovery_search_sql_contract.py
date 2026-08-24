from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from psycopg import Connection, errors

PgConnection = Connection[Any]

_SEARCH_SQL = """
    SELECT count(*)
      FROM request_engine.search_discovery_candidates_v2(
          %s::text,
          %s::double precision,
          %s::double precision,
          %s::integer,
          %s::timestamptz,
          %s::timestamptz,
          %s::integer
      )
"""


@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.parametrize("null_index", [0, 1, 2, 3, 4, 5, 6])
def test_security_definer_search_rejects_null_contract_inputs_under_discovery_authority(
    admin_conn: PgConnection,
    null_index: int,
) -> None:
    window_start = datetime(2035, 6, 1, tzinfo=UTC)
    params: list[object | None] = [
        "cardiology",
        19.7934,
        -70.6884,
        100_000,
        window_start,
        window_start + timedelta(days=1),
        201,
    ]
    params[null_index] = None

    with admin_conn.transaction():
        admin_conn.execute("SET LOCAL ROLE request_engine_discovery")
        with admin_conn.transaction():
            with pytest.raises(errors.InvalidParameterValue):
                admin_conn.execute(_SEARCH_SQL, params).fetchone()


@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.parametrize("limit", [0, 202])
def test_security_definer_search_rejects_candidate_limit_outside_contract(
    admin_conn: PgConnection,
    limit: int,
) -> None:
    window_start = datetime(2035, 6, 1, tzinfo=UTC)
    params = (
        "cardiology",
        19.7934,
        -70.6884,
        100_000,
        window_start,
        window_start + timedelta(days=1),
        limit,
    )

    with admin_conn.transaction():
        admin_conn.execute("SET LOCAL ROLE request_engine_discovery")
        with admin_conn.transaction():
            with pytest.raises(errors.InvalidParameterValue):
                admin_conn.execute(_SEARCH_SQL, params).fetchone()
