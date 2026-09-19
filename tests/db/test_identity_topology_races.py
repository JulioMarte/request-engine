"""Identity-topology lock-order races (plan B-02).

These proofs protect the inversion-free lock order required by ADR 0013 D5:

- every tenant topology writer acquires the ordered active-staff-membership root
  before locking any specific membership or binding row, so a concurrent writer
  waits on the root instead of holding a specific row;
- two controllers removing each other concurrently resolve without a PostgreSQL
  deadlock (``40P01``) and always leave at least one effective controller.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_governance_support import (
    native_identity,
    principal_revision,
    provision_root,
    reset_actor,
    set_tenant_actor,
)
from native_authority_gate_support import wait_for_lock_wait
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _backend_pid(conn: PgConnection) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return cast(int, row[0])


def _invite_activate_promote(
    conn: PgConnection,
    *,
    organization_id: UUID,
    party_id: UUID,
    root_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
    try:
        returned = conn.execute(
            """
            SELECT request_engine.invite_native_staff(
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"topology-race-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            """
            SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)
            """,
            (membership_id, f"topology-race-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
        revision = principal_revision(conn, principal_id)
        promoted = conn.execute(
            """
            SELECT request_engine.replace_staff_authority(
                %s, %s,
                ARRAY[
                    'staff.manage_membership',
                    'staff.manage_authority',
                    'identity.bind'
                ]::text[],
                %s
            )
            """,
            (membership_id, revision, f"topology-race-promote:{uuid4().hex}"),
        ).fetchone()
        assert promoted is not None
    finally:
        reset_actor(conn)
    return membership_id, principal_id, binding_id


def _binding_revision(conn: PgConnection, binding_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _effective_controller_count(conn: PgConnection, organization_id: UUID) -> int:
    """Count effective controllers under the authoritative tenant predicate.

    The predicate is ``SECURITY DEFINER`` over ``FORCE RLS`` tables, so it needs
    the trusted tenant GUC even when called from the administrative connection.
    """

    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    try:
        row = conn.execute(
            """
            SELECT count(*)
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = %s
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       %s, membership.principal_id)
            """,
            (organization_id, organization_id),
        ).fetchone()
    finally:
        conn.execute("SELECT set_config('request_engine.organization_id', '', false)")
    assert row is not None
    return int(row[0])


@pytest.mark.concurrency
@pytest.mark.parametrize("command", ["staff_membership", "identity_binding"])
def test_topology_writers_lock_the_staff_root_before_any_specific_row(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command: str,
) -> None:
    organization_id, party_id, root_id, _root_authority = provision_root(admin_conn)
    authority_id, native_identity_id, _credential_id = native_identity(admin_conn)
    membership_id, _staff_id, staff_binding = _invite_activate_promote(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        root_id=root_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
    )

    # Move the specific target out of the ordered active root so a third
    # connection can probe it independently of the root lock.
    set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    try:
        if command == "staff_membership":
            target_id = membership_id
            target_table = "request_engine.staff_memberships"
            suspended = admin_conn.execute(
                """
                SELECT request_engine.transition_staff_membership(%s, 2, 'suspended', %s)
                """,
                (membership_id, f"topology-race-suspend:{uuid4().hex}"),
            ).fetchone()
            assert suspended == (3,)
            statement = "SELECT request_engine.transition_staff_membership(%s, 3, 'active', %s)"
        else:
            target_id = staff_binding
            target_table = "request_engine.identity_bindings"
            suspended = admin_conn.execute(
                """
                SELECT request_engine.transition_identity_binding(%s, 2, 'suspended', %s)
                """,
                (staff_binding, f"topology-race-suspend:{uuid4().hex}"),
            ).fetchone()
            assert suspended == (3,)
            statement = "SELECT request_engine.transition_identity_binding(%s, 3, 'active', %s)"
    finally:
        reset_actor(admin_conn)

    holder = psycopg.connect(pg_conninfo)
    worker = psycopg.connect(pg_conninfo)
    probe = psycopg.connect(pg_conninfo)
    try:
        holder.execute("SET statement_timeout = '20s'")
        holder.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        holder_pid = _backend_pid(holder)
        holder.execute("SELECT request_engine.lock_tenant_staff_root()")

        worker.execute("SET statement_timeout = '20s'")
        set_tenant_actor(worker, organization_id=organization_id, principal_id=root_id)
        worker_pid = _backend_pid(worker)
        params: tuple[object, ...] = (target_id, f"topology-order:{uuid4().hex}")

        def run() -> None:
            try:
                worker.execute(statement, params)
                worker.commit()
            except Error:
                worker.rollback()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(run)
            try:
                assert wait_for_lock_wait(admin_conn, worker_pid, blocker_pid=holder_pid), (
                    f"{command} did not wait on the staff root"
                )
                # While the writer waits on the root, the specific row must still
                # be free. If the writer had locked it first, NOWAIT would fail.
                try:
                    probe.execute(
                        f"SELECT 1 FROM {target_table} WHERE id = %s FOR UPDATE NOWAIT",
                        (target_id,),
                    )
                except Error as exc:
                    assert exc.sqlstate != "55P03", (
                        f"{command} locked its specific row before the staff root"
                    )
                    raise
                probe.rollback()
            finally:
                holder.rollback()
            pending.result(timeout=20)
    finally:
        probe.close()
        holder.close()
        worker.close()


@pytest.mark.concurrency
def test_mutual_binding_suspension_cannot_remove_all_controllers(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, party_id, root_id, _root_authority = provision_root(admin_conn)
    authority_id, native_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, staff_id, staff_binding = _invite_activate_promote(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        root_id=root_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
    )
    root_binding_row = admin_conn.execute(
        """
        SELECT id, revision FROM request_engine.identity_bindings
         WHERE organization_id = %s AND principal_id = %s AND principal_plane = 'tenant'
        """,
        (organization_id, root_id),
    ).fetchone()
    assert root_binding_row is not None
    root_binding = cast(UUID, root_binding_row[0])
    root_binding_revision = int(root_binding_row[1])
    staff_binding_revision = _binding_revision(admin_conn, staff_binding)
    assert _effective_controller_count(admin_conn, organization_id) == 2

    barrier = threading.Barrier(2)
    results: list[tuple[str, str | None]] = []
    results_lock = threading.Lock()

    def suspend(
        actor_id: UUID,
        target_binding_id: UUID,
        target_revision: int,
        reason: str,
    ) -> None:
        conn = psycopg.connect(pg_conninfo, autocommit=True)
        try:
            set_tenant_actor(conn, organization_id=organization_id, principal_id=actor_id)
            barrier.wait(timeout=15)
            conn.execute(
                """
                SELECT request_engine.transition_identity_binding(%s, %s, 'suspended', %s)
                """,
                (target_binding_id, target_revision, reason),
            )
            outcome: tuple[str, str | None] = ("ok", None)
        except Error as exc:
            outcome = ("error", exc.sqlstate)
        finally:
            conn.close()
        with results_lock:
            results.append(outcome)

    threads = [
        threading.Thread(
            target=suspend,
            args=(root_id, staff_binding, staff_binding_revision, f"race-root:{uuid4().hex}"),
        ),
        threading.Thread(
            target=suspend,
            args=(staff_id, root_binding, root_binding_revision, f"race-staff:{uuid4().hex}"),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(result[0] for result in results) == ["error", "ok"]
    loser = next(sqlstate for status, sqlstate in results if status == "error")
    assert loser != "40P01", "the binding lifecycle inverted the staff lock order"
    assert loser in {"23514", "40001", "42501"}, loser

    statuses = admin_conn.execute(
        """
        SELECT id, status FROM request_engine.identity_bindings
         WHERE id IN (%s, %s)
        """,
        (root_binding, staff_binding),
    ).fetchall()
    assert sorted(str(status[1]) for status in statuses) == ["active", "suspended"]
    assert _effective_controller_count(admin_conn, organization_id) >= 1
