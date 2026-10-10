"""Provision ephemeral least-privilege logins for the smoke worker and collector."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql


def _provision() -> None:
    database_url = os.environ.get("OPERATOR_ALERT_SMOKE_ADMIN_URL")
    role_name = os.environ.get("OPERATOR_ALERT_SMOKE_METRICS_ROLE")
    password = os.environ.get("OPERATOR_ALERT_SMOKE_METRICS_PASSWORD")
    worker_role_name = os.environ.get("OPERATOR_ALERT_SMOKE_WORKER_ROLE")
    worker_password = os.environ.get("OPERATOR_ALERT_SMOKE_WORKER_PASSWORD")
    if (
        not database_url
        or not role_name
        or not password
        or not worker_role_name
        or not worker_password
    ):
        raise RuntimeError("ephemeral worker and collector database role settings are required")
    if re.fullmatch(r"request_metrics_[a-f0-9]{16}", role_name) is None:
        raise RuntimeError("ephemeral collector database role name has an invalid format")
    if re.fullmatch(r"request_worker_[a-f0-9]{16}", worker_role_name) is None:
        raise RuntimeError("ephemeral worker database role name has an invalid format")
    with psycopg.connect(database_url, autocommit=True) as connection:
        for login, login_password, parent_role in (
            (role_name, password, "request_operator_metrics"),
            (worker_role_name, worker_password, "request_engine_worker"),
        ):
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(login_password))
            )
            connection.execute(
                sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                    sql.Identifier(parent_role), sql.Identifier(login)
                )
            )


def _create_event(database_url: str, state_file: Path) -> None:
    organization_id = uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO request_engine.organizations (id, organization_key, display_name) "
            "VALUES (%s, %s, 'Operator alert integration probe')",
            (organization_id, f"operator-smoke-{organization_id}"),
        )
        row = connection.execute(
            "INSERT INTO request_engine.provider_events (organization_id, provider_key, "
            "connection_key, provider_event_id, payload_hash, payload) "
            "VALUES (%s, 'operator-smoke', 'worker-failure', %s, %s, '{}'::jsonb) RETURNING id",
            (organization_id, f"probe-{uuid4()}", f"sha256-{uuid4().hex}"),
        ).fetchone()
        if row is None:
            raise RuntimeError("event fixture creation returned no event")
    state_file.write_text(
        json.dumps({"organization_id": str(organization_id), "event_id": str(row[0])}),
        encoding="utf-8",
    )


def _replay_event(database_url: str, state_file: Path) -> None:
    fixture = json.loads(state_file.read_text(encoding="utf-8"))
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "SELECT set_config('request_engine.organization_id', %s, true), "
            "set_config('request_engine.authenticated_principal_id', %s, true)",
            (fixture["organization_id"], str(uuid4())),
        )
        row = connection.execute(
            "SELECT request_admin.replay_provider_event(%s, %s, 1, "
            "'operator alert smoke recovery')",
            (fixture["organization_id"], fixture["event_id"]),
        ).fetchone()
        if row is None or row[0] is not True:
            raise RuntimeError("operator replay did not return the failed event to the queue")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "create-event", "replay-event"))
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    if args.action == "provision":
        _provision()
        return
    database_url = os.environ.get("OPERATOR_ALERT_SMOKE_ADMIN_URL")
    if not database_url or args.state_file is None:
        parser.error("event actions require the outer admin database and --state-file")
    if args.action == "create-event":
        _create_event(database_url, args.state_file)
    else:
        _replay_event(database_url, args.state_file)


if __name__ == "__main__":
    main()
