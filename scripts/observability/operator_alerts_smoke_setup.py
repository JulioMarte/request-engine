"""Provision ephemeral least-privilege logins for the smoke worker and collector."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql


def main() -> None:
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


if __name__ == "__main__":
    main()
