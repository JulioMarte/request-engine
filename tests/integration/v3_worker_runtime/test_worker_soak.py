import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


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


def _seed(admin_conn: PgConnection) -> tuple[set[UUID], set[UUID]]:
    organization_ids: set[UUID] = set()
    action_ids: set[UUID] = set()
    for tenant_number in range(12):
        suffix = uuid4().hex
        row = admin_conn.execute(
            """
            INSERT INTO request_engine.organizations (organization_key, display_name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (f"soak-{tenant_number}-{suffix}", f"Soak tenant {tenant_number}"),
        ).fetchone()
        assert row is not None
        organization_id = cast(UUID, row[0])
        organization_ids.add(organization_id)
        rows = admin_conn.execute(
            """
            INSERT INTO request_engine.scheduled_actions (
                organization_id, owner_module, action_type, action_version,
                payload, dedupe_key, execute_at, next_attempt_at
            )
            SELECT %s, 'booking', 'test.soak', 1, '{}'::jsonb,
                   %s || ':' || value::text,
                   clock_timestamp() - interval '1 minute',
                   clock_timestamp() - interval '1 minute'
            FROM generate_series(1, 30) AS value
            RETURNING id
            """,
            (organization_id, f"soak:{suffix}"),
        ).fetchall()
        action_ids.update(cast(UUID, value[0]) for value in rows)
    return organization_ids, action_ids


def _drain(target_ids: set[UUID]) -> set[UUID]:
    completed: set[UUID] = set()
    worker: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        for _ in range(100):
            rows = worker.execute(
                """
                SELECT action_id, claim_token
                FROM request_cmd.claim_scheduled_actions(25, interval '30 seconds')
                """
            ).fetchall()
            ours = [
                (cast(UUID, row[0]), cast(UUID, row[1])) for row in rows if row[0] in target_ids
            ]
            for action_id, token in ours:
                if worker.execute(
                    "SELECT request_cmd.complete_scheduled_action(%s, %s)",
                    (action_id, token),
                ).fetchone() == (True,):
                    completed.add(action_id)
            if len(completed) == len(target_ids):
                break
    finally:
        worker.close()
    return completed


def _drain_worker(_: int, target_ids: set[UUID]) -> set[UUID]:
    return _drain(target_ids)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_multi_worker_soak_completes_hot_and_cold_tenants_without_duplicate_ownership(
    admin_conn: PgConnection,
) -> None:
    """Run eight real claimers against 360 actions and verify exact terminal cardinality."""

    organization_ids, action_ids = _seed(admin_conn)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_drain_worker, worker_number, action_ids) for worker_number in range(8)
        ]
        completed_sets: list[set[UUID]] = [future.result() for future in futures]

    all_completed: set[UUID] = set()
    for completed in completed_sets:
        all_completed.update(completed)

    missing = action_ids - all_completed
    assert not missing, f"{len(missing)} soak actions were never completed: {sorted(missing)[:10]}"

    completion_count = sum(len(values) for values in completed_sets)
    assert completion_count == len(action_ids), (
        "one or more soak actions completed under multiple workers: "
        f"unique={len(action_ids)} worker-completions={completion_count}"
    )

    states = admin_conn.execute(
        """
        SELECT organization_id, count(*) FILTER (WHERE status = 'completed'),
               count(*) FILTER (WHERE status <> 'completed'),
               max(attempt_count)
        FROM request_engine.scheduled_actions
        WHERE id = ANY(%s)
        GROUP BY organization_id
        ORDER BY organization_id
        """,
        (list(action_ids),),
    ).fetchall()
    observed_organizations = {cast(UUID, row[0]) for row in states}
    assert observed_organizations == organization_ids, (
        "soak tenant set mismatch: "
        f"missing={sorted(organization_ids - observed_organizations)} "
        f"unexpected={sorted(observed_organizations - organization_ids)}"
    )

    invalid_states = [
        (cast(UUID, row[0]), cast(int, row[1]), cast(int, row[2]), cast(int, row[3]))
        for row in states
        if row[1:] != (30, 0, 1)
    ]
    assert not invalid_states, (
        "soak tenant terminal cardinality or claim-attempt invariant failed; "
        f"expected=(completed=30, non_completed=0, max_attempt_count=1), observed={invalid_states}"
    )
