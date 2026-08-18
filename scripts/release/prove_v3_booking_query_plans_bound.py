from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

import prove_v3_booking_query_plans as base


def _explain(cursor: base.CursorLike, sql: str, params: object = ()) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params)
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def _prove(
    cursor: base.CursorLike,
    report: dict[str, Any],
    target: dict[str, Any],
) -> None:
    organization_id = target["organization_id"]
    resource_id = target["resource_id"]

    cursor.execute(
        """
        SELECT clock_timestamp() + interval '1 day',
               clock_timestamp() + interval '2 days'
        """
    )
    window = cursor.fetchone()
    assert window is not None
    window_start, window_end = window

    schedules = _explain(
        cursor,
        """
        SELECT resource_id, weekday, local_start, local_end, timezone,
               valid_from, valid_until
        FROM request_engine.availability_schedules
        WHERE organization_id = %s
          AND resource_id = %s
          AND active
        ORDER BY resource_id, weekday, local_start, id
        """,
        (organization_id, resource_id),
    )
    base._record(
        report,
        name="booking_resource_schedules",
        plan=schedules,
        relations={"availability_schedules"},
        max_rows_removed={"availability_schedules": 16},
        max_shared_hit_blocks=64,
    )

    exceptions = _explain(
        cursor,
        """
        SELECT resource_id, lower(during) AS start_at, upper(during) AS end_at,
               exception_kind
        FROM request_engine.schedule_exceptions
        WHERE organization_id = %s
          AND resource_id = %s
          AND during && tstzrange(%s, %s, '[)')
        ORDER BY resource_id, lower(during), id
        """,
        (organization_id, resource_id, window_start, window_end),
    )
    base._record(
        report,
        name="booking_resource_exceptions",
        plan=exceptions,
        relations={"schedule_exceptions"},
        max_rows_removed={"schedule_exceptions": 16},
        max_shared_hit_blocks=64,
    )

    claims = _explain(
        cursor,
        """
        SELECT c.resource_id, lower(c.during) AS start_at,
               upper(c.during) AS end_at, c.quantity
        FROM request_engine.capacity_claims c
        LEFT JOIN request_engine.reservations r
          ON r.organization_id = c.organization_id
         AND r.id = c.reservation_id
        LEFT JOIN request_engine.capacity_holds h
          ON h.organization_id = c.organization_id
         AND h.id = c.hold_id
        WHERE c.organization_id = %s
          AND c.resource_id = %s
          AND c.status = 'active'
          AND c.during && tstzrange(%s, %s, '[)')
          AND (
              (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
              OR (
                  c.reservation_id IS NULL
                  AND h.status = 'active'
                  AND h.expires_at > clock_timestamp()
              )
          )
        ORDER BY c.resource_id, lower(c.during), c.id
        """,
        (organization_id, resource_id, window_start, window_end),
    )
    base._record(
        report,
        name="booking_live_capacity_claims",
        plan=claims,
        relations={"capacity_claims"},
        max_rows_removed={"capacity_claims": 16},
        max_shared_hit_blocks=96,
    )


def _vacuum_measurement_relations(connection: Any) -> None:
    for relation in (
        "availability_schedules",
        "schedule_exceptions",
        "capacity_claims",
        "capacity_holds",
    ):
        connection.execute(f"VACUUM (ANALYZE) request_engine.{relation}")


def _cleanup_seeded_tenants(cursor: base.CursorLike, organization_ids: list[Any]) -> None:
    # Cleanup is deliberately outside the measured workload. Some seeded catalog
    # rows are append-only in production, so a normal DELETE must keep failing.
    # This cleanup-only transaction runs as the bootstrap principal and disables
    # user triggers locally so repeated local proof runs do not leave fixtures.
    cursor.execute("SET LOCAL session_replication_role = replica")
    tenant_tables = (
        "capacity_claims",
        "capacity_holds",
        "schedule_exceptions",
        "availability_schedules",
        "resource_capability_assignments",
        "offering_resource_requirements",
        "resources",
        "resource_capabilities",
        "offering_versions",
        "offerings",
        "parties",
    )
    for organization_id in organization_ids:
        for table in tenant_tables:
            cursor.execute(
                f"DELETE FROM request_engine.{table} WHERE organization_id = %s",
                (organization_id,),
            )
        cursor.execute(
            "DELETE FROM request_engine.organizations WHERE id = %s",
            (organization_id,),
        )


def main() -> int:
    import psycopg

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "cardinality": {
            "tenant_count": base.TENANT_COUNT,
            "history_per_tenant": base.HISTORY_PER_TENANT,
        },
        "proofs": [],
        "failures": [],
    }

    organization_ids: list[Any] = []
    with psycopg.connect(autocommit=True) as connection:
        run_suffix = uuid.uuid4().hex
        target: dict[str, Any] | None = None
        try:
            with connection.transaction(), connection.cursor() as cursor:
                for tenant_index in range(base.TENANT_COUNT):
                    seeded = base._seed_tenant(cursor, f"{run_suffix}-{tenant_index}")
                    organization_ids.append(seeded["organization_id"])
                    if target is None:
                        target = seeded
            assert target is not None

            _vacuum_measurement_relations(connection)

            with connection.transaction(), connection.cursor() as cursor:
                _prove(cursor, report, target)
        finally:
            if organization_ids:
                with connection.transaction(), connection.cursor() as cursor:
                    _cleanup_seeded_tenants(cursor, organization_ids)

    if report["failures"]:
        report["status"] = "FAIL"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["failures"]:
        details = "; ".join(
            f"{failure['name']}: {failure['reason']}" for failure in report["failures"]
        )
        raise SystemExit(f"measured Booking query plan failures: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())