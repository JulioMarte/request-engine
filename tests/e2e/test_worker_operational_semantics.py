from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.conninfo import make_conninfo


pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

PgConnection = Connection[Any]
UTC = timezone.utc


class _Credentials(Protocol):
    role_name: str
    password: str


def _runtime_dsn(credentials: _Credentials) -> str:
    return make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "request_engine_v3"),
        user=credentials.role_name,
        password=credentials.password,
    )


def _runtime_conn(credentials: _Credentials) -> PgConnection:
    return psycopg.connect(_runtime_dsn(credentials), autocommit=True)


def _new_org(conn: PgConnection, prefix: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{uuid4().hex}", f"{prefix} organization"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _new_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _new_contact_point(
    conn: PgConnection,
    organization_id: UUID,
    party_id: UUID,
    suffix: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'email', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"{suffix}-{uuid4().hex}@example.test"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _insert_scheduled_action(
    conn: PgConnection,
    organization_id: UUID,
    *,
    when: datetime,
    max_attempts: int = 8,
    status: str = "pending",
    claim_token: UUID | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            subject_kind,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts
        ) VALUES (
            %s, 'e2e', 'probe', 'test', '{}'::jsonb, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            f"e2e-scheduled-{uuid4().hex}",
            when,
            when,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _insert_outbox_message(
    conn: PgConnection,
    organization_id: UUID,
    *,
    when: datetime,
    max_attempts: int = 12,
    status: str = "pending",
    claim_token: UUID | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id,
            event_type,
            payload,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
            next_attempt_at
        ) VALUES (
            %s, 'e2e.probe.v1', '{}'::jsonb, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
            when,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _claim_scheduled(conn: PgConnection, limit: int) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            "SELECT * FROM request_cmd.claim_scheduled_actions(%s, %s)",
            (limit, timedelta(seconds=30)),
        ).fetchall()
    )


def _claim_outbox(conn: PgConnection, limit: int) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            "SELECT * FROM request_cmd.claim_outbox_messages(%s, %s)",
            (limit, timedelta(seconds=30)),
        ).fetchall()
    )


def test_app_runtime_cannot_cross_tenant_claim_worker_surfaces(
    app_runtime_credentials: _Credentials,
) -> None:
    with _runtime_conn(app_runtime_credentials) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
            ).fetchall()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '30 seconds')"
            ).fetchall()


def test_worker_claim_argument_bounds_are_enforced(
    worker_runtime_credentials: _Credentials,
) -> None:
    with _runtime_conn(worker_runtime_credentials) as conn:
        for query in (
            "SELECT * FROM request_cmd.claim_scheduled_actions(0, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(501, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '0 seconds')",
            "SELECT * FROM request_cmd.claim_scheduled_actions(1, interval '16 minutes')",
            "SELECT * FROM request_cmd.claim_outbox_messages(0, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(501, interval '30 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '0 seconds')",
            "SELECT * FROM request_cmd.claim_outbox_messages(1, interval '16 minutes')",
        ):
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                conn.execute(query).fetchall()


def test_worker_direct_reads_remain_rls_scoped_but_claim_surface_discovers_tenants(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "worker-rls")
    action_id = _insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(2000, 1, 1, tzinfo=UTC),
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        direct = conn.execute(
            "SELECT count(*) FROM request_engine.scheduled_actions WHERE id = %s",
            (action_id,),
        ).fetchone()
        assert direct == (0,)

        claimed = _claim_scheduled(conn, 1)
        assert len(claimed) == 1
        assert claimed[0][0] == action_id
        assert claimed[0][1] == organization_id
        assert claimed[0][8] == 1

        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (claimed[0][0], claimed[0][2]),
        ).fetchone() == (True,)


def test_scheduled_claims_due_work_across_tenants_and_ignores_future_work(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    org_a = _new_org(e2e_admin_conn, "scheduled-a")
    org_b = _new_org(e2e_admin_conn, "scheduled-b")
    due_at = datetime(2001, 1, 1, tzinfo=UTC)
    future_at = datetime(2099, 1, 1, tzinfo=UTC)
    due_ids = {
        _insert_scheduled_action(e2e_admin_conn, org_a, when=due_at),
        _insert_scheduled_action(e2e_admin_conn, org_b, when=due_at),
    }
    future_id = _insert_scheduled_action(e2e_admin_conn, org_a, when=future_at)

    with _runtime_conn(worker_runtime_credentials) as conn:
        claimed = _claim_scheduled(conn, 2)
        assert {cast(UUID, row[0]) for row in claimed} == due_ids
        assert {cast(UUID, row[1]) for row in claimed} == {org_a, org_b}
        assert all(row[8] == 1 for row in claimed)

        for row in claimed:
            assert conn.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)

    future = e2e_admin_conn.execute(
        "SELECT status, attempt_count FROM request_engine.scheduled_actions WHERE id = %s",
        (future_id,),
    ).fetchone()
    assert future == ("pending", 0)


def test_two_workers_claim_disjoint_scheduled_batches_under_contention(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "scheduled-race")
    due_at = datetime(1990, 1, 1, tzinfo=UTC)
    expected = {
        _insert_scheduled_action(e2e_admin_conn, organization_id, when=due_at)
        for _ in range(16)
    }
    barrier = threading.Barrier(2)

    def claim_batch() -> list[tuple[Any, ...]]:
        with _runtime_conn(worker_runtime_credentials) as conn:
            barrier.wait()
            return _claim_scheduled(conn, 8)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim_batch)
        second_future = executor.submit(claim_batch)
        first = first_future.result()
        second = second_future.result()

    first_ids = {cast(UUID, row[0]) for row in first}
    second_ids = {cast(UUID, row[0]) for row in second}
    assert len(first_ids) == 8
    assert len(second_ids) == 8
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == expected

    with _runtime_conn(worker_runtime_credentials) as conn:
        for row in first + second:
            assert conn.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)


def test_scheduled_claim_token_is_single_use_and_stale_safe(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "scheduled-token")
    action_id = _insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1985, 1, 1, tzinfo=UTC),
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        row = _claim_scheduled(conn, 1)[0]
        assert row[0] == action_id
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

    state = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, completed_at IS NOT NULL
        FROM request_engine.scheduled_actions WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert state == ("completed", None, None, True)


def test_scheduled_retry_exhaustion_becomes_dead_and_cannot_be_reclaimed(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "scheduled-retry")
    action_id = _insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1980, 1, 1, tzinfo=UTC),
        max_attempts=2,
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        first = _claim_scheduled(conn, 1)[0]
        assert first[0] == action_id
        assert first[8] == 1
        assert conn.execute(
            "SELECT request_cmd.retry_scheduled_action(%s, %s, %s, %s)",
            (action_id, first[2], datetime(1979, 1, 1, tzinfo=UTC), "transient"),
        ).fetchone() == ("pending",)

        second = _claim_scheduled(conn, 1)[0]
        assert second[0] == action_id
        assert second[8] == 2
        assert conn.execute(
            "SELECT request_cmd.retry_scheduled_action(%s, %s, %s, %s)",
            (action_id, second[2], datetime(1978, 1, 1, tzinfo=UTC), "still_broken"),
        ).fetchone() == ("dead",)

        assert all(row[0] != action_id for row in _claim_scheduled(conn, 1))

    state = e2e_admin_conn.execute(
        "SELECT status, attempt_count, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert state == ("dead", 2, "still_broken")


def test_expired_scheduled_lease_is_reclaimed_after_simulated_worker_crash(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "scheduled-crash")
    stale_token = uuid4()
    action_id = _insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1970, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1970, 1, 2, tzinfo=UTC),
        attempt_count=1,
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        reclaimed = _claim_scheduled(conn, 1)[0]
        assert reclaimed[0] == action_id
        assert reclaimed[2] != stale_token
        assert reclaimed[8] == 2
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, stale_token),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, reclaimed[2]),
        ).fetchone() == (True,)


def test_scheduled_dead_letter_is_terminal_and_token_guarded(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "scheduled-dead-letter")
    action_id = _insert_scheduled_action(
        e2e_admin_conn,
        organization_id,
        when=datetime(1960, 1, 1, tzinfo=UTC),
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        claimed = _claim_scheduled(conn, 1)[0]
        assert claimed[0] == action_id
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


def test_two_workers_claim_disjoint_outbox_batches_under_contention(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "outbox-race")
    due_at = datetime(1950, 1, 1, tzinfo=UTC)
    expected = {
        _insert_outbox_message(e2e_admin_conn, organization_id, when=due_at)
        for _ in range(20)
    }
    barrier = threading.Barrier(2)

    def claim_batch() -> list[tuple[Any, ...]]:
        with _runtime_conn(worker_runtime_credentials) as conn:
            barrier.wait()
            return _claim_outbox(conn, 10)

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

    with _runtime_conn(worker_runtime_credentials) as conn:
        for row in first + second:
            assert conn.execute(
                "SELECT request_cmd.complete_outbox_message(%s, %s)",
                (row[0], row[2]),
            ).fetchone() == (True,)


def test_outbox_retry_exhaustion_and_stale_token_semantics(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "outbox-retry")
    message_id = _insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1940, 1, 1, tzinfo=UTC),
        max_attempts=2,
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        first = _claim_outbox(conn, 1)[0]
        assert first[0] == message_id
        assert first[8] == 1
        assert conn.execute(
            "SELECT request_cmd.complete_outbox_message(%s, %s)",
            (message_id, uuid4()),
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT request_cmd.retry_outbox_message(%s, %s, %s, %s)",
            (message_id, first[2], datetime(1939, 1, 1, tzinfo=UTC), "provider_503"),
        ).fetchone() == ("pending",)

        second = _claim_outbox(conn, 1)[0]
        assert second[0] == message_id
        assert second[8] == 2
        assert conn.execute(
            "SELECT request_cmd.retry_outbox_message(%s, %s, %s, %s)",
            (message_id, second[2], datetime(1938, 1, 1, tzinfo=UTC), "provider_503"),
        ).fetchone() == ("dead",)

    assert e2e_admin_conn.execute(
        "SELECT status, attempt_count, last_error_class FROM request_engine.outbox_messages WHERE id = %s",
        (message_id,),
    ).fetchone() == ("dead", 2, "provider_503")


def test_expired_outbox_lease_is_reclaimed_after_simulated_worker_crash(
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "outbox-crash")
    stale_token = uuid4()
    message_id = _insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1930, 1, 1, tzinfo=UTC),
        status="leased",
        claim_token=stale_token,
        lease_until=datetime(1930, 1, 2, tzinfo=UTC),
        attempt_count=3,
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        reclaimed = _claim_outbox(conn, 1)[0]
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
    e2e_admin_conn: PgConnection,
    worker_runtime_credentials: _Credentials,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "outbox-dead-letter")
    message_id = _insert_outbox_message(
        e2e_admin_conn,
        organization_id,
        when=datetime(1920, 1, 1, tzinfo=UTC),
    )

    with _runtime_conn(worker_runtime_credentials) as conn:
        claimed = _claim_outbox(conn, 1)[0]
        assert claimed[0] == message_id
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


def test_communication_task_dedupe_is_tenant_scoped_and_contact_fk_is_tenant_safe(
    e2e_admin_conn: PgConnection,
) -> None:
    org_a = _new_org(e2e_admin_conn, "communication-a")
    org_b = _new_org(e2e_admin_conn, "communication-b")
    party_a = _new_party(e2e_admin_conn, org_a, "Recipient A")
    party_b = _new_party(e2e_admin_conn, org_b, "Recipient B")
    contact_a = _new_contact_point(e2e_admin_conn, org_a, party_a, "a")
    contact_b = _new_contact_point(e2e_admin_conn, org_b, party_b, "b")
    dedupe = f"appointment-reminder:{uuid4().hex}"

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, dedupe_key
        ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
        """,
        (org_a, party_a, contact_a, dedupe),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_tasks (
                organization_id, recipient_party_id, contact_point_id, purpose,
                template_key, template_version, dedupe_key
            ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
            """,
            (org_a, party_a, contact_a, dedupe),
        )

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, dedupe_key
        ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
        """,
        (org_b, party_b, contact_b, dedupe),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_tasks (
                organization_id, recipient_party_id, contact_point_id, purpose,
                template_key, template_version, dedupe_key
            ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
            """,
            (org_a, party_a, contact_b, f"cross-tenant:{uuid4().hex}"),
        )


def test_communication_delivery_provider_idempotency_and_message_id_are_unique(
    e2e_admin_conn: PgConnection,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "delivery-dedupe")
    party_id = _new_party(e2e_admin_conn, organization_id, "Recipient")

    def new_task() -> UUID:
        row = e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_tasks (
                organization_id, recipient_party_id, purpose,
                template_key, template_version, dedupe_key
            ) VALUES (%s, %s, 'confirmation', 'booking-confirmed', 1, %s)
            RETURNING id
            """,
            (organization_id, party_id, f"task:{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        return cast(UUID, row[0])

    task_a = new_task()
    task_b = new_task()
    provider_idempotency_key = f"send:{uuid4().hex}"
    provider_message_id = f"msg-{uuid4().hex}"

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, provider_message_id, status
        ) VALUES (%s, %s, 1, 'whatsapp', 'provider-a', %s, %s, 'accepted')
        """,
        (organization_id, task_a, provider_idempotency_key, provider_message_id),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, status
            ) VALUES (%s, %s, 1, 'whatsapp', 'provider-a', %s, 'accepted')
            """,
            (organization_id, task_b, provider_idempotency_key),
        )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, provider_message_id, status
            ) VALUES (%s, %s, 1, 'whatsapp', 'provider-a', %s, %s, 'accepted')
            """,
            (
                organization_id,
                task_b,
                f"send:{uuid4().hex}",
                provider_message_id,
            ),
        )


def test_provider_event_deduplication_scopes_provider_connection_and_tenant(
    e2e_admin_conn: PgConnection,
) -> None:
    org_a = _new_org(e2e_admin_conn, "provider-event-a")
    org_b = _new_org(e2e_admin_conn, "provider-event-b")
    event_id = f"evt-{uuid4().hex}"

    def insert_event(org: UUID, connection: str) -> None:
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.provider_events (
                organization_id, provider_key, connection_key,
                provider_event_id, payload_hash, payload
            ) VALUES (%s, 'provider-a', %s, %s, %s, '{}'::jsonb)
            """,
            (org, connection, event_id, uuid4().hex),
        )

    insert_event(org_a, "primary")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_event(org_a, "primary")

    insert_event(org_a, "secondary")
    insert_event(org_b, "primary")


def test_reminder_acknowledgement_is_idempotent_per_occurrence_and_subject(
    e2e_admin_conn: PgConnection,
) -> None:
    organization_id = _new_org(e2e_admin_conn, "reminder-ack")
    party_id = _new_party(e2e_admin_conn, organization_id, "Patient")
    plan_row = e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.reminder_plans (
            organization_id, subject_party_id, purpose, timezone,
            schedule_spec, template_key, template_version
        ) VALUES (
            %s, %s, 'medication', 'America/Santo_Domingo',
            '{"type":"daily_times","times":["08:00"]}'::jsonb,
            'medication-reminder', 1
        )
        RETURNING id
        """,
        (organization_id, party_id),
    ).fetchone()
    assert plan_row is not None
    plan_id = cast(UUID, plan_row[0])
    occurrence = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.reminder_acknowledgements (
            organization_id, reminder_plan_id, occurrence_at,
            subject_party_id, source_key, reported_value
        ) VALUES (%s, %s, %s, %s, 'patient_reply', 'taken')
        """,
        (organization_id, plan_id, occurrence, party_id),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.reminder_acknowledgements (
                organization_id, reminder_plan_id, occurrence_at,
                subject_party_id, source_key, reported_value
            ) VALUES (%s, %s, %s, %s, 'duplicate_webhook', 'taken')
            """,
            (organization_id, plan_id, occurrence, party_id),
        )
