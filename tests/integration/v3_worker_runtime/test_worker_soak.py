import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]
WORKER_COUNT = 8


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


def _drain(worker_number: int, target_ids: set[UUID], start: Barrier) -> tuple[int, list[UUID]]:
    completed: list[UUID] = []
    worker: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        start.wait(timeout=10)
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
                    completed.append(action_id)
    finally:
        worker.close()
    return worker_number, completed


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_multi_worker_soak_completes_hot_and_cold_tenants_without_duplicate_ownership(
    admin_conn: PgConnection,
) -> None:
    """Synchronize eight claimers against 360 actions and prove exactly-once ownership."""

    organization_ids, action_ids = _seed(admin_conn)
    start = Barrier(WORKER_COUNT)
    with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
        futures = [
            executor.submit(_drain, worker_number, action_ids, start)
            for worker_number in range(WORKER_COUNT)
        ]
        worker_results = [future.result(timeout=120) for future in futures]

    owners: defaultdict[UUID, list[int]] = defaultdict(list)
    for worker_number, completed in worker_results:
        for action_id in completed:
            owners[action_id].append(worker_number)

    completed_ids = set(owners)
    missing = action_ids - completed_ids
    assert not missing, f"{len(missing)} soak actions were never completed: {sorted(missing)[:10]}"

    duplicate_owners = {
        action_id: worker_numbers
        for action_id, worker_numbers in owners.items()
        if len(worker_numbers) != 1
    }
    assert not duplicate_owners, (
        "one or more soak actions completed more than once; "
        f"duplicates={dict(list(sorted(duplicate_owners.items()))[:20])}"
    )

    unexpected = completed_ids - action_ids
    assert not unexpected, (
        f"workers completed actions outside the soak fixture: {sorted(unexpected)[:10]}"
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
