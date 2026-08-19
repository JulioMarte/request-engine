from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Protocol

TENANT_COUNT = 4
FUTURE_ROWS_PER_TENANT = 2_500
DUE_ROWS_PER_TENANT = 25


class CursorLike(Protocol):
    def execute(self, query: str, params: object = ...) -> object: ...

    def fetchone(self) -> Any: ...


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("Plans", []):
        nodes.extend(_walk(child))
    return nodes


def _index_names(plan: dict[str, Any]) -> set[str]:
    return {str(node["Index Name"]) for node in _walk(plan) if node.get("Index Name") is not None}


def _explain(cursor: CursorLike, sql: str) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def _record_proof(
    report: dict[str, Any],
    *,
    name: str,
    plan: dict[str, Any],
    required_indexes: set[str],
) -> None:
    indexes = _index_names(plan["Plan"])
    missing = sorted(required_indexes - indexes)
    required = sorted(required_indexes)
    for required_index in required:
        proof_name = name if len(required) == 1 else f"{name}:{required_index}"
        report["proofs"].append(
            {
                "name": proof_name,
                "required_index": required_index,
                "required_indexes": required,
                "indexes": sorted(indexes),
                "missing_indexes": missing,
                "plan": plan,
            }
        )
    if missing:
        report["failures"].append({"name": name, "missing_indexes": missing})


def _seed_scheduled_actions(
    cursor: CursorLike,
    organization_id: object,
    suffix: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload, dedupe_key,
            execute_at, next_attempt_at, status
        )
        SELECT %s, 'plan', 'future', '{}'::jsonb,
               'future-' || value::text || '-' || %s,
               clock_timestamp() + interval '7 days',
               clock_timestamp() + interval '7 days' + value * interval '1 second',
               'pending'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload, dedupe_key,
            execute_at, next_attempt_at, status
        )
        SELECT %s, 'plan', 'due', '{}'::jsonb,
               'due-' || value::text || '-' || %s,
               clock_timestamp() - interval '1 hour',
               clock_timestamp() - value * interval '1 second',
               'pending'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, DUE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload, dedupe_key,
            execute_at, next_attempt_at, status, claim_token, lease_until
        )
        SELECT %s, 'plan', 'leased', '{}'::jsonb,
               'leased-future-' || value::text || '-' || %s,
               clock_timestamp() - interval '1 hour',
               clock_timestamp(), 'leased', uuidv7(),
               clock_timestamp() + interval '7 days' + value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, payload, dedupe_key,
            execute_at, next_attempt_at, status, claim_token, lease_until
        )
        SELECT %s, 'plan', 'leased', '{}'::jsonb,
               'leased-expired-' || value::text || '-' || %s,
               clock_timestamp() - interval '1 hour',
               clock_timestamp(), 'leased', uuidv7(),
               clock_timestamp() - value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, DUE_ROWS_PER_TENANT),
    )


def _seed_outbox_messages(
    cursor: CursorLike,
    organization_id: object,
    suffix: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, next_attempt_at
        )
        SELECT %s, 'plan.future', '{}'::jsonb, 'pending',
               clock_timestamp() + interval '7 days' + value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, next_attempt_at
        )
        SELECT %s, 'plan.due.' || %s, '{}'::jsonb, 'pending',
               clock_timestamp() - value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, DUE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, claim_token,
            lease_until, next_attempt_at
        )
        SELECT %s, 'plan.leased', '{}'::jsonb, 'leased', uuidv7(),
               clock_timestamp() + interval '7 days' + value * interval '1 second',
               clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, claim_token,
            lease_until, next_attempt_at
        )
        SELECT %s, 'plan.expired.' || %s, '{}'::jsonb, 'leased', uuidv7(),
               clock_timestamp() - value * interval '1 second', clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, DUE_ROWS_PER_TENANT),
    )


def _seed_provider_events(
    cursor: CursorLike,
    organization_id: object,
    suffix: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload, status, next_attempt_at
        )
        SELECT %s, 'plan-provider', 'primary',
               'future-' || value::text || '-' || %s,
               md5(value::text || %s), '{}'::jsonb, 'received',
               clock_timestamp() + interval '7 days' + value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, suffix, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload, status, next_attempt_at
        )
        SELECT %s, 'plan-provider', 'primary',
               'due-' || value::text || '-' || %s,
               md5('due-' || value::text || %s), '{}'::jsonb, 'received',
               clock_timestamp() - value * interval '1 second'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, suffix, DUE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key, provider_event_id,
            payload_hash, payload, status, claim_token, lease_until, next_attempt_at
        )
        SELECT %s, 'plan-provider', 'primary',
               'leased-future-' || value::text || '-' || %s,
               md5('leased-future-' || value::text || %s), '{}'::jsonb,
               'leased', uuidv7(),
               clock_timestamp() + interval '7 days' + value * interval '1 second',
               clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, suffix, FUTURE_ROWS_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key, provider_event_id,
            payload_hash, payload, status, claim_token, lease_until, next_attempt_at
        )
        SELECT %s, 'plan-provider', 'primary',
               'leased-expired-' || value::text || '-' || %s,
               md5('leased-expired-' || value::text || %s), '{}'::jsonb,
               'leased', uuidv7(), clock_timestamp() - value * interval '1 second',
               clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, suffix, DUE_ROWS_PER_TENANT),
    )


def _prove_worker_family(
    cursor: CursorLike,
    report: dict[str, Any],
    *,
    table: str,
    ready_status: str,
    due_index: str,
    reclaim_index: str,
) -> None:
    cursor.execute(f"ANALYZE request_engine.{table}")
    due_plan = _explain(
        cursor,
        f"""
        SELECT id
        FROM request_engine.{table}
        WHERE status = '{ready_status}'
          AND attempt_count < max_attempts
          AND next_attempt_at <= clock_timestamp()
        ORDER BY next_attempt_at, id
        LIMIT 50
        """,
    )
    _record_proof(
        report,
        name=f"{table}_due",
        plan=due_plan,
        required_indexes={due_index},
    )

    reclaim_plan = _explain(
        cursor,
        f"""
        SELECT id
        FROM request_engine.{table}
        WHERE status = 'leased'
          AND attempt_count < max_attempts
          AND lease_until <= clock_timestamp()
        ORDER BY lease_until, id
        LIMIT 50
        """,
    )
    _record_proof(
        report,
        name=f"{table}_reclaim",
        plan=reclaim_plan,
        required_indexes={reclaim_index},
    )

    fairness_plan = _explain(
        cursor,
        f"""
        SELECT id, organization_id,
               CASE WHEN status = '{ready_status}'
                    THEN next_attempt_at ELSE lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY organization_id
                   ORDER BY
                       CASE WHEN status = '{ready_status}'
                            THEN next_attempt_at ELSE lease_until END,
                       id
               ) AS tenant_rank
        FROM request_engine.{table}
        WHERE attempt_count < max_attempts
          AND (
              (status = '{ready_status}' AND next_attempt_at <= statement_timestamp())
              OR (status = 'leased' AND lease_until <= statement_timestamp())
          )
        """,
    )
    _record_proof(
        report,
        name=f"{table}_fairness_rank",
        plan=fairness_plan,
        required_indexes={due_index, reclaim_index},
    )


def main() -> int:
    import psycopg

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    total_rows_per_family = TENANT_COUNT * (2 * FUTURE_ROWS_PER_TENANT + 2 * DUE_ROWS_PER_TENANT)
    report: dict[str, Any] = {
        "schema_version": 5,
        "cardinality": {
            "tenant_count": TENANT_COUNT,
            "future_per_state_per_tenant": FUTURE_ROWS_PER_TENANT,
            "due_per_state_per_tenant": DUE_ROWS_PER_TENANT,
            "total_rows_per_family": total_rows_per_family,
        },
        "proofs": [],
        "failures": [],
    }
    with (
        psycopg.connect() as connection,
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
    ):
        run_suffix = uuid.uuid4().hex
        for tenant_index in range(TENANT_COUNT):
            suffix = f"{run_suffix}-{tenant_index}"
            cursor.execute(
                """
                INSERT INTO request_engine.organizations (organization_key, display_name)
                VALUES (%s, 'Query plan proof')
                RETURNING id
                """,
                (f"query-plan-{suffix}",),
            )
            row = cursor.fetchone()
            assert row is not None
            organization_id = row[0]
            _seed_scheduled_actions(cursor, organization_id, suffix)
            _seed_outbox_messages(cursor, organization_id, suffix)
            _seed_provider_events(cursor, organization_id, suffix)

        _prove_worker_family(
            cursor,
            report,
            table="scheduled_actions",
            ready_status="pending",
            due_index="scheduled_actions_due_idx",
            reclaim_index="scheduled_actions_reclaim_idx",
        )
        _prove_worker_family(
            cursor,
            report,
            table="outbox_messages",
            ready_status="pending",
            due_index="outbox_messages_due_idx",
            reclaim_index="outbox_messages_reclaim_idx",
        )
        _prove_worker_family(
            cursor,
            report,
            table="provider_events",
            ready_status="received",
            due_index="provider_events_due_idx",
            reclaim_index="provider_events_reclaim_idx",
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    failures = report["failures"]
    if failures:
        details = "; ".join(
            f"{failure['name']}: {', '.join(failure['missing_indexes'])}" for failure in failures
        )
        raise SystemExit(f"measured worker query plan failures: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
