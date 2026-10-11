"""Recovery in the alert lab must use a real actor and commit an audited replay."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from psycopg import Connection

pytestmark = [pytest.mark.postgres, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]


def test_alert_fixture_replay_commits_with_existing_audit_actor(
    pg_conninfo: str, admin_conn: Connection[Any], tmp_path: Path
) -> None:
    state_file = tmp_path / "event.json"
    environment = {**os.environ, "OPERATOR_ALERT_SMOKE_ADMIN_URL": pg_conninfo}
    command = [sys.executable, str(ROOT / "scripts/observability/operator_alerts_smoke_setup.py")]
    subprocess.run(
        [*command, "create-event", "--state-file", str(state_file)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    fixture = json.loads(state_file.read_text(encoding="utf-8"))
    # This is the replay helper's prerequisite, not a claim about worker execution.
    admin_conn.execute(
        "UPDATE request_engine.provider_events SET status = 'dead' WHERE id = %s",
        (fixture["event_id"],),
    )
    subprocess.run(
        [*command, "replay-event", "--state-file", str(state_file)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert admin_conn.execute(
        "SELECT status, replay_count FROM request_engine.provider_events WHERE id = %s",
        (fixture["event_id"],),
    ).fetchone() == ("received", 1)
    audit = admin_conn.execute(
        "SELECT a.actor_principal_id::text, a.details->>'reason' "
        "FROM request_engine.audit_records a JOIN request_engine.principals p "
        "ON (p.organization_id, p.id) = (a.organization_id, a.actor_principal_id) "
        "WHERE a.organization_id = %s AND a.aggregate_id = %s "
        "AND a.command_name = 'admin.replay_provider_event'",
        (fixture["organization_id"], fixture["event_id"]),
    ).fetchall()
    assert audit == [(fixture["actor_id"], "operator alert smoke recovery")]
