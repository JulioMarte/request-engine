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


def test_app_runtime_cannot_execute_outbox_claim_surface(
    app_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    with (
        support.runtime_conn(app_runtime_credentials) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')"
        ).fetchall()


def test_outbox_claim_argument_bounds_are_enforced(
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    with support.runtime_conn(worker_runtime_credentials) as conn:
        for query in (
            "SELECT * FROM request_cmd.claim_outbox_messages(0, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(501, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '0 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '16 minutes')",
        ):
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                conn.execute(query).fetchall()


def test_worker_direct_outbox_read_is_rls_scoped_but_claim_discovers_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-rls")
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1910, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        direct = conn.execute(
            "SELECT count(*) FROM request_engine.outbox_messages WHERE id = %s",
            (message_id,),
        ).fetchone()
        assert direct == (0,)

        claimed = support.claim_outbox(conn, 1)
        assert len(claimed) == 1
        assert claimed[0][0] == message_id
        assert claimed[0][1] == organization_id
        assert claimed[0][8] == 1
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, claimed[0][2]),
        ).fetchone() == (True,)


def test_outbox_claims_due_work_across_tenants_and_ignores_future_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org_a = support.new_org(e2e_admin_conn, "outbox-a")
    org_b = support.new_org(e2e_admin_conn, "outbox-b")
    due_at = datetime(1900, 1, 1, tzinfo=UTC)
    future_at = datetime(2099, 1, 1, tzinfo=UTC)
    due_ids = {
        support.insert_outbox_message(e2e_admin_conn, org_a, when=due_at),
        support.insert_outbox_message(e2e_admin_conn, org_b, when=due_at),
    }
    future_id = support.insert_outbox_message(e2e_admin_conn, org_a, when=future_at)

    with support.runtime_conn(worker_runtime_credentials) as conn:
        claimed = support.claim_outbox(conn, 2)
        assert {cast(UUID, row[0]) for row in claimed} == due_ids
        assert {cast(UUID, row[1]) for row in claimed} == {org_a, org_b}
        assert all(row[8] == 1 for row in claimed)
        for row in claimed:
            assert conn.execute(
                "SELECT request_cmd.complete_outbox_message(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)

    assert e2e_admin_conn.execute(
        "SELECT status, attempt_count FROM request_engine.outbox_messages WHERE id = %s",
        (future_id,),
    ).fetchone() == ("pending", 0)


def test_two_workers_claim_disjoint_outbox_batches_under_contention(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-race")
    due_at = datetime(1890, 1, 1, tzinfo=UTC)
    expected = {
        support.insert_outbox_message(e2e_admin_conn, organization_id, when=due_at)
        for _ in range(20)
    }
    barrier = threading.Barrier(2)

    def claim_batch() -> list[tuple[Any, ...]]:
        with support.runtime_conn(worker_runtime_credentials) as conn:
            barrier.wait()
            return support.claim_outbox(conn, 10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim_batch)
        second_future = executor.submit(claim_batch)
        first = first_future.result()
        second = second_future.result()

    first_ids = {cast(UUID, row[0]) for row in first}
    second_ids = {cast(UUID, row[0]) for row in second}
    assert len(first_ids) == 10
    assert len(second_ids) == 10
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == expected

    with support.runtime_conn(worker_runtime_credentials) as conn:
        for row in first + second:
            assert conn.execute(
                "SELECT request_cmd.complete_outbox_message(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)


def test_outbox_claim_token_is_single_use_and_delivery_is_terminal(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-token")
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1880, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        claimed = support.claim_outbox(conn, 1)[0]
        real_token = cast(UUID, claimed[2])
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, uuid4()),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, real_token),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, real_token),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, delivered_at IS NOT NULL
        FROM request_engine.outbox_messages
        WHERE id = %s
        """,
        (message_id,),
    ).fetchone() == ("delivered", None, None, True)


def test_outbox_retry_exhaustion_and_stale_token_semantics(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-retry")
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1870, 1, 1, tzinfo=UTC),
        max_attempts=2,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        first = support.claim_outbox(conn, 1)[0]
        assert first[8] == 1
        assert conn.execute(
            "SELECT request_cmd.retry_outbox_message(%s, %s, %s, %s)",
            (message_id, uuid4(), datetime(1869, 1, 1, tzinfo=UTC), "wrong_token"),
        ).fetchone() == ("stale",)
        assert conn.execute(
            "SELECT request_cmd.retry_outbox_message(%s, %s, %s, %s)",
            (message_id, first[2], datetime(1869, 1, 1, tzinfo=UTC), "provider_503"),
        ).fetchone() == ("pending",)

        second = support.claim_outbox(conn, 1)[0]
        assert second[8] == 2
        assert conn.execute(
            "SELECT request_cmd.retry_outbox_message(%s, %s, %s, %s)",
            (message_id, second[2], datetime(1868, 1, 1, tzinfo=UTC), "provider_503"),
        ).fetchone() == ("dead",)

    assert e2e_admin_conn.execute(
        """
        SELECT status, attempt_count, last_error_class
        FROM request_engine.outbox_messages
        WHERE id = %s
        """,
        (message_id,),
    ).fetchone() == ("dead", 2, "provider_503")


@pytest.mark.concurrency
def test_expired_outbox_lease_is_reclaimed_after_simulated_worker_crash(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-crash")
    stale_token = uuid4()
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1860, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1860, 1, 2, tzinfo=UTC),
        attempt_count=3,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        reclaimed = support.claim_outbox(conn, 1)[0]
        assert reclaimed[0] == message_id
        assert reclaimed[2] != stale_token
        assert reclaimed[8] == 4
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, stale_token),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, reclaimed[2]),
        ).fetchone() == (True,)


def test_outbox_dead_letter_is_terminal_and_token_guarded(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-dead-letter")
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1850, 1, 1, tzinfo=UTC),
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        claimed = support.claim_outbox(conn, 1)[0]
        assert conn.execute(
            "SELECT request_cmd.dead_letter_outbox_message(%s, %s, %s)",
            (message_id, uuid4(), "wrong_token"),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.dead_letter_outbox_message(%s, %s, %s)",
            (message_id, claimed[2], "invalid_destination"),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT request_cmd.dead_letter_outbox_message(%s, %s, %s)",
            (message_id, claimed[2], "duplicate"),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.outbox_messages WHERE id = %s",
        (message_id,),
    ).fetchone() == ("dead", "invalid_destination")


def test_due_pre_exhausted_outbox_message_is_auto_dead_before_claim(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-pre-exhausted")
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1840, 1, 1, tzinfo=UTC),
        attempt_count=5,
        max_attempts=5,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        assert all(row[0] != message_id for row in support.claim_outbox(conn, 1))

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.outbox_messages
        WHERE id = %s
        """,
        (message_id,),
    ).fetchone() == ("dead", None, None, "max_attempts_exhausted")


def test_expired_pre_exhausted_outbox_lease_is_auto_dead_and_unfenced(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "outbox-exhausted-lease")
    stale_token = uuid4()
    message_id = support.insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1830, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1830, 1, 2, tzinfo=UTC),
        attempt_count=6,
        max_attempts=6,
    )

    with support.runtime_conn(worker_runtime_credentials) as conn:
        assert all(row[0] != message_id for row in support.claim_outbox(conn, 1))
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, stale_token),
        ).fetchone() == (False,)

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.outbox_messages
        WHERE id = %s
        """,
        (message_id,),
    ).fetchone() == ("dead", None, None, "max_attempts_exhausted")
