import os
import random
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@dataclass
class Model:
    action_id: UUID
    current_token: UUID | None = None
    stale_tokens: list[UUID] | None = None

    def __post_init__(self) -> None:
        if self.stale_tokens is None:
            self.stale_tokens = []


def _conninfo() -> str:
    return " ".join(
        (
            f"host={os.environ.get('PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('PGPORT', '5432')}",
            f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}",
            f"user={os.environ.get('PGUSER', 'request_engine')}",
            f"password={os.environ.get('PGPASSWORD', 'request_engine')}",
        )
    )


def _create_action(admin_conn: PgConnection, seed: int) -> UUID:
    suffix = uuid4().hex
    organization_row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"stateful-worker-{seed}-{suffix}", f"Stateful worker {seed}"),
    ).fetchone()
    assert organization_row is not None
    organization_id = cast(UUID, organization_row[0])
    action_row = admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            payload, dedupe_key, execute_at, next_attempt_at, max_attempts
        ) VALUES (
            %s, 'booking', 'test.state_machine', 1, '{}'::jsonb, %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() - interval '1 minute', 12
        )
        RETURNING id
        """,
        (organization_id, f"state-machine:{suffix}"),
    ).fetchone()
    assert action_row is not None
    return cast(UUID, action_row[0])


def _assert_invariants(admin_conn: PgConnection, action_id: UUID) -> None:
    row = admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count, max_attempts
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert row is not None
    status, token, lease_until, attempts, max_attempts = row
    assert 0 <= attempts <= max_attempts
    if status == "leased":
        assert token is not None
        assert lease_until is not None
    else:
        assert token is None
        assert lease_until is None
    if status in {"completed", "dead"}:
        assert token is None
        assert lease_until is None


def _claim(worker: PgConnection, model: Model) -> None:
    rows = worker.execute(
        """
        SELECT action_id, claim_token
        FROM request_cmd.claim_scheduled_actions(500, interval '30 seconds')
        """
    ).fetchall()
    matching = [row for row in rows if row[0] == model.action_id]
    if matching:
        new_token = cast(UUID, matching[0][1])
        if model.current_token is not None:
            assert model.stale_tokens is not None
            model.stale_tokens.append(model.current_token)
        model.current_token = new_token


def _step(
    admin_conn: PgConnection,
    worker: PgConnection,
    model: Model,
    operation: str,
) -> None:
    if operation == "claim":
        _claim(worker, model)
        return

    if operation == "expire":
        admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s AND status = 'leased'
            """,
            (model.action_id,),
        )
        return

    if operation == "renew":
        if model.current_token is not None:
            worker.execute(
                "SELECT request_cmd.renew_scheduled_action_lease(%s, %s, interval '30 seconds')",
                (model.action_id, model.current_token),
            ).fetchone()
        return

    if operation == "retry":
        if model.current_token is not None:
            result = worker.execute(
                """
                SELECT request_cmd.retry_scheduled_action_after(
                    %s, %s, interval '0 seconds', 'stateful_retry'
                )
                """,
                (model.action_id, model.current_token),
            ).fetchone()
            if result is not None and result[0] in {"pending", "dead"}:
                assert model.stale_tokens is not None
                model.stale_tokens.append(model.current_token)
                model.current_token = None
        return

    if operation == "complete":
        if model.current_token is not None:
            completed = worker.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (model.action_id, model.current_token),
            ).fetchone()
            if completed == (True,):
                assert model.stale_tokens is not None
                model.stale_tokens.append(model.current_token)
                model.current_token = None
        return

    if operation == "stale_complete":
        assert model.stale_tokens is not None
        if model.stale_tokens:
            stale = model.stale_tokens[-1]
            assert worker.execute(
                "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                (model.action_id, stale),
            ).fetchone() == (False,)
        return

    raise AssertionError(f"unknown state-machine operation: {operation}")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_worker_lifecycle_state_machine_fuzz_preserves_fencing_invariants(
    admin_conn: PgConnection,
) -> None:
    """Explore long deterministic transition sequences and report the minimal failing prefix."""

    operations = ("claim", "expire", "renew", "retry", "complete", "stale_complete")
    for seed in range(40):
        rng = random.Random(seed)
        model = Model(_create_action(admin_conn, seed))
        worker: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
        worker.execute("SET ROLE request_engine_worker")
        history: list[str] = []
        try:
            for _ in range(60):
                operation = rng.choice(operations)
                history.append(operation)
                try:
                    _step(admin_conn, worker, model, operation)
                    _assert_invariants(admin_conn, model.action_id)
                except Exception as exc:
                    # The first failing prefix is already a deterministic prefix shrink.
                    pytest.fail(
                        f"seed={seed} minimal_failing_prefix={history!r}: {exc}",
                        pytrace=True,
                    )
        finally:
            worker.close()
