import threading
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    provision_agent,
    provision_root,
    reset_actor,
    set_tenant_actor,
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

_BOOKING_CAPABILITY = "appointments.book"
_TIMEOUT_SECONDS = 30.0


def _wait_for_lock_wait(
    admin_conn: PgConnection,
    blocked_pid: int,
) -> None:
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
    raise RuntimeError("expected statement never blocked on the revoked grant row")


def _agent_world(
    admin_conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID]:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_BOOKING_CAPABILITY,
        authority_plane="operational",
    )
    return organization_id, controller_id, agent_principal_id, workload_authority_id


def test_concurrent_delegable_grant_revocation_fails_agent_authority_replacement_closed(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, controller_id, agent_principal_id, _workload = _agent_world(admin_conn)

    revoker = PgConnection.connect(pg_conninfo)
    contender = PgConnection.connect(pg_conninfo, autocommit=True)
    try:
        revoker.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        revoker.execute(
            """
            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = %s
             WHERE organization_id = %s
               AND principal_id = %s
               AND capability_key = %s
               AND status = 'active'
            """,
            (controller_id, organization_id, controller_id, _BOOKING_CAPABILITY),
        )

        outcome: list[Error | int] = []
        started = threading.Event()

        def _contend() -> None:
            started.set()
            set_tenant_actor(
                contender,
                organization_id=organization_id,
                principal_id=controller_id,
            )
            try:
                row = contender.execute(
                    "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
                    (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
                ).fetchone()
                outcome.append(int(row[0]) if row is not None else 0)
            except Error as exc:
                outcome.append(exc)
            finally:
                reset_actor(contender)

        thread = threading.Thread(target=_contend)
        thread.start()
        started.wait(_TIMEOUT_SECONDS)
        _wait_for_lock_wait(admin_conn, contender.info.backend_pid)
        revoker.commit()
        thread.join(_TIMEOUT_SECONDS)
        assert not thread.is_alive()

        assert len(outcome) == 1
        result = outcome[0]
        assert isinstance(result, Error)
        assert result.sqlstate == "42501"
    finally:
        revoker.close()
        contender.close()

    live_grants = admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active'
        """,
        (agent_principal_id,),
    ).fetchone()
    assert live_grants is not None
    assert int(live_grants[0]) == 0


def test_concurrent_delegable_grant_revocation_fails_delegation_creation_closed(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, controller_id, agent_principal_id, _workload = _agent_world(admin_conn)

    revoker = PgConnection.connect(pg_conninfo)
    contender = PgConnection.connect(pg_conninfo, autocommit=True)
    try:
        revoker.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        revoker.execute(
            """
            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = %s
             WHERE organization_id = %s
               AND principal_id = %s
               AND capability_key = %s
               AND status = 'active'
            """,
            (controller_id, organization_id, controller_id, _BOOKING_CAPABILITY),
        )

        outcome: list[Error | UUID] = []
        started = threading.Event()
        delegation_id = uuid4()

        def _contend() -> None:
            started.set()
            set_tenant_actor(
                contender,
                organization_id=organization_id,
                principal_id=controller_id,
            )
            try:
                contender.execute(
                    """
                    SELECT request_engine.create_delegation(
                        %s, %s, %s, %s, %s,
                        clock_timestamp(),
                        clock_timestamp() + interval '1 hour',
                        %s
                    )
                    """,
                    (
                        delegation_id,
                        controller_id,
                        agent_principal_id,
                        "concurrent delegation attempt",
                        [_BOOKING_CAPABILITY],
                        f"delegation:{uuid4().hex}",
                    ),
                )
                outcome.append(delegation_id)
            except Error as exc:
                outcome.append(exc)
            finally:
                reset_actor(contender)

        thread = threading.Thread(target=_contend)
        thread.start()
        started.wait(_TIMEOUT_SECONDS)
        _wait_for_lock_wait(admin_conn, contender.info.backend_pid)
        revoker.commit()
        thread.join(_TIMEOUT_SECONDS)
        assert not thread.is_alive()

        assert len(outcome) == 1
        result = outcome[0]
        assert isinstance(result, Error)
        assert result.sqlstate == "42501"
    finally:
        revoker.close()
        contender.close()

    live_delegations = admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.delegations
         WHERE delegate_principal_id = %s AND status = 'active'
        """,
        (agent_principal_id,),
    ).fetchone()
    assert live_delegations is not None
    assert int(live_delegations[0]) == 0
