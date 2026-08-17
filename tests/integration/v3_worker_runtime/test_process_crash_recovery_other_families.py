import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]
WorkerFamily = Literal["outbox", "provider_event"]


def _conninfo() -> str:
    return " ".join(
        (
            f"host={os.environ.get('PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('PGPORT', '5432')}",
            f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}",
            f"user={os.environ.get('PGUSER', 'request_engine')}",
            f"password={os.environ.get('PGPASSWORD', 'request_engine')}",
        )
    )


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(admin_conn: PgConnection, family: WorkerFamily) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"process-crash-{family}-{suffix}", f"Process crash {family}"),
    )


def _fixture(admin_conn: PgConnection, family: WorkerFamily) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _organization(admin_conn, family)
    if family == "outbox":
        work_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id, event_type, aggregate_kind, aggregate_id,
                payload, next_attempt_at
            ) VALUES (
                %s, 'test.process_crash.v1', 'Test', %s, '{}'::jsonb,
                clock_timestamp() - interval '1 minute'
            )
            RETURNING id
            """,
            (organization_id, uuid4()),
        )
    else:
        work_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.provider_events (
                organization_id, provider_key, connection_key,
                provider_event_id, payload_hash, payload, next_attempt_at
            ) VALUES (
                %s, 'process-crash-provider', 'primary', %s, %s, '{}'::jsonb,
                clock_timestamp() - interval '1 minute'
            )
            RETURNING id
            """,
            (organization_id, f"event-{suffix}", uuid4().hex),
        )
    return organization_id, work_id


def _expire(admin_conn: PgConnection, family: WorkerFamily, work_id: UUID) -> None:
    sql: LiteralString
    if family == "outbox":
        sql = """
            UPDATE request_engine.outbox_messages
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
        """
    else:
        sql = """
            UPDATE request_engine.provider_events
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
        """
    admin_conn.execute(sql, (work_id,))


def _state(
    admin_conn: PgConnection,
    family: WorkerFamily,
    organization_id: UUID,
    work_id: UUID,
) -> tuple[object, ...]:
    query: LiteralString
    if family == "outbox":
        query = """
            SELECT status, claim_token, lease_until > clock_timestamp(), attempt_count
            FROM request_engine.outbox_messages
            WHERE organization_id = %s AND id = %s
        """
    else:
        query = """
            SELECT status, claim_token, lease_until > clock_timestamp(), attempt_count
            FROM request_engine.provider_events
            WHERE organization_id = %s AND id = %s
        """
    row = admin_conn.execute(query, (organization_id, work_id)).fetchone()
    assert row is not None
    return tuple(row)


def _final_state(
    admin_conn: PgConnection,
    family: WorkerFamily,
    organization_id: UUID,
    work_id: UUID,
) -> tuple[object, ...]:
    query: LiteralString
    if family == "outbox":
        query = """
            SELECT status, claim_token, lease_until, attempt_count
            FROM request_engine.outbox_messages
            WHERE organization_id = %s AND id = %s
        """
    else:
        query = """
            SELECT status, claim_token, lease_until, attempt_count
            FROM request_engine.provider_events
            WHERE organization_id = %s AND id = %s
        """
    row = admin_conn.execute(query, (organization_id, work_id)).fetchone()
    assert row is not None
    return tuple(row)


def _reclaim(worker: PgConnection, family: WorkerFamily, work_id: UUID) -> UUID:
    query: LiteralString
    if family == "outbox":
        query = """
            SELECT message_id, claim_token
            FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')
        """
    else:
        query = """
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
        """
    rows = worker.execute(query).fetchall()
    row = next(value for value in rows if value[0] == work_id)
    return cast(UUID, row[1])


def _complete(
    worker: PgConnection,
    family: WorkerFamily,
    work_id: UUID,
    token: UUID,
) -> bool:
    query: LiteralString
    if family == "outbox":
        query = "SELECT request_cmd.complete_outbox_message(%s, %s)"
    else:
        query = "SELECT request_cmd.complete_provider_event(%s, %s)"
    row = worker.execute(query, (work_id, token)).fetchone()
    assert row is not None
    return cast(bool, row[0])


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.parametrize("family", ("outbox", "provider_event"))
def test_sigkill_after_claim_is_recoverable_for_other_worker_families(
    family: WorkerFamily,
    admin_conn: PgConnection,
    tmp_path: Path,
) -> None:
    organization_id, work_id = _fixture(admin_conn, family)
    result_path = tmp_path / f"claimed-{family}.json"
    child = r'''
import json
import os
import signal
import sys

import psycopg

conninfo, family, work_id, result_path = sys.argv[1:5]
conn = psycopg.connect(conninfo, autocommit=True)
conn.execute("SET ROLE request_engine_worker")
if family == "outbox":
    rows = conn.execute(
        "SELECT message_id, claim_token FROM request_cmd.claim_outbox_messages(500, interval '30 seconds')"
    ).fetchall()
else:
    rows = conn.execute(
        "SELECT provider_event_row_id, claim_token FROM request_cmd.claim_provider_events(500, interval '30 seconds')"
    ).fetchall()
row = next(value for value in rows if str(value[0]) == work_id)
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump({"work_id": str(row[0]), "claim_token": str(row[1])}, handle)
    handle.flush()
    os.fsync(handle.fileno())
os.kill(os.getpid(), signal.SIGKILL)
'''
    process = subprocess.run(
        [sys.executable, "-c", child, _conninfo(), family, str(work_id), str(result_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode < 0
    assert result_path.exists(), process.stderr
    first_token = UUID(json.loads(result_path.read_text(encoding="utf-8"))["claim_token"])

    assert _state(admin_conn, family, organization_id, work_id) == (
        "leased",
        first_token,
        True,
        1,
    )

    _expire(admin_conn, family, work_id)
    worker: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        second_token = _reclaim(worker, family, work_id)
        assert second_token != first_token
        assert _complete(worker, family, work_id, first_token) is False
        assert _complete(worker, family, work_id, second_token) is True
    finally:
        worker.close()

    expected_status = "delivered" if family == "outbox" else "processed"
    assert _final_state(admin_conn, family, organization_id, work_id) == (
        expected_status,
        None,
        None,
        2,
    )
