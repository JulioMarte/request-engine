"""PostgreSQL backstop for staff Representation delegation (INV-STAFF-REPRESENTATION-001).

Plausible defects these proofs catch: a delegated (non-delegable) row being usable
as a delegation ceiling, the operation revoking a root Representation, stale or
concurrent writers both winning, delegation provenance being rewritten after the
fact, and non-delegable rows without grantor provenance. Calls run as the
restricted ``request_engine_app`` runtime role; the admin connection only builds
the valid prerequisite world and reads authoritative rows as the oracle.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error
from test_staff_membership_lifecycle import (
    invite_active_staff,
    new_staff_native_identity,
    provision_staff_root,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]
_PROFILE = "operations.manage_profile"
_SUPPLY = "operations.manage_supply"
_REPLACE = "SELECT request_engine.replace_staff_representations(%s, %s, %s, %s, %s)"


def _as_actor(conn: PgConnection, organization_id: UUID, principal_id: UUID) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)", (str(organization_id),)
    )
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )


def _revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s", (principal_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _active(conn: PgConnection, principal_id: UUID, party_id: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT scope_key, delegable, granted_by_principal_id FROM request_engine.representations"
        " WHERE principal_id = %s AND represented_party_id = %s AND status = 'active'"
        " ORDER BY scope_key",
        (principal_id, party_id),
    ).fetchall()


def _world(admin_conn: PgConnection) -> dict[str, UUID]:
    org, party, root, _binding, _provisioner = provision_staff_root(admin_conn)
    members: dict[str, UUID] = {"org": org, "party": party, "root": root}
    for name in ("a", "b"):
        authority_id, identity_id, _credential = new_staff_native_identity(admin_conn)
        membership, principal, _ = invite_active_staff(
            admin_conn,
            organization_id=org,
            root_id=root,
            party_id=party,
            authority_id=authority_id,
            native_identity_id=identity_id,
        )
        members[f"{name}_membership"], members[name] = membership, principal
    row = admin_conn.execute(
        "SELECT id FROM request_engine.staff_memberships WHERE principal_id = %s", (root,)
    ).fetchone()
    assert row is not None
    members["root_membership"] = row[0]
    return members


def _sqlstate(conn: PgConnection, params: tuple[object, ...]) -> str | None:
    with pytest.raises(Error) as raised, conn.transaction():
        conn.execute(_REPLACE, params)
    return raised.value.sqlstate


def test_ceiling_root_protection_and_provenance_backstops(
    admin_conn: PgConnection,
    app_role_conn_factory: Callable[[], PgConnection],
) -> None:
    w = _world(admin_conn)
    app = app_role_conn_factory()
    app.autocommit = True
    _as_actor(app, w["org"], w["root"])

    revision = _revision(admin_conn, w["a"])
    assert _sqlstate(app, (w["a_membership"], w["party"], revision, ["staff.invite"], "p")) == (
        "22023"
    )
    assert _sqlstate(app, (w["a_membership"], w["party"], revision, [_PROFILE], " ")) == "22023"
    assert _sqlstate(app, (w["a_membership"], uuid4(), revision, [_PROFILE], "p")) == "P0002"
    assert _sqlstate(app, (uuid4(), w["party"], revision, [_PROFILE], "p")) == "P0002"
    assert _sqlstate(app, (w["a_membership"], w["party"], revision - 1, [_PROFILE], "p")) == (
        "40001"
    )
    root_revision = _revision(admin_conn, w["root"])
    assert _sqlstate(app, (w["root_membership"], w["party"], root_revision, [], "p")) == "42501"
    assert _active(admin_conn, w["a"], w["party"]) == []

    written = app.execute(
        _REPLACE, (w["a_membership"], w["party"], revision, [_PROFILE, _SUPPLY], "delegate")
    ).fetchone()
    assert written is not None and int(written[0]) == _revision(admin_conn, w["a"]) > revision
    assert _active(admin_conn, w["a"], w["party"]) == [
        (_PROFILE, False, w["root"]),
        (_SUPPLY, False, w["root"]),
    ]

    # Provenance is immutable and non-delegable rows require a grantor.
    with pytest.raises(Error) as immutable:
        admin_conn.execute(
            "UPDATE request_engine.representations SET delegable = true"
            " WHERE principal_id = %s AND scope_key = %s",
            (w["a"], _PROFILE),
        )
    assert immutable.value.sqlstate == "23514"
    with pytest.raises(Error) as missing_grantor:
        admin_conn.execute(
            "INSERT INTO request_engine.representations (organization_id, principal_id,"
            " represented_party_id, scope_key, delegable) VALUES (%s, %s, %s, %s, false)",
            (w["org"], w["b"], w["party"], _PROFILE),
        )
    assert missing_grantor.value.sqlstate == "23514"

    # A manager holding only delegated rows has no delegable ceiling.
    admin_conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (%s, %s, 'tenant', 'tenant_control', 'staff.manage_authority', false, %s,
                  'authority_management', 'fixture-second-manager')
        """,
        (w["org"], w["a"], w["root"]),
    )
    _as_actor(app, w["org"], w["a"])
    b_revision = _revision(admin_conn, w["b"])
    assert _sqlstate(app, (w["b_membership"], w["party"], b_revision, [_PROFILE], "p")) == "42501"
    assert _active(admin_conn, w["b"], w["party"]) == []
    # ...and cannot touch the controller's delegable root rows.
    untouched = app.execute(
        _REPLACE, (w["root_membership"], w["party"], _revision(admin_conn, w["root"]), [], "p")
    ).fetchone()
    assert untouched is not None
    assert [row[1] for row in _active(admin_conn, w["root"], w["party"])] == [True] * 4

    # Revocation by the root marks the rows revoked with actor provenance.
    _as_actor(app, w["org"], w["root"])
    app.execute(_REPLACE, (w["a_membership"], w["party"], _revision(admin_conn, w["a"]), [], "r"))
    assert _active(admin_conn, w["a"], w["party"]) == []
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations WHERE principal_id = %s"
        " AND status = 'revoked' AND revoked_by_principal_id = %s AND revoked_at IS NOT NULL",
        (w["a"], w["root"]),
    ).fetchone() == (2,)


def test_concurrent_writers_at_one_revision_have_exactly_one_winner(
    admin_conn: PgConnection,
    app_role_conn_factory: Callable[[], PgConnection],
) -> None:
    w = _world(admin_conn)
    winner, loser = app_role_conn_factory(), app_role_conn_factory()
    for conn in (winner, loser):
        _as_actor(conn, w["org"], w["root"])
        conn.commit()
    revision = _revision(admin_conn, w["a"])
    winner.execute(_REPLACE, (w["a_membership"], w["party"], revision, [_PROFILE], "winner"))
    loser_pid = loser.info.backend_pid

    def contend() -> str | None:
        try:
            loser.execute(_REPLACE, (w["a_membership"], w["party"], revision, [_SUPPLY], "loser"))
        except Error as exc:
            loser.rollback()
            return exc.sqlstate
        loser.commit()
        return None

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(contend)
        deadline = monotonic() + 10
        while True:
            row = admin_conn.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (loser_pid,)
            ).fetchone()
            if row is not None and row[0] == "Lock":
                break
            assert monotonic() < deadline, "loser never blocked on the staff serialization root"
            assert not pending.done(), pending.result()
        winner.commit()
        assert pending.result(timeout=10) == "40001"
    assert _active(admin_conn, w["a"], w["party"]) == [(_PROFILE, False, w["root"])]
