from __future__ import annotations

from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _queue_entry_fixture(conn: PgConnection) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i34-{suffix}", f"I34 {suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name, policy_key
        ) VALUES (%s, %s, %s, 'fifo')
        RETURNING id
        """,
        (organization_id, f"queue-{suffix}", f"Queue {suffix}"),
    )
    entry_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, queue_id, subject_party_id),
    )
    return organization_id, entry_id


@pytest.mark.postgres
def test_i34_queue_entry_allows_only_canonical_lifecycle_transitions(
    admin_conn: PgConnection,
) -> None:
    organization_id, entry_id = _queue_entry_fixture(admin_conn)

    for next_status in ("called", "serving", "completed"):
        row = admin_conn.execute(
            """
            UPDATE request_engine.queue_entries
            SET status = %s, revision = revision + 1
            WHERE organization_id = %s AND id = %s
            RETURNING status, revision
            """,
            (next_status, organization_id, entry_id),
        ).fetchone()
        assert row is not None
        assert row[0] == next_status

    with pytest.raises(Error) as reopen_error:
        admin_conn.execute(
            """
            UPDATE request_engine.queue_entries
            SET status = 'waiting', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, entry_id),
        )
    assert reopen_error.value.sqlstate == "23514"

    second_org, second_entry = _queue_entry_fixture(admin_conn)
    with pytest.raises(Error) as skip_error:
        admin_conn.execute(
            """
            UPDATE request_engine.queue_entries
            SET status = 'serving', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (second_org, second_entry),
        )
    assert skip_error.value.sqlstate == "23514"


@pytest.mark.postgres
def test_i35_queue_position_is_derived_and_has_no_authoritative_counter(
    admin_conn: PgConnection,
) -> None:
    columns = {
        cast(str, row[0])
        for row in admin_conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'request_engine'
              AND table_name = 'queue_entries'
            """
        ).fetchall()
    }
    forbidden_authoritative_position_columns = {
        "position",
        "queue_position",
        "position_index",
        "position_counter",
        "sequence_number",
        "ordinal",
    }
    assert columns.isdisjoint(forbidden_authoritative_position_columns)

    reader_source = Path(
        "src/request_engine/modules/queue/adapters/db/service_queue_reader.py"
    ).read_text(encoding="utf-8")
    assert "SELECT count(*)" in reader_source
    assert "AND status = 'waiting'" in reader_source
    assert "AND (admitted_at, id) < (:admitted_at, :entry_id)" in reader_source
