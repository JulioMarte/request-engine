from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("Plans", []):
        nodes.extend(_walk(child))
    return nodes


def _index_names(plan: dict[str, Any]) -> set[str]:
    return {
        str(node["Index Name"])
        for node in _walk(plan)
        if node.get("Index Name") is not None
    }


def _explain(cursor: psycopg.Cursor[Any], sql: str) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report: dict[str, Any] = {"schema_version": 1, "proofs": []}
    with psycopg.connect() as connection:
        with connection.transaction(force_rollback=True), connection.cursor() as cursor:
            suffix = uuid4().hex
            cursor.execute(
                """
                INSERT INTO request_engine.organizations (organization_key, display_name)
                VALUES (%s, 'Query plan proof')
                RETURNING id
                """,
                (f"query-plan-{suffix}",),
            )
            organization_id = cursor.fetchone()[0]

            # A large mostly-future population forces the planner to choose the partial due index
            # for the small actionable subset. generate_series keeps fixture creation deterministic.
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
                FROM generate_series(1, 10000) AS value
                """,
                (organization_id, suffix, suffix),
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
                FROM generate_series(1, 100) AS value
                """,
                (organization_id, suffix, suffix),
            )
            cursor.execute("ANALYZE request_engine.provider_events")

            due_plan = _explain(
                cursor,
                """
                SELECT id
                FROM request_engine.provider_events
                WHERE status = 'received'
                  AND next_attempt_at <= clock_timestamp()
                ORDER BY next_attempt_at, id
                LIMIT 50
                """,
            )
            due_indexes = _index_names(due_plan["Plan"])
            report["proofs"].append(
                {
                    "name": "provider_events_due",
                    "required_index": "provider_events_due_idx",
                    "indexes": sorted(due_indexes),
                    "plan": due_plan,
                }
            )
            if "provider_events_due_idx" not in due_indexes:
                raise SystemExit("provider_events_due_idx was not selected by the measured query plan")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
