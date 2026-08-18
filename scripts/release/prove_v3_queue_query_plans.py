from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Protocol

TENANT_COUNT = 4
QUEUE_HISTORY_PER_TENANT = 2_500
WAITLIST_CANDIDATES_PER_TENANT = 400
PRIOR_OFFERS_PER_TARGET = 100
SLOT_OFFER_HISTORY_PER_TENANT = 2_500


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


def _relation_seq_scans(plan: dict[str, Any], relations: set[str]) -> list[str]:
    return sorted(
        {
            str(node.get("Relation Name"))
            for node in _walk(plan)
            if node.get("Node Type") == "Seq Scan" and node.get("Relation Name") in relations
        }
    )


def _rows_removed_by_filter(plan: dict[str, Any], relation: str) -> int:
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


def _record_plan(
    report: dict[str, Any],
    *,
    name: str,
    plan: dict[str, Any],
    forbidden_seq_relations: set[str],
    max_execution_ms: float,
    max_shared_hit_blocks: int,
    max_rows_removed: dict[str, int] | None = None,
) -> None:
    root = plan["Plan"]
    execution_ms = float(plan.get("Execution Time", 0.0) or 0.0)
    shared_hit_blocks = int(root.get("Shared Hit Blocks", 0) or 0)
    shared_read_blocks = int(root.get("Shared Read Blocks", 0) or 0)
    temp_written_blocks = int(root.get("Temp Written Blocks", 0) or 0)
    seq_scans = _relation_seq_scans(root, forbidden_seq_relations)
    rows_removed = {
        relation: _rows_removed_by_filter(root, relation)
        for relation in sorted((max_rows_removed or {}).keys())
    }

    failures: list[str] = []
    if seq_scans:
        failures.append(f"forbidden sequential scan on {', '.join(seq_scans)}")
    if execution_ms > max_execution_ms:
        failures.append(
            f"execution time {execution_ms:.3f}ms exceeds {max_execution_ms:.3f}ms budget"
        )
    if shared_hit_blocks > max_shared_hit_blocks:
        failures.append(
            f"shared hit blocks {shared_hit_blocks} exceed {max_shared_hit_blocks} budget"
        )
    if shared_read_blocks:
        failures.append(f"unexpected shared reads: {shared_read_blocks}")
    if temp_written_blocks:
        failures.append(f"plan spilled {temp_written_blocks} temp blocks")
    for relation, maximum in (max_rows_removed or {}).items():
        actual = rows_removed[relation]
        if actual > maximum:
            failures.append(
                f"{relation} removed {actual} rows by filter; "
                f"selectivity budget is {maximum}"
            )

    proof = {
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
    report["proofs"].append(proof)
    for failure in failures:
        report["failures"].append({"name": name, "reason": failure})


def _one(cursor: CursorLike, sql: str, params: object) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _create_temp_seed_tables(cursor: CursorLike) -> None:
    cursor.execute(
        """
        CREATE TEMP TABLE g15_queue_candidates (
            organization_id uuid NOT NULL,
            seq integer NOT NULL,
            party_id uuid NOT NULL,
            waitlist_id uuid NOT NULL,
            hold_id uuid NOT NULL,
            PRIMARY KEY (organization_id, seq)
        ) ON COMMIT DROP
        """
    )
    cursor.execute(
        """
        CREATE TEMP TABLE g15_slot_history (
            organization_id uuid NOT NULL,
            seq integer NOT NULL,
            opportunity_id uuid NOT NULL,
            hold_id uuid NOT NULL,
            PRIMARY KEY (organization_id, seq)
        ) ON COMMIT DROP
        """
    )


def _seed_queue_waitlist(
    cursor: CursorLike,
    *,
    organization_id: object,
    suffix: str,
) -> dict[str, Any]:
    offering_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'G15 plan offering')
        RETURNING id
        """,
        (organization_id, f"g15-offering-{suffix}"),
    )
    offering_version_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable, requestable
        ) VALUES (%s, %s, 1, 30, true, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    queue_id = _one(
        cursor,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, offering_id, queue_key, display_name
        ) VALUES (%s, %s, %s, 'G15 plan queue')
        RETURNING id
        """,
        (organization_id, offering_id, f"g15-queue-{suffix}"),
    )
    queue_subject_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name, external_ref
        ) VALUES (%s, 'person', 'G15 queue subject', %s)
        RETURNING id
        """,
        (organization_id, f"g15-queue-subject-{suffix}"),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id, offering_id,
            status, admitted_at, completed_at
        )
        SELECT %s, %s, %s, %s, 'completed',
               clock_timestamp() - interval '30 days' + value * interval '1 second',
               clock_timestamp() - interval '29 days'
        FROM generate_series(1, %s) AS value
        """,
        (
            organization_id,
            queue_id,
            queue_subject_id,
            offering_id,
            QUEUE_HISTORY_PER_TENANT,
        ),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id, offering_id,
            status, admitted_at
        ) VALUES (%s, %s, %s, %s, 'waiting', clock_timestamp() - interval '1 hour')
        """,
        (organization_id, queue_id, queue_subject_id, offering_id),
    )

    cursor.execute(
        """
        INSERT INTO g15_queue_candidates (
            organization_id, seq, party_id, waitlist_id, hold_id
        )
        SELECT %s, value, uuidv7(), uuidv7(), uuidv7()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, WAITLIST_CANDIDATES_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.parties (
            id, organization_id, party_kind, display_name, external_ref
        )
        SELECT party_id, organization_id, 'person', 'G15 candidate',
               %s || '-candidate-' || seq::text
        FROM g15_queue_candidates
        WHERE organization_id = %s
        """,
        (suffix, organization_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.waitlist_entries (
            id, organization_id, offering_id, subject_party_id, status, created_at
        )
        SELECT waitlist_id, organization_id, %s, party_id, 'active',
               clock_timestamp() - interval '2 days' + seq * interval '1 second'
        FROM g15_queue_candidates
        WHERE organization_id = %s
        """,
        (offering_id, organization_id),
    )

    target_opportunity_id = _one(
        cursor,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during, status
        ) VALUES (
            %s, %s, uuidv7(),
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'open'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.capacity_holds (
            id, organization_id, offering_version_id, subject_party_id,
            during, status, expires_at
        )
        SELECT c.hold_id, c.organization_id, %s, c.party_id,
               tstzrange(
                   clock_timestamp() + interval '1 day',
                   clock_timestamp() + interval '1 day 30 minutes',
                   '[)'
               ),
               'released', clock_timestamp() + interval '2 hours'
        FROM g15_queue_candidates c
        WHERE c.organization_id = %s
          AND c.seq <= %s
        """,
        (offering_version_id, organization_id, PRIOR_OFFERS_PER_TARGET),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, status, expires_at
        )
        SELECT c.organization_id, %s, c.waitlist_id, c.hold_id,
               'declined', clock_timestamp() + interval '1 hour'
        FROM g15_queue_candidates c
        WHERE c.organization_id = %s
          AND c.seq <= %s
        """,
        (target_opportunity_id, organization_id, PRIOR_OFFERS_PER_TARGET),
    )

    history_subject_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name, external_ref
        ) VALUES (%s, 'person', 'G15 history subject', %s)
        RETURNING id
        """,
        (organization_id, f"g15-history-subject-{suffix}"),
    )
    history_waitlist_id = _one(
        cursor,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id, status
        ) VALUES (%s, %s, %s, 'active')
        RETURNING id
        """,
        (organization_id, offering_id, history_subject_id),
    )
    cursor.execute(
        """
        INSERT INTO g15_slot_history (
            organization_id, seq, opportunity_id, hold_id
        )
        SELECT %s, value, uuidv7(), uuidv7()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, SLOT_OFFER_HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.slot_opportunities (
            id, organization_id, offering_version_id, source_event_id, during, status
        )
        SELECT opportunity_id, organization_id, %s, uuidv7(),
               tstzrange(
                   clock_timestamp() + interval '1 day',
                   clock_timestamp() + interval '1 day 30 minutes',
                   '[)'
               ),
               'closed'
        FROM g15_slot_history
        WHERE organization_id = %s
        """,
        (offering_version_id, organization_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.capacity_holds (
            id, organization_id, offering_version_id, subject_party_id,
            during, status, expires_at
        )
        SELECT hold_id, organization_id, %s, %s,
               tstzrange(
                   clock_timestamp() + interval '1 day',
                   clock_timestamp() + interval '1 day 30 minutes',
                   '[)'
               ),
               'released', clock_timestamp() + interval '2 hours'
        FROM g15_slot_history
        WHERE organization_id = %s
        """,
        (offering_version_id, history_subject_id, organization_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, status, expires_at
        )
        SELECT organization_id, opportunity_id, %s, hold_id,
               'declined', clock_timestamp() + interval '1 hour'
        FROM g15_slot_history
        WHERE organization_id = %s
        """,
        (history_waitlist_id, organization_id),
    )

    rare_subject_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name, external_ref
        ) VALUES (%s, 'person', 'G15 rare history subject', %s)
        RETURNING id
        """,
        (organization_id, f"g15-rare-subject-{suffix}"),
    )
    rare_waitlist_id = _one(
        cursor,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id, status
        ) VALUES (%s, %s, %s, 'cancelled')
        RETURNING id
        """,
        (organization_id, offering_id, rare_subject_id),
    )
    rare_opportunity_id = _one(
        cursor,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during, status
        ) VALUES (
            %s, %s, uuidv7(),
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'closed'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id),
    )
    rare_hold_id = _one(
        cursor,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id, offering_version_id, subject_party_id,
            during, status, expires_at
        ) VALUES (
            %s, %s, %s,
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'released', clock_timestamp() + interval '2 hours'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id, rare_subject_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, status, expires_at
        ) VALUES (%s, %s, %s, %s, 'declined', clock_timestamp() + interval '1 hour')
        """,
        (organization_id, rare_opportunity_id, rare_waitlist_id, rare_hold_id),
    )

    active_subject_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name, external_ref
        ) VALUES (%s, 'person', 'G15 active offer subject', %s)
        RETURNING id
        """,
        (organization_id, f"g15-active-subject-{suffix}"),
    )
    active_waitlist_id = _one(
        cursor,
        """
        INSERT INTO request_engine.waitlist_entries (
            organization_id, offering_id, subject_party_id, status
        ) VALUES (%s, %s, %s, 'active')
        RETURNING id
        """,
        (organization_id, offering_id, active_subject_id),
    )
    active_opportunity_id = _one(
        cursor,
        """
        INSERT INTO request_engine.slot_opportunities (
            organization_id, offering_version_id, source_event_id, during, status
        ) VALUES (
            %s, %s, uuidv7(),
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            'open'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id),
    )
    active_hold_id = _one(
        cursor,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id, offering_version_id, subject_party_id,
            during, status, expires_at
        )
        SELECT %s, %s, %s, o.during, 'active', clock_timestamp() + interval '2 hours'
        FROM request_engine.slot_opportunities o
        WHERE o.organization_id = %s
          AND o.id = %s
        RETURNING id
        """,
        (
            organization_id,
            offering_version_id,
            active_subject_id,
            organization_id,
            active_opportunity_id,
        ),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.slot_offers (
            organization_id, slot_opportunity_id, waitlist_entry_id,
            capacity_hold_id, status, expires_at
        ) VALUES (%s, %s, %s, %s, 'offered', clock_timestamp() + interval '1 hour')
        """,
        (organization_id, active_opportunity_id, active_waitlist_id, active_hold_id),
    )

    return {
        "organization_id": organization_id,
        "queue_id": queue_id,
        "offering_version_id": offering_version_id,
        "target_opportunity_id": target_opportunity_id,
        "rare_waitlist_id": rare_waitlist_id,
        "rare_opportunity_id": rare_opportunity_id,
        "active_opportunity_id": active_opportunity_id,
    }


def _prove_queue_paths(cursor: CursorLike, report: dict[str, Any], target: dict[str, Any]) -> None:
    organization_id = target["organization_id"]
    queue_id = target["queue_id"]
    offering_version_id = target["offering_version_id"]
    target_opportunity_id = target["target_opportunity_id"]
    rare_waitlist_id = target["rare_waitlist_id"]
    rare_opportunity_id = target["rare_opportunity_id"]
    active_opportunity_id = target["active_opportunity_id"]

    cursor.execute("ANALYZE request_engine.queue_entries")
    cursor.execute("ANALYZE request_engine.waitlist_entries")
    cursor.execute("ANALYZE request_engine.slot_offers")
    cursor.execute("ANALYZE request_engine.offering_versions")

    fifo_plan = _explain(
        cursor,
        f"""
        SELECT id
        FROM request_engine.queue_entries
        WHERE organization_id = '{organization_id}'::uuid
          AND service_queue_id = '{queue_id}'::uuid
          AND status = 'waiting'
        ORDER BY admitted_at, id
        LIMIT 1
        FOR UPDATE
        """,
    )
    _record_plan(
        report,
        name="queue_call_next_fifo",
        plan=fifo_plan,
        forbidden_seq_relations={"queue_entries"},
        max_execution_ms=20.0,
        max_shared_hit_blocks=64,
    )

    active_offer_plan = _explain(
        cursor,
        f"""
        SELECT id
        FROM request_engine.slot_offers
        WHERE organization_id = '{organization_id}'::uuid
          AND slot_opportunity_id = '{active_opportunity_id}'::uuid
          AND status = 'offered'
        FOR UPDATE
        """,
    )
    _record_plan(
        report,
        name="slot_offer_active_for_opportunity",
        plan=active_offer_plan,
        forbidden_seq_relations={"slot_offers"},
        max_execution_ms=20.0,
        max_shared_hit_blocks=64,
    )

    candidate_plan = _explain(
        cursor,
        f"""
        SELECT w.id, w.subject_party_id, w.preferred_resource_id, w.created_at
        FROM request_engine.waitlist_entries w
        JOIN request_engine.offering_versions ov
          ON ov.organization_id = w.organization_id
         AND ov.offering_id = w.offering_id
        WHERE w.organization_id = '{organization_id}'::uuid
          AND ov.id = '{offering_version_id}'::uuid
          AND w.status = 'active'
          AND (
              w.location_id IS NULL
              OR w.location_id IS NOT DISTINCT FROM NULL::uuid
          )
          AND (w.earliest_start IS NULL OR w.earliest_start <= clock_timestamp() + interval '1 day')
          AND (w.latest_start IS NULL OR w.latest_start >= clock_timestamp() + interval '1 day')
          AND NOT (w.id = ANY(ARRAY[]::uuid[]))
          AND NOT EXISTS (
              SELECT 1
              FROM request_engine.slot_offers prior_offer
              WHERE prior_offer.organization_id = w.organization_id
                AND prior_offer.slot_opportunity_id = '{target_opportunity_id}'::uuid
                AND prior_offer.waitlist_entry_id = w.id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM request_engine.slot_offers active_offer
              WHERE active_offer.organization_id = w.organization_id
                AND active_offer.waitlist_entry_id = w.id
                AND active_offer.status = 'offered'
          )
        ORDER BY w.created_at, w.id
        FOR UPDATE OF w SKIP LOCKED
        LIMIT 1
        """,
    )
    _record_plan(
        report,
        name="waitlist_offer_candidate_fifo",
        plan=candidate_plan,
        forbidden_seq_relations={"waitlist_entries", "slot_offers"},
        max_execution_ms=50.0,
        max_shared_hit_blocks=512,
    )

    waitlist_history_plan = _explain(
        cursor,
        f"""
        SELECT 1
        FROM request_engine.slot_offers
        WHERE organization_id = '{organization_id}'::uuid
          AND waitlist_entry_id = '{rare_waitlist_id}'::uuid
        LIMIT 1
        """,
    )
    _record_plan(
        report,
        name="slot_offer_waitlist_provenance_lookup",
        plan=waitlist_history_plan,
        forbidden_seq_relations={"slot_offers"},
        max_execution_ms=20.0,
        max_shared_hit_blocks=32,
        max_rows_removed={"slot_offers": 16},
    )

    opportunity_history_plan = _explain(
        cursor,
        f"""
        SELECT 1
        FROM request_engine.slot_offers
        WHERE organization_id = '{organization_id}'::uuid
          AND slot_opportunity_id = '{rare_opportunity_id}'::uuid
        LIMIT 1
        """,
    )
    _record_plan(
        report,
        name="slot_offer_opportunity_provenance_lookup",
        plan=opportunity_history_plan,
        forbidden_seq_relations={"slot_offers"},
        max_execution_ms=20.0,
        max_shared_hit_blocks=32,
        max_rows_removed={"slot_offers": 16},
    )


def main() -> int:
    import psycopg

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema_version": 2,
        "status": "PASS",
        "cardinality": {
            "tenant_count": TENANT_COUNT,
            "queue_history_per_tenant": QUEUE_HISTORY_PER_TENANT,
            "waitlist_candidates_per_tenant": WAITLIST_CANDIDATES_PER_TENANT,
            "prior_offers_per_target_opportunity": PRIOR_OFFERS_PER_TARGET,
            "slot_offer_history_per_tenant": SLOT_OFFER_HISTORY_PER_TENANT,
        },
        "proofs": [],
        "failures": [],
    }

    with (
        psycopg.connect() as connection,
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
    ):
        _create_temp_seed_tables(cursor)
        run_suffix = uuid.uuid4().hex
        target: dict[str, Any] | None = None
        for tenant_index in range(TENANT_COUNT):
            suffix = f"{run_suffix}-{tenant_index}"
            organization_id = _one(
                cursor,
                """
                INSERT INTO request_engine.organizations (organization_key, display_name)
                VALUES (%s, 'G15 Queue plan proof')
                RETURNING id
                """,
                (f"g15-queue-plan-{suffix}",),
            )
            seeded = _seed_queue_waitlist(
                cursor,
                organization_id=organization_id,
                suffix=suffix,
            )
            if target is None:
                target = seeded

        assert target is not None
        _prove_queue_paths(cursor, report, target)

    if report["failures"]:
        report["status"] = "FAIL"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["failures"]:
        details = "; ".join(
            f"{failure['name']}: {failure['reason']}" for failure in report["failures"]
        )
        raise SystemExit(f"measured queue query plan failures: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
