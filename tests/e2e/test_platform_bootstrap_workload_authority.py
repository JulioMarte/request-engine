"""Deployment bootstrap registers the RE-native workload identity authority.

Integration and agent provisioning require an active ``workload`` identity
authority. The deployment bootstrap is the supported trust-root contract that
registers it, so a clean installation never needs SQL fixtures to obtain one.

This proof runs the real bootstrap CLI against real PostgreSQL and asserts the
authority it prints is an active workload authority distinct from the native
human authority. The API acceptance of an active workload authority is proven
separately by ``test_native_integration_lifecycle``; together they cover the
deployment-to-command chain without seeding the result under test.
"""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.platform_bootstrap_cli import issue_intent

from .conftest import PgConnection

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security]


def _issued_authorities(conn: PgConnection, monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID]:
    monkeypatch.setenv(
        "REQUEST_ENGINE_BOOTSTRAP_DSN",
        make_conninfo(conn.info.dsn, password=os.environ.get("PGPASSWORD", "request_engine")),
    )
    issued = issue_intent(ttl_minutes=15, provenance="bootstrap-workload-authority-e2e")
    lines = dict(line.split(": ", 1) for line in issued.splitlines() if ": " in line)
    return UUID(lines["Native authority"]), UUID(lines["Workload authority"])


def test_bootstrap_registers_active_workload_identity_authority(
    e2e_admin_conn: PgConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_authority_id, workload_authority_id = _issued_authorities(e2e_admin_conn, monkeypatch)
    assert workload_authority_id != native_authority_id

    observed = {
        row[0]: (row[1], row[2])
        for row in e2e_admin_conn.execute(
            """
            SELECT id, kind, status
              FROM request_engine.identity_authorities
             WHERE id = ANY(%s)
            """,
            ([native_authority_id, workload_authority_id],),
        ).fetchall()
    }
    assert observed[native_authority_id] == ("native", "active")
    assert observed[workload_authority_id] == ("workload", "active")
