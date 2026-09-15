"""Identity-topology gate: complete writer inventory, ordering and containment.

The gate is the transaction-scoped advisory pair (1380274257, 1902476357). These
proofs protect three claims:

- every command that can alter identity bindings, control grants or staff
  memberships acquires the gate as its first statement, before any row lock;
- ordinary reads and native login never wait on the gate;
- the existing tenant lock root keeps at least one effective controller when two
  controllers try to remove each other concurrently.
"""

import re
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
    set_tenant_actor,
)
from native_authority_gate_support import wait_for_lock_wait
from psycopg import Connection, Error, sql

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

_GATE_SHARE = "request_engine.acquire_identity_topology_share()"
_GATE_EXCLUSIVE = "request_engine.acquire_identity_topology_exclusive()"

# Complete inventory: every function whose own body writes one of the four
# topology tables, plus the public integration wrappers that lock a Principal
# before delegating to their gated ``*_state`` implementation.
_GATED_DML_WRITERS: dict[tuple[str, str], str] = {
    ("request_engine", "invite_native_staff"): _GATE_SHARE,
    ("request_engine", "provision_agent"): _GATE_SHARE,
    ("request_engine", "provision_integration_state"): _GATE_SHARE,
    ("request_engine", "replace_agent_authority"): _GATE_SHARE,
    ("request_engine", "replace_integration_authority_state"): _GATE_SHARE,
    ("request_engine", "replace_staff_authority"): _GATE_SHARE,
    ("request_engine", "set_integration_status_state"): _GATE_SHARE,
    ("request_engine", "transition_agent_profile"): _GATE_SHARE,
    ("request_engine", "transition_identity_binding"): _GATE_SHARE,
    ("request_engine", "transition_staff_membership"): _GATE_SHARE,
    ("request_platform", "establish_root"): _GATE_EXCLUSIVE,
    ("request_platform", "provision_native_organization_root"): _GATE_SHARE,
    ("request_platform", "provision_native_tenant_provisioner"): _GATE_SHARE,
    ("request_platform", "provision_tenant_provisioner"): _GATE_SHARE,
    ("request_platform", "transition_native_platform_provisioner"): _GATE_SHARE,
}

_GATED_WRAPPERS: dict[tuple[str, str], tuple[str, str]] = {
    ("request_engine", "provision_integration"): (
        _GATE_SHARE,
        "request_engine.provision_integration_state(",
    ),
    ("request_engine", "replace_integration_authority"): (
        _GATE_SHARE,
        "request_engine.replace_integration_authority_state(",
    ),
    ("request_engine", "set_integration_status"): (
        _GATE_SHARE,
        "request_engine.set_integration_status_state(",
    ),
}

_GATED_WRITERS = {
    **_GATED_DML_WRITERS,
    **{key: gate for key, (gate, _delegate) in _GATED_WRAPPERS.items()},
}

# Trigger functions fire from the gated organization-root transaction and are not
# independently callable by runtime roles; they must not carry a late gate.
_TRIGGER_WRITERS = {
    ("request_engine", "seed_initial_controller_policy"),
    ("request_engine", "seed_root_staff_membership"),
    ("request_engine", "seed_root_staff_read_authority"),
}

_DIRECT_DML = re.compile(
    r"(insert\s+into|update|delete\s+from)\s+"
    r"(request_engine\.|request_platform\.)?"
    r"(identity_bindings|principal_authority_grants|staff_memberships|representations)"
    r"([^a-zA-Z_]|$)",
    re.IGNORECASE,
)
_BEGIN_LINE = re.compile(r"^[ \t]*BEGIN[ \t]*$", re.MULTILINE)

_WRITER_CALLS: tuple[tuple[str, int], ...] = (
    ("request_engine.invite_native_staff", 7),
    ("request_engine.provision_agent", 13),
    ("request_engine.provision_integration", 9),
    ("request_engine.provision_integration_state", 9),
    ("request_engine.replace_agent_authority", 4),
    ("request_engine.replace_integration_authority", 4),
    ("request_engine.replace_integration_authority_state", 4),
    ("request_engine.replace_staff_authority", 4),
    ("request_engine.set_integration_status", 4),
    ("request_engine.set_integration_status_state", 4),
    ("request_engine.transition_agent_profile", 4),
    ("request_engine.transition_identity_binding", 4),
    ("request_engine.transition_staff_membership", 4),
    ("request_platform.establish_root", 9),
    ("request_platform.provision_native_organization_root", 8),
    ("request_platform.provision_native_tenant_provisioner", 5),
    ("request_platform.provision_tenant_provisioner", 3),
    ("request_platform.transition_native_platform_provisioner", 7),
)

_CONTROL_CAPABILITIES = (
    "staff.manage_membership",
    "staff.manage_authority",
    "identity.bind",
)


def _first_statement(prosrc: str) -> str:
    begin_match = _BEGIN_LINE.search(prosrc)
    assert begin_match is not None
    return prosrc[begin_match.end() :].lstrip().split(";", 1)[0].strip()


def _backend_pid(conn: PgConnection) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return cast(int, row[0])


def _hold_gate(conn: PgConnection, function_name: str) -> int:
    pid = _backend_pid(conn)
    conn.execute(sql.SQL("SELECT request_engine.{}()").format(sql.Identifier(function_name)))
    return pid


def _function_bodies(conn: PgConnection) -> dict[tuple[str, str], str]:
    rows = conn.execute(
        """
        SELECT n.nspname, p.proname, p.prosrc
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname LIKE 'request_%'
           AND p.prokind = 'f'
        """
    ).fetchall()
    return {(str(schema), str(name)): str(prosrc) for schema, name, prosrc in rows}


def test_writer_inventory_is_complete_and_gate_is_the_first_statement(
    admin_conn: PgConnection,
) -> None:
    bodies = _function_bodies(admin_conn)
    discovered = {key for key, prosrc in bodies.items() if _DIRECT_DML.search(prosrc)}
    assert discovered == set(_GATED_DML_WRITERS) | _TRIGGER_WRITERS, (
        "identity topology writer inventory drifted; classify the new writer "
        "and either gate it or document why it is a trigger-side effect"
    )
    assert {call for call, _arity in _WRITER_CALLS} == {
        f"{schema}.{name}" for schema, name in _GATED_WRITERS
    }
    for key, gate_call in _GATED_DML_WRITERS.items():
        statement = _first_statement(bodies[key])
        assert statement == f"PERFORM {gate_call}", f"{key}: {statement!r}"
    for key, (gate_call, delegates_to) in _GATED_WRAPPERS.items():
        assert key in bodies, f"missing public wrapper {key}"
        statement = _first_statement(bodies[key])
        assert statement == f"PERFORM {gate_call}", f"{key}: {statement!r}"
        assert delegates_to in bodies[key], f"{key} no longer delegates to {delegates_to}"

    triggered = {
        (str(schema), str(name))
        for schema, name in admin_conn.execute(
            """
            SELECT DISTINCT n.nspname, p.proname
              FROM pg_trigger t
              JOIN pg_proc p ON p.oid = t.tgfoid
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE NOT t.tgisinternal
            """
        ).fetchall()
    }
    assert triggered >= _TRIGGER_WRITERS
    for schema, name in _TRIGGER_WRITERS:
        assert "acquire_identity_topology" not in bodies[(schema, name)]


def test_gate_functions_are_a_controlled_definer_surface(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT p.proname,
               pg_get_userbyid(p.proowner),
               p.prosecdef,
               p.proconfig,
               (
                   SELECT bool_or(acl.grantee = 0 AND acl.privilege_type = 'EXECUTE')
                     FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
               ),
               has_function_privilege(
                   'request_platform_control_definer', p.oid, 'EXECUTE'
               ),
               has_function_privilege('request_bootstrap_definer', p.oid, 'EXECUTE'),
               has_function_privilege('request_engine_app', p.oid, 'EXECUTE')
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'request_engine'
           AND p.proname LIKE 'acquire_identity_topology_%'
        """
    ).fetchall()
    assert len(rows) == 2
    for (
        name,
        owner,
        security_definer,
        configuration,
        public_execute,
        control_can_execute,
        bootstrap_can_execute,
        app_can_execute,
    ) in rows:
        assert owner == "request_engine_schema_owner", name
        assert security_definer is True, name
        assert configuration == ["search_path=pg_catalog, request_engine, pg_temp"], name
        assert public_execute is False, name
        assert control_can_execute is True, name
        assert bootstrap_can_execute is True, name
        assert app_can_execute is False, name


def test_runtime_role_cannot_acquire_the_gate(app_role_conn: PgConnection) -> None:
    for function_name in (
        "acquire_identity_topology_share",
        "acquire_identity_topology_exclusive",
    ):
        with pytest.raises(Error) as denied:
            app_role_conn.execute(f"SELECT request_engine.{function_name}()")
        assert denied.value.sqlstate == "42501"
        app_role_conn.rollback()


def test_share_holders_do_not_block_each_other(pg_conninfo: str) -> None:
    first = psycopg.connect(pg_conninfo)
    second = psycopg.connect(pg_conninfo)
    try:
        _hold_gate(first, "acquire_identity_topology_share")
        second.execute("SET statement_timeout = '5s'")
        _hold_gate(second, "acquire_identity_topology_share")
    finally:
        first.rollback()
        first.close()
        second.rollback()
        second.close()


def test_exclusive_and_share_mutually_block(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    share = psycopg.connect(pg_conninfo)
    exclusive = psycopg.connect(pg_conninfo)
    second_share = psycopg.connect(pg_conninfo)
    try:
        share_pid = _hold_gate(share, "acquire_identity_topology_share")
        exclusive_pid = _backend_pid(exclusive)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_exclusive = pool.submit(
                _hold_gate, exclusive, "acquire_identity_topology_exclusive"
            )
            try:
                exclusive_blocked = wait_for_lock_wait(
                    admin_conn, exclusive_pid, blocker_pid=share_pid
                )
            finally:
                share.rollback()
            assert exclusive_blocked
            pending_exclusive.result(timeout=10)

        second_share_pid = _backend_pid(second_share)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_share = pool.submit(_hold_gate, second_share, "acquire_identity_topology_share")
            try:
                share_blocked = wait_for_lock_wait(
                    admin_conn, second_share_pid, blocker_pid=exclusive_pid
                )
            finally:
                exclusive.rollback()
            assert share_blocked
            pending_share.result(timeout=10)
    finally:
        share.rollback()
        share.close()
        exclusive.rollback()
        exclusive.close()
        second_share.rollback()
        second_share.close()


def test_gate_is_transaction_scoped_and_released_on_rollback(pg_conninfo: str) -> None:
    holder = psycopg.connect(pg_conninfo)
    follower = psycopg.connect(pg_conninfo)
    try:
        _hold_gate(holder, "acquire_identity_topology_exclusive")
        holder.rollback()
        follower.execute("SET statement_timeout = '5s'")
        _hold_gate(follower, "acquire_identity_topology_exclusive")
    finally:
        holder.close()
        follower.rollback()
        follower.close()


@pytest.mark.parametrize(
    ("call", "arity"),
    _WRITER_CALLS,
    ids=[call for call, _arity in _WRITER_CALLS],
)
def test_command_entry_points_take_the_gate_before_any_row_lock(
    admin_conn: PgConnection,
    pg_conninfo: str,
    call: str,
    arity: int,
) -> None:
    locker = psycopg.connect(pg_conninfo)
    worker = psycopg.connect(pg_conninfo)
    try:
        locker_pid = _hold_gate(locker, "acquire_identity_topology_exclusive")
        worker_pid = _backend_pid(worker)
        schema_name, _, function_name = call.partition(".")
        statement = sql.SQL("SELECT {}.{}({})").format(
            sql.Identifier(schema_name),
            sql.Identifier(function_name),
            sql.SQL(", ").join(sql.SQL("NULL") for _ in range(arity)),
        )

        def run() -> None:
            try:
                worker.execute(statement)
                worker.commit()
            except Error:
                worker.rollback()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(run)
            try:
                blocked = wait_for_lock_wait(admin_conn, worker_pid, blocker_pid=locker_pid)
                assert blocked, f"{call} did not wait on the identity topology gate"
                row_locks = admin_conn.execute(
                    """
                    SELECT locktype, mode
                      FROM pg_locks
                     WHERE pid = %s
                       AND (
                           locktype IN ('transactionid', 'tuple')
                           OR (
                               locktype = 'relation'
                               AND mode IN (
                                   'RowExclusiveLock', 'RowShareLock',
                                   'ShareRowExclusiveLock', 'ExclusiveLock',
                                   'AccessExclusiveLock'
                               )
                           )
                       )
                    """,
                    (worker_pid,),
                ).fetchall()
                assert row_locks == [], f"{call} held row locks before the gate: {row_locks!r}"
            finally:
                locker.rollback()
            pending.result(timeout=15)
    finally:
        locker.close()
        worker.close()


def test_reads_do_not_wait_on_the_gate(
    pg_conninfo: str,
) -> None:
    locker = psycopg.connect(pg_conninfo)
    reader = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        _hold_gate(locker, "acquire_identity_topology_exclusive")
        reader.execute("SET statement_timeout = '5s'")
        for statement, params in (
            (
                sql.SQL(
                    "SELECT * FROM request_platform.read_platform_provisioners(NULL, NULL, 10)"
                ),
                (),
            ),
            (
                sql.SQL("SELECT * FROM request_platform.read_principal_authority(%s)"),
                (uuid4(),),
            ),
        ):
            try:
                reader.execute(statement, params).fetchall()
            except Error as exc:
                assert exc.sqlstate != "57014", f"read waited on the gate: {statement}"
    finally:
        locker.rollback()
        locker.close()
        reader.close()


def _invite_and_activate(
    conn: PgConnection,
    *,
    organization_id: UUID,
    root_id: UUID,
    party_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
    try:
        returned = conn.execute(
            """
            SELECT request_engine.invite_native_staff(%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"gate-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            """
            SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)
            """,
            (membership_id, f"gate-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
    finally:
        conn.execute("RESET ROLE")
    return membership_id, principal_id


def _promote_to_controller(
    conn: PgConnection,
    *,
    organization_id: UUID,
    root_id: UUID,
    membership_id: UUID,
    staff_id: UUID,
) -> None:
    revision = principal_revision(conn, staff_id)
    set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
    try:
        conn.execute(
            """
            SELECT request_engine.replace_staff_authority(
                %s, %s, %s::text[], %s
            )
            """,
            (
                membership_id,
                revision,
                list(_CONTROL_CAPABILITIES),
                f"gate-controller:{uuid4().hex}",
            ),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")


@pytest.mark.concurrency
def test_mutual_staff_suspension_cannot_remove_all_controllers(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    staff_authority_id, staff_identity_id, _credential_id = native_identity(admin_conn)
    staff_membership_id, staff_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=staff_authority_id,
        native_identity_id=staff_identity_id,
    )
    _promote_to_controller(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        membership_id=staff_membership_id,
        staff_id=staff_id,
    )
    root_row = admin_conn.execute(
        """
        SELECT id, revision FROM request_engine.staff_memberships
         WHERE organization_id = %s AND principal_id = %s
        """,
        (organization_id, root_id),
    ).fetchone()
    assert root_row is not None
    root_membership_id = cast(UUID, root_row[0])
    root_membership_revision = int(root_row[1])

    barrier = threading.Barrier(2)
    results: list[tuple[str, str | None]] = []
    results_lock = threading.Lock()

    def suspend(
        actor_id: UUID,
        target_membership_id: UUID,
        target_revision: int,
        reason: str,
    ) -> None:
        conn = psycopg.connect(pg_conninfo, autocommit=True)
        try:
            conn.execute(
                "SELECT set_config('request_engine.organization_id', %s, false)",
                (str(organization_id),),
            )
            conn.execute(
                "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
                (str(actor_id),),
            )
            conn.execute("SET ROLE request_engine_app")
            barrier.wait(timeout=15)
            conn.execute(
                """
                SELECT request_engine.transition_staff_membership(%s, %s, 'suspended', %s)
                """,
                (target_membership_id, target_revision, reason),
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
            args=(root_id, staff_membership_id, 2, f"gate-mutual-root:{uuid4().hex}"),
        ),
        threading.Thread(
            target=suspend,
            args=(
                staff_id,
                root_membership_id,
                root_membership_revision,
                f"gate-mutual-staff:{uuid4().hex}",
            ),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(result[0] for result in results) == ["error", "ok"]
    loser = next(sqlstate for status, sqlstate in results if status == "error")
    # The ordered staff root is acquired before the specific membership row, so
    # the mutual suspension resolves cleanly instead of through a 40P01 deadlock.
    assert loser in {"40001", "42501", "23514"}, loser

    statuses = admin_conn.execute(
        """
        SELECT status FROM request_engine.staff_memberships
         WHERE organization_id = %s AND principal_id IN (%s, %s)
        """,
        (organization_id, root_id, staff_id),
    ).fetchall()
    assert sorted(str(status[0]) for status in statuses) == ["active", "suspended"]
    effective = admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.staff_memberships AS membership
         WHERE membership.organization_id = %s
           AND membership.status = 'active'
           AND request_engine.principal_is_effective_tenant_controller(
                   %s, membership.principal_id
               )
        """,
        (organization_id, organization_id),
    ).fetchone()
    assert effective is not None
    assert int(effective[0]) >= 1
