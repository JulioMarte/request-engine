"""v8 roots reach tenant-controller-v9 only through adoption with the exact delta.

Adapted at the 2026-10-23 rebaseline (docs/audits/postgresql-rebaseline-0047.md):
the former physical 0043 -> head populated-upgrade half lost its subject when the
history collapsed (no pre-0044 database can upgrade into the new 0001). The
authority half remains current truth: on the current head a v8 root reaches v9
only through the platform-approved adoption primitives and gains exactly the
reviewed front-desk delta; provisioning a v7/v8 root grants none of it; adoption
touches no other organization and rewrites no immutable policy row. Adoption runs
through the restricted runtime primitives; this proves database authority, not
HTTP authentication or WebAuthn admission.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_governance_support import native_identity, principal_revision, provision_root
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import URL

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.provenance]
ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_TABLES = (
    "principals",
    "principal_authority_grants",
    "organization_root_provisioning_facts",
    "controller_policy_adoption_requests",
    "controller_policy_adoption_facts",
    "staff_memberships",
    "representations",
)
# Independent reviewed oracle; deliberately not read from the policy catalog.
_V9_DELTA = sorted(
    (
        "queue.configure",
        "queue.list",
        "queue.staff_read",
        "queue.check_in",
        "queue.call_next",
        "queue.skip",
        "queue.mark_no_show",
        "queue.operator_select",
        "queue.recall_hold",
        "queue.release_recall_hold",
        "service_session.start",
        "service_session.complete",
        "appointments.confirm_attendance",
        "appointments.record_arrival_estimate",
        "organization.manage_profile",
    )
)


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


def test_v8_roots_reach_v9_only_through_adoption_with_exact_delta() -> None:
    database = f"re_controller_v9_adoption_{uuid4().hex}"
    with psycopg.connect(_conninfo("postgres"), autocommit=True) as cluster:
        assert cluster.info.server_version >= 180000
        cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            _upgrade(database, "head")
            with psycopg.connect(_conninfo(database), autocommit=True) as conn:
                _prove_adoption_at_head(conn)
        finally:
            cluster.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _root(conn: Connection[Any], policy: str) -> tuple[UUID, UUID, UUID]:
    with conn.transaction():
        conn.execute("SET LOCAL ROLE request_platform_control")
        conn.execute("SELECT request_platform.select_initial_controller_policy(%s)", (policy,))
        conn.execute("RESET ROLE")
        org, _, root, _ = provision_root(conn)
    row = conn.execute(
        "SELECT controller_binding_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (org,),
    ).fetchone()
    assert row is not None
    return org, root, row[0]


def _consent(conn: Connection[Any], org: UUID, root: UUID, binding: UUID) -> tuple[Any, ...]:
    revision = principal_revision(conn, root)
    with conn.transaction():
        conn.execute("SELECT set_config('request_engine.organization_id',%s,true)", (str(org),))
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id',%s,true)", (str(root),)
        )
        conn.execute(
            "SELECT set_config('request_engine.authority_revision',%s,true)", (str(revision),)
        )
        conn.execute("SET LOCAL ROLE request_engine_app")
        row = conn.execute(
            "SELECT * FROM request_cmd.request_controller_policy_adoption(%s,%s,%s,%s,%s,%s)",
            (binding, revision, "Run the front desk", uuid4().hex * 2, uuid4().hex * 2, uuid4()),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _approver(conn: Connection[Any]) -> tuple[UUID, UUID]:
    authority, identity, _ = native_identity(conn)
    owner, binding = uuid4(), uuid4()
    conn.execute(
        "INSERT INTO request_engine.principals(id,principal_plane,principal_kind,external_subject) "
        "VALUES (%s,'platform','human',%s)",
        (owner, f"v9-upgrade-approver-{owner}"),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(id,principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,%s,'platform',%s,%s,'active')",
        (binding, owner, authority, str(identity)),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','platform.organization.adopt_initial_controller_policy',"
        "false,'trust_bootstrap','v9 upgrade approver')",
        (owner,),
    )
    return owner, binding


def _apply(
    conn: Connection[Any], approver: tuple[UUID, UUID], consent: tuple[Any, ...]
) -> tuple[Any, ...]:
    owner, binding = approver
    with conn.transaction():
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id',%s,true)", (str(owner),)
        )
        conn.execute(
            "SELECT set_config('request_engine.authority_revision',%s,true)",
            (str(principal_revision(conn, owner)),),
        )
        conn.execute(
            "SELECT set_config('request_engine.identity_binding_id',%s,true)", (str(binding),)
        )
        conn.execute("SELECT set_config('request_engine.correlation_id',%s,true)", (str(uuid4()),))
        conn.execute("SET LOCAL ROLE request_platform_control")
        row = conn.execute(
            "SELECT * FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
            (consent[0], consent[4], "c" * 64, "d" * 64),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _snapshot(conn: Connection[Any]) -> dict[str, set[str]]:
    return {
        table: {
            str(row[0])
            for row in conn.execute(
                sql.SQL("SELECT to_jsonb(t)::text FROM request_engine.{} t").format(
                    sql.Identifier(table)
                )
            ).fetchall()
        }
        for table in _SNAPSHOT_TABLES
    }


def _active(conn: Connection[Any], root: UUID) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE principal_id=%s AND status='active'",
            (root,),
        ).fetchall()
    }


def _prove_adoption_at_head(conn: Connection[Any]) -> None:
    _, legacy_root, _ = _root(conn, "tenant-controller-v7")
    adopt_org, adopt_root, adopt_binding = _root(conn, "tenant-controller-v8")
    idle_org, idle_root, _ = _root(conn, "tenant-controller-v8")
    # Catches: provisioning an older selected policy silently granting the v9 delta.
    for root in (legacy_root, adopt_root, idle_root):
        assert not _active(conn, root) & set(_V9_DELTA)
    policies_before = conn.execute(
        "SELECT policy_key,revision,grants FROM request_engine.initial_controller_policies "
        "ORDER BY revision"
    ).fetchall()
    assert [row[0] for row in policies_before][-1] == "tenant-controller-v9"

    approver = _approver(conn)
    after_approver = _snapshot(conn)
    adopt_active_before = _active(conn, adopt_root)
    adopt_revision_before = principal_revision(conn, adopt_root)
    consent = _consent(conn, adopt_org, adopt_root, adopt_binding)
    # Catches: consent still targeting v8 (v8 roots would be stuck forever).
    assert consent[1:3] == ("tenant-controller-v8", "tenant-controller-v9")
    applied = _apply(conn, approver, consent)
    # Catches: apply rejecting v8 -> v9, or a delta wider/narrower than reviewed.
    assert (applied[4], applied[5]) == ("tenant-controller-v8", "tenant-controller-v9")
    assert list(applied[8]) == _V9_DELTA
    assert _active(conn, adopt_root) == adopt_active_before | set(_V9_DELTA)
    assert principal_revision(conn, adopt_root) > adopt_revision_before
    new_grants = conn.execute(
        "SELECT capability_key,authority_plane,delegable,granted_by_principal_id "
        "FROM request_engine.principal_authority_grants WHERE provenance_reference=%s "
        "ORDER BY capability_key",
        (f"adoption:{consent[0]}",),
    ).fetchall()
    assert new_grants == [(key, "operational", True, approver[0]) for key in _V9_DELTA]

    # Catches: adoption touching any other organization's rows or rewriting old grants.
    after = _snapshot(conn)
    added_grants = (
        after["principal_authority_grants"] - after_approver["principal_authority_grants"]
    )
    assert after_approver["principal_authority_grants"] <= after["principal_authority_grants"]
    assert len(added_grants) == len(_V9_DELTA)
    for table in ("organization_root_provisioning_facts", "staff_memberships", "representations"):
        assert after[table] == after_approver[table]
    changed_principals = after["principals"] - after_approver["principals"]
    assert len(changed_principals) == 1 and str(adopt_root) in next(iter(changed_principals))
    assert conn.execute(
        "SELECT initial_controller_policy_key "
        "FROM request_engine.organization_root_provisioning_facts WHERE organization_id=%s",
        (adopt_org,),
    ).fetchone() == ("tenant-controller-v8",)

    # Catches: adoption rewriting immutable policy rows or touching other roots.
    assert (
        conn.execute(
            "SELECT policy_key,revision,grants FROM request_engine.initial_controller_policies "
            "ORDER BY revision"
        ).fetchall()
        == policies_before
    )
    assert not _active(conn, legacy_root) & set(_V9_DELTA)
    # Catches: migration or provisioning upgrading an organization that never consented.
    assert not _active(conn, idle_root) & set(_V9_DELTA)
    assert conn.execute(
        "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
        "WHERE organization_id=%s",
        (idle_org,),
    ).fetchone() == (0,)
