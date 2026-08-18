from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Protocol

TENANT_COUNT = 4
HISTORY_PER_TENANT = 1_500


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


def _seq_scans(plan: dict[str, Any], relations: set[str]) -> list[str]:
    return sorted(
        {
            str(node.get("Relation Name"))
            for node in _walk(plan)
            if node.get("Node Type") == "Seq Scan" and node.get("Relation Name") in relations
        }
    )


def _rows_removed(plan: dict[str, Any], relation: str) -> int:
    total = 0.0
    for node in _walk(plan):
        if node.get("Relation Name") != relation:
            continue
        removed = float(node.get("Rows Removed by Filter", 0) or 0)
        loops = float(node.get("Actual Loops", 1) or 1)
        total += removed * loops
    return int(total)


def _explain(cursor: CursorLike, sql: str) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def _record(
    report: dict[str, Any],
    *,
    name: str,
    plan: dict[str, Any],
    relations: set[str],
    max_rows_removed: dict[str, int],
    max_shared_hit_blocks: int,
) -> None:
    root = plan["Plan"]
    seq_scans = _seq_scans(root, relations)
    rows_removed = {relation: _rows_removed(root, relation) for relation in max_rows_removed}
    shared_hit_blocks = int(root.get("Shared Hit Blocks", 0) or 0)
    shared_read_blocks = int(root.get("Shared Read Blocks", 0) or 0)
    temp_written_blocks = int(root.get("Temp Written Blocks", 0) or 0)
    execution_ms = float(plan.get("Execution Time", 0.0) or 0.0)

    failures: list[str] = []
    if seq_scans:
        failures.append(f"forbidden sequential scan on {', '.join(seq_scans)}")
    if shared_hit_blocks > max_shared_hit_blocks:
        failures.append(f"shared hit blocks {shared_hit_blocks} exceed {max_shared_hit_blocks}")
    if shared_read_blocks:
        failures.append(f"unexpected shared reads: {shared_read_blocks}")
    if temp_written_blocks:
        failures.append(f"plan spilled {temp_written_blocks} temp blocks")
    for relation, maximum in max_rows_removed.items():
        if rows_removed[relation] > maximum:
            failures.append(
                f"{relation} removed {rows_removed[relation]} rows; budget is {maximum}"
            )

    report["proofs"].append(
        {
            "name": name,
            "status": "PASS" if not failures else "FAIL",
            "indexes": sorted(_index_names(root)),
            "execution_ms": execution_ms,
            "shared_hit_blocks": shared_hit_blocks,
            "shared_read_blocks": shared_read_blocks,
            "temp_written_blocks": temp_written_blocks,
            "forbidden_seq_scans": seq_scans,
            "rows_removed_by_filter": rows_removed,
            "failures": failures,
            "plan": plan,
        }
    )
    for failure in failures:
        report["failures"].append({"name": name, "reason": failure})


def _one(cursor: CursorLike, sql: str, params: object) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _seed_claim_history(
    cursor: CursorLike,
    *,
    organization_id: object,
    resource_id: object,
    requirement_id: object,
    hold_id: object,
) -> None:
    cursor.execute(
        """
        DO $block$
        DECLARE
            v_claim_id uuid;
            v_step integer;
        BEGIN
            FOR v_step IN 1..%s LOOP
                INSERT INTO request_engine.capacity_claims (
                    organization_id, resource_id, requirement_id, hold_id,
                    during, quantity, status
                )
                SELECT %s, %s, %s, h.id, h.during, 1, 'active'
                FROM request_engine.capacity_holds h
                WHERE h.organization_id = %s
                  AND h.id = %s
                RETURNING id INTO v_claim_id;

                UPDATE request_engine.capacity_claims
                SET status = 'released',
                    released_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                WHERE id = v_claim_id;
            END LOOP;
        END
        $block$
        """,
        (
            HISTORY_PER_TENANT,
            organization_id,
            resource_id,
            requirement_id,
            organization_id,
            hold_id,
        ),
    )


def _seed_tenant(cursor: CursorLike, suffix: str) -> dict[str, Any]:
    organization_id = _one(
        cursor,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'G15 Booking plan proof')
        RETURNING id
        """,
        (f"g15-booking-{suffix}",),
    )
    party_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'G15 Booking subject')
        RETURNING id
        """,
        (organization_id,),
    )
    offering_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'G15 Booking offering')
        RETURNING id
        """,
        (organization_id, f"g15-booking-offering-{suffix}"),
    )
    offering_version_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _one(
        cursor,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'G15 Booking capability')
        RETURNING id
        """,
        (organization_id, f"g15-booking-capability-{suffix}"),
    )
    requirement_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _one(
        cursor,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'G15 Booking resource', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"g15-booking-resource-{suffix}"),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end,
            timezone, active
        )
        SELECT %s, %s, value %% 7, '08:00', '17:00', 'UTC', false
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, resource_id, HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone, active
        ) VALUES (%s, %s, 1, '09:00', '12:00', 'UTC', true)
        """,
        (organization_id, resource_id),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.schedule_exceptions (
            organization_id, resource_id, during, exception_kind, reason
        )
        SELECT %s, %s,
               tstzrange(
                   timestamptz '2020-01-01 00:00:00+00' + value * interval '2 hours',
                   timestamptz '2020-01-01 01:00:00+00' + value * interval '2 hours',
                   '[)'
               ),
               'unavailable', 'G15 historical exception'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, resource_id, HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.schedule_exceptions (
            organization_id, resource_id, during, exception_kind, reason
        ) VALUES (
            %s, %s,
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'unavailable', 'G15 current exception'
        )
        """,
        (organization_id, resource_id),
    )

    hold_id = _one(
        cursor,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id, offering_version_id, subject_party_id, during,
            status, expires_at
        ) VALUES (
            %s, %s, %s,
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'active', clock_timestamp() + interval '2 hours'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id, party_id),
    )

    _seed_claim_history(
        cursor,
        organization_id=organization_id,
        resource_id=resource_id,
        requirement_id=requirement_id,
        hold_id=hold_id,
    )
    cursor.execute(
        """
        INSERT INTO request_engine.capacity_claims (
            organization_id, resource_id, requirement_id, hold_id,
            during, quantity, status
        )
        SELECT %s, %s, %s, h.id, h.during, 1, 'active'
        FROM request_engine.capacity_holds h
        WHERE h.organization_id = %s
          AND h.id = %s
        """,
        (
            organization_id,
            resource_id,
            requirement_id,
            organization_id,
            hold_id,
        ),
    )

    return {"organization_id": organization_id, "resource_id": resource_id}


def _prove(cursor: CursorLike, report: dict[str, Any], target: dict[str, Any]) -> None:
    organization_id = target["organization_id"]
    resource_id = target["resource_id"]

    for relation in (
        "availability_schedules",
        "schedule_exceptions",
        "capacity_claims",
        "capacity_holds",
    ):
        cursor.execute(f"ANALYZE request_engine.{relation}")

    schedules = _explain(
        cursor,
        f"""
        SELECT resource_id, weekday, local_start, local_end, timezone,
               valid_from, valid_until
        FROM request_engine.availability_schedules
        WHERE organization_id = '{organization_id}'::uuid
          AND resource_id = '{resource_id}'::uuid
          AND active
        ORDER BY resource_id, weekday, local_start, id
        """,
    )
    _record(
        report,
        name="booking_resource_schedules",
        plan=schedules,
        relations={"availability_schedules"},
        max_rows_removed={"availability_schedules": 16},
        max_shared_hit_blocks=64,
    )

    exceptions = _explain(
        cursor,
        f"""
        SELECT resource_id, lower(during) AS start_at, upper(during) AS end_at,
               exception_kind
        FROM request_engine.schedule_exceptions
        WHERE organization_id = '{organization_id}'::uuid
          AND resource_id = '{resource_id}'::uuid
          AND during && tstzrange(
              clock_timestamp() + interval '1 day',
              clock_timestamp() + interval '2 days',
              '[)'
          )
        ORDER BY resource_id, lower(during), id
        """,
    )
    _record(
        report,
        name="booking_resource_exceptions",
        plan=exceptions,
        relations={"schedule_exceptions"},
        max_rows_removed={"schedule_exceptions": 16},
        max_shared_hit_blocks=64,
    )

    claims = _explain(
        cursor,
        f"""
        SELECT c.resource_id, lower(c.during) AS start_at,
               upper(c.during) AS end_at, c.quantity
        FROM request_engine.capacity_claims c
        LEFT JOIN request_engine.reservations r
          ON r.organization_id = c.organization_id
         AND r.id = c.reservation_id
        LEFT JOIN request_engine.capacity_holds h
          ON h.organization_id = c.organization_id
         AND h.id = c.hold_id
        WHERE c.organization_id = '{organization_id}'::uuid
          AND c.resource_id = '{resource_id}'::uuid
          AND c.status = 'active'
          AND c.during && tstzrange(
              clock_timestamp() + interval '1 day',
              clock_timestamp() + interval '2 days',
              '[)'
          )
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
    )
    _record(
        report,
        name="booking_live_capacity_claims",
        plan=claims,
        relations={"capacity_claims"},
        max_rows_removed={"capacity_claims": 16},
        max_shared_hit_blocks=96,
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
            "tenant_count": TENANT_COUNT,
            "history_per_tenant": HISTORY_PER_TENANT,
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
        target: dict[str, Any] | None = None
        for tenant_index in range(TENANT_COUNT):
            seeded = _seed_tenant(cursor, f"{run_suffix}-{tenant_index}")
            if target is None:
                target = seeded
        assert target is not None
        _prove(cursor, report, target)

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
