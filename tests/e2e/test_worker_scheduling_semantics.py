from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


def test_app_runtime_cannot_execute_worker_claim_surface(
    app_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    with (
        support.runtime_conn(app_runtime_credentials) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
        ).fetchall()


def test_worker_claim_argument_bounds_are_enforced(
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    with support.runtime_conn(worker_runtime_credentials) as conn:
        for query in (
            "SELECT * FROM request_cmd.claim_scheduled_actions(0, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(501, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '0 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '16 minutes')",
        ):
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                conn.execute(query).fetchall()


def test_runtime_roles_have_no_delete_privilege(
    app_runtime_credentials: support.RuntimeCredentialsLike,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    for credentials in (app_runtime_credentials, worker_runtime_credentials):
        with (
            support.runtime_conn(credentials) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute("DELETE FROM request_engine.scheduled_actions WHERE false")


def test_worker_security_definer_functions_pin_trusted_search_path(
    e2e_admin_conn: support.PgConnection,
) -> None:
    rows = e2e_admin_conn.execute(
        """
        SELECT p.proname, p.prosecdef, p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_cmd'
          AND p.proname IN (
              'claim_scheduled_actions',
              'complete_scheduled_action',
              'retry_scheduled_action',
              'dead_letter_scheduled_action'
          )
        ORDER BY p.proname
        """
    ).fetchall()
    assert len(rows) == 4
    for _, security_definer, config in rows:
        assert security_definer is True
        assert config is not None
        assert "search_path=pg_catalog, request_engine, pg_temp" in config

    invoker = e2e_admin_conn.execute(
        """
        SELECT p.prosecdef
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_cmd'
          AND p.proname = 'acquire_idempotency'
        """
    ).fetchone()
    assert invoker == (False,)


def test_worker_direct_read_is_denied_but_claim_discovers_tenant_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "worker-rls")
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(2000, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT count(*) FROM request_engine.scheduled_actions WHERE id = %s",
                (action_id,),
            ).fetchone()

        claimed = support.claim_scheduled(conn, 1)
        assert len(claimed) == 1
        assert claimed[0][0] == action_id
        assert claimed[0][1] == organization_id
        assert claimed[0][9] == 1
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (claimed[0][0], claimed[0][2]),
        ).fetchone() == (True,)


def test_scheduled_claims_due_work_across_tenants_and_ignores_future_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org_a = support.new_org(e2e_admin_conn, "scheduled-a")
    org_b = support.new_org(e2e_admin_conn, "scheduled-b")
    due_at = datetime(2001, 1, 1, tzinfo=UTC)
    future_at = datetime(2099, 1, 1, tzinfo=UTC)
    due_ids = {
        support.insert_scheduled_action(e2e_admin_conn, org_a, when=due_at),
        support.insert_scheduled_action(e2e_admin_conn, org_b, when=due_at),
    }
    future_id = support.insert_scheduled_action(e2e_admin_conn, org_a, when=future_at)

    with support.runtime_conn(worker_runtime_credentials) as conn:
        claimed = support.claim_scheduled(conn, 2)
        assert {cast(UUID, row[0]) for row in claimed} == due_ids
        assert {cast(UUID, row[1]) for row in claimed} == {org_a, org_b}
        assert all(row[9] == 1 for row in claimed)
        for row in claimed:
            assert conn.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)

    assert e2e_admin_conn.execute(
        "SELECT status, attempt_count FROM request_engine.scheduled_actions WHERE id = %s",
        (future_id,),
    ).fetchone() == ("pending", 0)


def test_two_workers_claim_disjoint_scheduled_batches_under_contention(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-race")
    due_at = datetime(1990, 1, 1, tzinfo=UTC)
    expected = {
        support.insert_scheduled_action(e2e_admin_conn, organization_id, when=due_at)
        for _ in range(16)
    }
    barrier = threading.Barrier(2)

    def claim_batch() -> list[tuple[Any, ...]]:
        with support.runtime_conn(worker_runtime_credentials) as conn:
            barrier.wait(timeout=10)
            return support.claim_scheduled(conn, 8)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim_batch)
        second_future = executor.submit(claim_batch)
        first = first_future.result(timeout=10)
        second = second_future.result(timeout=10)

    first_ids = {cast(UUID, row[0]) for row in first}
    second_ids = {cast(UUID, row[0]) for row in second}
    assert len(first_ids) == 8
    assert len(second_ids) == 8
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == expected

    with support.runtime_conn(worker_runtime_credentials) as conn:
        for row in first + second:
            assert conn.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)


def test_scheduled_claim_token_is_single_use_and_stale_safe(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-token")
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1985, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        row = support.claim_scheduled(conn, 1)[0]
        real_token = cast(UUID, row[2])
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, uuid4()),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, real_token),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, real_token),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, completed_at IS NOT NULL
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("completed", None, None, True)


@pytest.mark.concurrency
def test_scheduled_retry_exhaustion_becomes_dead_and_cannot_be_reclaimed(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-retry")
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1980, 1, 1, tzinfo=UTC),
        max_attempts=2,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        first = support.claim_scheduled(conn, 1)[0]
        assert first[9] == 1
        assert conn.execute(
            "SELECT request_cmd.retry_scheduled_action(%s, %s, %s, %s)",
            (action_id, first[2], datetime(1979, 1, 1, tzinfo=UTC), "transient"),
        ).fetchone() == ("pending",)

        second = support.claim_scheduled(conn, 1)[0]
        assert second[9] == 2
        assert conn.execute(
            "SELECT request_cmd.retry_scheduled_action(%s, %s, %s, %s)",
            (action_id, second[2], datetime(1978, 1, 1, tzinfo=UTC), "still_broken"),
        ).fetchone() == ("dead",)
        assert all(row[0] != action_id for row in support.claim_scheduled(conn, 1))

    assert e2e_admin_conn.execute(
        """
        SELECT status, attempt_count, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("dead", 2, "still_broken")


@pytest.mark.concurrency
def test_expired_scheduled_lease_is_reclaimed_after_simulated_worker_crash(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-crash")
    stale_token = uuid4()
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1970, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1970, 1, 2, tzinfo=UTC),
        attempt_count=1,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        reclaimed = support.claim_scheduled(conn, 1)[0]
        assert reclaimed[0] == action_id
        assert reclaimed[2] != stale_token
        assert reclaimed[9] == 2
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, stale_token),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, reclaimed[2]),
        ).fetchone() == (True,)


def test_scheduled_dead_letter_is_terminal_and_token_guarded(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-dead-letter")
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1960, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        claimed = support.claim_scheduled(conn, 1)[0]
        assert conn.execute(
            "SELECT request_cmd.dead_letter_scheduled_action(%s, %s, %s)",
            (action_id, uuid4(), "wrong_token"),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.dead_letter_scheduled_action(%s, %s, %s)",
            (action_id, claimed[2], "permanent"),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT request_cmd.dead_letter_scheduled_action(%s, %s, %s)",
            (action_id, claimed[2], "duplicate"),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("dead", "permanent")


def test_due_pre_exhausted_scheduled_action_is_auto_dead_before_claim(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-pre-exhausted")
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1950, 1, 1, tzinfo=UTC),
        attempt_count=3,
        max_attempts=3,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        assert all(row[0] != action_id for row in support.claim_scheduled(conn, 1))

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("dead", None, None, "max_attempts_exhausted")


def test_expired_pre_exhausted_scheduled_lease_is_auto_dead_and_unfenced(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "scheduled-exhausted-lease")
    stale_token = uuid4()
    action_id = support.insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1940, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1940, 1, 2, tzinfo=UTC),
        attempt_count=4,
        max_attempts=4,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        assert all(row[0] != action_id for row in support.claim_scheduled(conn, 1))
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, stale_token),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("dead", None, None, "max_attempts_exhausted")
