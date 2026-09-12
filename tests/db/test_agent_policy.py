import threading
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    provision_agent,
    provision_root,
    reset_actor,
    set_tenant_actor,
    transition_agent,
    workload_authority,
)
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

_MANAGE_POLICY_CAPABILITY = "agent.manage_policy"
_PARTIES_REGISTER = "parties.register"
_PARTIES_LOOKUP = "parties.lookup"
_TIMEOUT_SECONDS = 30.0

_FIRST_WINDOW = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)
_LATER_WINDOW = datetime(2030, 1, 7, 13, 1, tzinfo=UTC)

_CONSUME_MUTATION_SQL = """
    INSERT INTO request_engine.agent_budget_windows
        (organization_id, agent_principal_id, window_started_at, mutation_count)
    VALUES (%s, %s, %s, 1)
    ON CONFLICT (organization_id, agent_principal_id, window_started_at)
    DO UPDATE SET
        mutation_count = request_engine.agent_budget_windows.mutation_count + 1
    WHERE request_engine.agent_budget_windows.mutation_count < %s
    RETURNING mutation_count
"""


def _grant_policy_authority(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
) -> None:
    for capability in ("agent.policy.read", _MANAGE_POLICY_CAPABILITY):
        conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                %s, %s, 'tenant', 'tenant_control', %s, false, %s,
                'authority_management', %s
            )
            """,
            (
                organization_id,
                controller_id,
                capability,
                controller_id,
                f"agent-policy-grant:{uuid4().hex}",
            ),
        )


def _policy_world(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    organization_id, _party_id, controller_id, _authority_id = provision_root(conn)
    workload_authority_id = workload_authority(conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )
    _grant_policy_authority(conn, organization_id=organization_id, controller_id=controller_id)
    return organization_id, controller_id, agent_principal_id


def _upsert_policy(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    agent_principal_id: UUID,
    allowed: tuple[str, ...],
    denied: tuple[str, ...] = (),
    risk_ceiling: str = "low_impact_write",
    max_mutations_per_minute: int = 30,
    provenance: str | None = None,
) -> int:
    set_tenant_actor(conn, organization_id=organization_id, principal_id=controller_id)
    try:
        row = conn.execute(
            "SELECT request_engine.upsert_agent_policy(%s, %s, %s, %s, %s, %s)",
            (
                agent_principal_id,
                list(allowed),
                list(denied),
                risk_ceiling,
                max_mutations_per_minute,
                provenance or f"agent-policy:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        reset_actor(conn)


def _policy_row(
    conn: PgConnection,
    *,
    organization_id: UUID,
    agent_principal_id: UUID,
) -> tuple[object, ...] | None:
    return conn.execute(
        """
        SELECT allowed_capabilities, denied_capabilities, risk_ceiling,
               max_mutations_per_minute, policy_revision, provenance_reference
          FROM request_engine.agent_policies
         WHERE organization_id = %s AND agent_principal_id = %s
        """,
        (organization_id, agent_principal_id),
    ).fetchone()


def test_agent_policy_upsert_creates_row_then_replace_bumps_revision(
    admin_conn: PgConnection,
) -> None:
    organization_id, controller_id, agent_principal_id = _policy_world(admin_conn)

    revision = _upsert_policy(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        allowed=(_PARTIES_REGISTER, _PARTIES_LOOKUP),
        risk_ceiling="low_impact_write",
        max_mutations_per_minute=30,
        provenance="agent-policy:create-proof",
    )
    assert revision == 1
    assert _policy_row(
        admin_conn, organization_id=organization_id, agent_principal_id=agent_principal_id
    ) == (
        [_PARTIES_REGISTER, _PARTIES_LOOKUP],
        [],
        "low_impact_write",
        30,
        1,
        "agent-policy:create-proof",
    )

    revision = _upsert_policy(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        allowed=(_PARTIES_LOOKUP,),
        denied=(_PARTIES_REGISTER,),
        risk_ceiling="read",
        max_mutations_per_minute=5,
        provenance="agent-policy:replace-proof",
    )
    assert revision == 2
    assert _policy_row(
        admin_conn, organization_id=organization_id, agent_principal_id=agent_principal_id
    ) == (
        [_PARTIES_LOOKUP],
        [_PARTIES_REGISTER],
        "read",
        5,
        2,
        "agent-policy:replace-proof",
    )


def test_agent_policy_upsert_rejects_invalid_policy_inputs(admin_conn: PgConnection) -> None:
    organization_id, controller_id, agent_principal_id = _policy_world(admin_conn)

    invalid_calls: list[tuple[tuple[str, ...], tuple[str, ...], str, int, str]] = [
        # allowed ∩ denied overlap
        ((_PARTIES_REGISTER,), (_PARTIES_REGISTER,), "low_impact_write", 30, "agent-policy:x"),
        # invalid risk ceilings, including the agent-banned class
        ((_PARTIES_REGISTER,), (), "authority_change", 30, "agent-policy:x"),
        ((_PARTIES_REGISTER,), (), "nonsense", 30, "agent-policy:x"),
        # non-positive budgets
        ((_PARTIES_REGISTER,), (), "low_impact_write", 0, "agent-policy:x"),
        ((_PARTIES_REGISTER,), (), "low_impact_write", -1, "agent-policy:x"),
        # blank provenance
        ((_PARTIES_REGISTER,), (), "low_impact_write", 30, "   "),
        # blank capability keys
        (("   ",), (), "low_impact_write", 30, "agent-policy:x"),
        ((_PARTIES_REGISTER,), ("",), "low_impact_write", 30, "agent-policy:x"),
    ]
    set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=controller_id)
    try:
        for call in invalid_calls:
            with pytest.raises(Error) as rejected:
                admin_conn.execute(
                    "SELECT request_engine.upsert_agent_policy(%s, %s, %s, %s, %s, %s)",
                    (
                        agent_principal_id,
                        list(call[0]),
                        list(call[1]),
                        call[2],
                        call[3],
                        call[4],
                    ),
                )
            assert rejected.value.sqlstate == "22023", call
    finally:
        reset_actor(admin_conn)


def test_agent_policy_upsert_requires_granted_actor_and_known_profile(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    with pytest.raises(Error) as ungranted:
        _upsert_policy(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            allowed=(_PARTIES_LOOKUP,),
        )
    assert ungranted.value.sqlstate == "42501"

    _grant_policy_authority(
        admin_conn, organization_id=organization_id, controller_id=controller_id
    )
    assert (
        _upsert_policy(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            allowed=(_PARTIES_LOOKUP,),
        )
        == 1
    )

    with pytest.raises(Error) as unknown_profile:
        _upsert_policy(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=uuid4(),
            allowed=(_PARTIES_LOOKUP,),
        )
    assert unknown_profile.value.sqlstate == "P0002"


def test_agent_policy_upsert_denies_suspended_agent(admin_conn: PgConnection) -> None:
    organization_id, controller_id, agent_principal_id = _policy_world(admin_conn)
    assert (
        transition_agent(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            expected_revision=1,
            target_status="active",
        )
        == 2
    )
    suspended = transition_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        expected_revision=2,
        target_status="suspended",
    )
    assert suspended == 3

    with pytest.raises(Error) as denied:
        _upsert_policy(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            allowed=(_PARTIES_LOOKUP,),
        )
    assert denied.value.sqlstate == "55000"


def test_agent_policies_are_tenant_isolated(admin_conn: PgConnection) -> None:
    first_org, controller_id, agent_principal_id = _policy_world(admin_conn)
    second_org, _second_party, second_controller, _second_authority = provision_root(admin_conn)
    _grant_policy_authority(admin_conn, organization_id=second_org, controller_id=second_controller)

    set_tenant_actor(admin_conn, organization_id=second_org, principal_id=second_controller)
    try:
        visible = admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.agent_policies
             WHERE agent_principal_id = %s
            """,
            (agent_principal_id,),
        ).fetchone()
        assert visible is not None
        assert int(visible[0]) == 0

        with pytest.raises(Error) as foreign_write:
            admin_conn.execute(
                "SELECT request_engine.upsert_agent_policy(%s, %s, %s, %s, %s, %s)",
                (
                    agent_principal_id,
                    [_PARTIES_LOOKUP],
                    [],
                    "read",
                    30,
                    f"agent-policy:{uuid4().hex}",
                ),
            )
        assert foreign_write.value.sqlstate == "P0002"
    finally:
        reset_actor(admin_conn)

    assert (
        _upsert_policy(
            admin_conn,
            organization_id=first_org,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            allowed=(_PARTIES_LOOKUP,),
        )
        == 1
    )


def _wait_for_lock_wait(admin_conn: PgConnection, blocked_pid: int) -> None:
    for _ in range(300):
        row = admin_conn.execute(
            """
            SELECT 1
              FROM pg_locks AS waiting
             WHERE waiting.pid = %s
               AND NOT waiting.granted
             LIMIT 1
            """,
            (blocked_pid,),
        ).fetchone()
        if row is not None:
            return
        threading.Event().wait(0.1)
    raise RuntimeError("expected budget consumer never blocked on the window row")


def test_concurrent_budget_window_consumption_admits_exactly_one(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, controller_id, agent_principal_id = _policy_world(admin_conn)
    assert (
        _upsert_policy(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            agent_principal_id=agent_principal_id,
            allowed=(_PARTIES_REGISTER, _PARTIES_LOOKUP),
            max_mutations_per_minute=1,
        )
        == 1
    )

    holder = PgConnection.connect(pg_conninfo)
    contender = PgConnection.connect(pg_conninfo, autocommit=True)
    try:
        set_tenant_actor(holder, organization_id=organization_id, principal_id=controller_id)
        winner = holder.execute(
            _CONSUME_MUTATION_SQL,
            (organization_id, agent_principal_id, _FIRST_WINDOW, 1),
        ).fetchone()
        assert winner is not None and int(winner[0]) == 1

        outcome: list[bool] = []
        started = threading.Event()

        def _contend() -> None:
            started.set()
            set_tenant_actor(contender, organization_id=organization_id, principal_id=controller_id)
            try:
                row = contender.execute(
                    _CONSUME_MUTATION_SQL,
                    (organization_id, agent_principal_id, _FIRST_WINDOW, 1),
                ).fetchone()
                outcome.append(row is not None)
            finally:
                reset_actor(contender)

        thread = threading.Thread(target=_contend)
        thread.start()
        started.wait(_TIMEOUT_SECONDS)
        _wait_for_lock_wait(admin_conn, contender.info.backend_pid)
        holder.commit()
        thread.join(_TIMEOUT_SECONDS)
        assert not thread.is_alive()

        assert outcome == [False]
    finally:
        holder.close()
        contender.close()

    window = admin_conn.execute(
        """
        SELECT mutation_count
          FROM request_engine.agent_budget_windows
         WHERE organization_id = %s AND agent_principal_id = %s
           AND window_started_at = %s
        """,
        (organization_id, agent_principal_id, _FIRST_WINDOW),
    ).fetchone()
    assert window == (1,)

    set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=controller_id)
    try:
        later = admin_conn.execute(
            _CONSUME_MUTATION_SQL,
            (organization_id, agent_principal_id, _LATER_WINDOW, 1),
        ).fetchone()
        assert later is not None and int(later[0]) == 1
    finally:
        reset_actor(admin_conn)
