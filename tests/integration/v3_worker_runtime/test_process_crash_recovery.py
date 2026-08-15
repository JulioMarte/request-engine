import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


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


def _fixture(admin_conn: PgConnection) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization_row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Process crash recovery')
        RETURNING id
        """,
        (f"process-crash-{suffix}",),
    ).fetchone()
    assert organization_row is not None
    organization_id = cast(UUID, organization_row[0])

    action_row = admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            payload, dedupe_key, execute_at, next_attempt_at
        ) VALUES (
            %s, 'booking', 'test.process_crash', 1,
            '{}'::jsonb, %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() - interval '1 minute'
        )
        RETURNING id
        """,
        (organization_id, f"process-crash:{suffix}"),
    ).fetchone()
    assert action_row is not None
    return organization_id, cast(UUID, action_row[0])


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_sigkill_after_claim_is_recoverable_and_stale_worker_is_fenced(
    admin_conn: PgConnection,
    tmp_path: Path,
) -> None:
    """Kill a real worker after claim COMMIT, then prove lease recovery and fencing."""

    organization_id, action_id = _fixture(admin_conn)
    result_path = tmp_path / "claimed.json"
    child = r"""
import json
import os
import signal
import sys
from uuid import UUID

import psycopg

conninfo, action_id, result_path = sys.argv[1:4]
conn = psycopg.connect(conninfo, autocommit=True)
conn.execute("SET ROLE request_engine_worker")
rows = conn.execute(
    """
    SELECT action_id, claim_token
    FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
    """
).fetchall()
row = next(value for value in rows if str(value[0]) == action_id)
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump({"action_id": str(row[0]), "claim_token": str(row[1])}, handle)
    handle.flush()
    os.fsync(handle.fileno())
os.kill(os.getpid(), signal.SIGKILL)
"""
    process = subprocess.run(
        [sys.executable, "-c", child, _conninfo(), str(action_id), str(result_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode < 0
    assert result_path.exists(), process.stderr
    first_claim = json.loads(result_path.read_text(encoding="utf-8"))
    first_token = UUID(first_claim["claim_token"])

    claimed_state = admin_conn.execute(
        """
        SELECT status, claim_token IS NOT NULL, lease_until > clock_timestamp()
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, action_id),
    ).fetchone()
    assert claimed_state == ("processing", True, True)

    # Advance only the lease boundary. This keeps the test deterministic without sleeping.
    admin_conn.execute(
        """
        UPDATE request_engine.scheduled_actions
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, action_id),
    )

    worker: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        rows = worker.execute(
            """
            SELECT action_id, claim_token
            FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
            """
        ).fetchall()
        second_row = next(row for row in rows if row[0] == action_id)
        second_token = cast(UUID, second_row[1])
        assert second_token != first_token

        assert worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, first_token),
        ).fetchone() == (False,)
        assert worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, second_token),
        ).fetchone() == (True,)
    finally:
        worker.close()

    assert admin_conn.execute(
        """
        SELECT status, claim_token, lease_until
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, action_id),
    ).fetchone() == ("completed", None, None)
