"""A populated v6-era database preserves authority and pending consent on upgrade.

The adoption under test is created/applied through restricted runtime primitives;
this proves migration compatibility, not HTTP authentication or WebAuthn admission.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_governance_support import native_identity, principal_revision, provision_root
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import URL

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.provenance]
ROOT = Path(__file__).resolve().parents[2]


def _conninfo(database: str) -> str:
    return make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "request_engine"),
        password=os.environ.get("PGPASSWORD", "request_engine"),
        dbname=database,
    )


def _upgrade(database: str, revision: str) -> None:
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ.get("PGUSER", "request_engine"),
        password=os.environ.get("PGPASSWORD", "request_engine"),
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=database,
    ).render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "MIGRATION_DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_preserves_old_roots_and_applies_original_v6_consent() -> None:
    database = f"re_controller_v7_upgrade_{uuid4().hex}"
    with psycopg.connect(_conninfo("postgres"), autocommit=True) as cluster:
        assert cluster.info.server_version >= 180000
        cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            _upgrade(database, "0039_operator_metrics_projection")
            with psycopg.connect(_conninfo(database), autocommit=True) as conn:
                _prove_populated_upgrade(database, conn)
        finally:
            cluster.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _prove_populated_upgrade(database: str, conn: Connection[Any]) -> None:
    with conn.transaction():
        conn.execute("SET LOCAL ROLE request_platform_control")
        conn.execute(
            "SELECT request_platform.select_initial_controller_policy('tenant-controller-v1')"
        )
        conn.execute("RESET ROLE")
        org, _, root, _ = provision_root(conn)
    binding_row = conn.execute(
        "SELECT controller_binding_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (org,),
    ).fetchone()
    assert binding_row is not None
    binding = binding_row[0]
    root_revision = principal_revision(conn, root)
    with conn.transaction():
        conn.execute("SELECT set_config('request_engine.organization_id',%s,true)", (str(org),))
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id',%s,true)", (str(root),)
        )
        conn.execute(
            "SELECT set_config('request_engine.authority_revision',%s,true)", (str(root_revision),)
        )
        conn.execute("SET LOCAL ROLE request_engine_app")
        consent = conn.execute(
            "SELECT * FROM request_cmd.request_controller_policy_adoption(%s,%s,%s,%s,%s,%s)",
            (
                binding,
                root_revision,
                "Adopt explicit business administration policy",
                "a" * 64,
                "b" * 64,
                uuid4(),
            ),
        ).fetchone()
    assert consent is not None and consent[2] == "tenant-controller-v6"
    snapshots: dict[str, list[tuple[Any, ...]]] = {}
    for table in (
        "principals",
        "principal_authority_grants",
        "organization_root_provisioning_facts",
        "controller_policy_adoption_requests",
    ):
        snapshots[table] = conn.execute(
            sql.SQL("SELECT to_jsonb(t) FROM request_engine.{} t ORDER BY 1").format(
                sql.Identifier(table)
            )
        ).fetchall()
    v6_before = conn.execute(
        "SELECT grants FROM request_engine.initial_controller_policies "
        "WHERE policy_key='tenant-controller-v6'"
    ).fetchone()
    _upgrade(database, "head")
    for table, before in snapshots.items():
        assert (
            conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM request_engine.{} t ORDER BY 1").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            == before
        )
    assert (
        conn.execute(
            "SELECT grants FROM request_engine.initial_controller_policies "
            "WHERE policy_key='tenant-controller-v6'"
        ).fetchone()
        == v6_before
    )

    authority, identity, _ = native_identity(conn)
    owner, owner_binding = uuid4(), uuid4()
    conn.execute(
        "INSERT INTO request_engine.principals(id,principal_plane,principal_kind,external_subject) "
        "VALUES (%s,'platform','human',%s)",
        (owner, f"migration-compatibility-owner-{owner}"),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(id,principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,%s,'platform',%s,%s,'active')",
        (owner_binding, owner, authority, str(identity)),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','platform.organization.adopt_initial_controller_policy',"
        "false,'trust_bootstrap','migration compatibility approver')",
        (owner,),
    )
    with conn.transaction():
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id',%s,true)", (str(owner),)
        )
        conn.execute(
            "SELECT set_config('request_engine.authority_revision',%s,true)",
            (str(principal_revision(conn, owner)),),
        )
        conn.execute(
            "SELECT set_config('request_engine.identity_binding_id',%s,true)", (str(owner_binding),)
        )
        conn.execute("SELECT set_config('request_engine.correlation_id',%s,true)", (str(uuid4()),))
        conn.execute("SET LOCAL ROLE request_platform_control")
        applied = conn.execute(
            "SELECT * FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
            (consent[0], consent[4], "c" * 64, "d" * 64),
        ).fetchone()
    assert applied is not None
    assert conn.execute(
        "SELECT source_policy_key,target_policy_key FROM "
        "request_engine.controller_policy_adoption_facts WHERE request_id=%s",
        (consent[0],),
    ).fetchone() == ("tenant-controller-v1", "tenant-controller-v6")
    assert conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND capability_key='queue.read_configuration'",
        (root,),
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT initial_controller_policy_key "
        "FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (org,),
    ).fetchone() == ("tenant-controller-v1",)
