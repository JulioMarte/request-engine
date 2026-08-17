from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection, label: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"provider-fair-{label}-{uuid4().hex}", f"Provider fairness {label}"),
    )


def _provider_event(
    conn: PgConnection,
    organization_id: UUID,
    *,
    offset: str,
    label: str,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload, next_attempt_at
        ) VALUES (
            %s, 'fair-provider', 'primary', %s, %s, '{}'::jsonb,
            clock_timestamp() + %s::interval
        )
        RETURNING id
        """,
        (
            organization_id,
            f"provider-fair-{label}-{uuid4().hex}",
            uuid4().hex,
            offset,
        ),
    )


@pytest.mark.postgres
@pytest.mark.concurrency
def test_provider_event_claiming_is_fair_across_tenants(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    hot = _organization(admin_conn, "hot")
    quiet = _organization(admin_conn, "quiet")
    hot_oldest = _provider_event(admin_conn, hot, offset="-10 minutes", label="hot-oldest")
    hot_second = _provider_event(admin_conn, hot, offset="-9 minutes", label="hot-second")
    quiet_oldest = _provider_event(admin_conn, quiet, offset="-1 minute", label="quiet-oldest")

    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT provider_event_row_id, organization_id
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
            """
        ).fetchall()
    finally:
        worker.close()

    ours = [(cast(UUID, row[0]), cast(UUID, row[1])) for row in rows if row[1] in {hot, quiet}]
    assert ours == [
        (hot_oldest, hot),
        (quiet_oldest, quiet),
        (hot_second, hot),
    ]
