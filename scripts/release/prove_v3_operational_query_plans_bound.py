from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

import prove_v3_booking_query_plans as booking_base
import prove_v3_operational_query_plans as base


MEASUREMENT_RELATIONS = (
    "party_contact_points",
    "communication_deliveries",
    "scheduled_actions",
    "reservations",
    "attendance_responses",
    "shared_capacity_bindings",
    "shared_capacity_claim_links",
    "capacity_claims",
)


def _explain(
    cursor: booking_base.CursorLike,
    sql: str,
    params: object = (),
) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params)
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def _one(cursor: booking_base.CursorLike, sql: str, params: object) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _seed_scale_history(
    cursor: booking_base.CursorLike,
    target: dict[str, Any],
    suffix: str,
) -> None:
    organization_id = target["organization_id"]
    party_id = target["party_id"]
    reservation_id = target["reservation_id"]
    resource_id = target["resource_id"]
    shared_identity_id = target["shared_identity_id"]
    task_id = target["task_id"]

    offering_version_id = _one(
        cursor,
        """
        SELECT offering_version_id
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, reservation_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.reservations (
            organization_id,
            offering_version_id,
            subject_party_id,
            during,
            status,
            cancelled_at
        )
        SELECT %s, %s, %s,
               tstzrange(
                   timestamptz '2018-01-01 00:00:00+00'
                       + value * interval '2 hours',
                   timestamptz '2018-01-01 01:00:00+00'
                       + value * interval '2 hours',
                   '[)'
               ),
               'cancelled',
               clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (
            organization_id,
            offering_version_id,
            party_id,
            base.HISTORY_PER_TENANT,
        ),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.shared_capacity_bindings (
            shared_capacity_identity_id,
            organization_id,
            resource_id,
            status,
            valid_from,
            valid_until,
            authorized_by,
            authorization_reason,
            revoked_by,
            revocation_reason
        )
        SELECT %s, %s, %s,
               'revoked',
               timestamptz '2019-01-01 00:00:00+00'
                   + value * interval '2 hours',
               timestamptz '2019-01-01 01:00:00+00'
                   + value * interval '2 hours',
               'g15-proof',
               'query-plan evidence',
               'g15-proof',
               'query-plan evidence'
        FROM generate_series(1, %s) AS value
        """,
        (
            shared_identity_id,
            organization_id,
            resource_id,
            base.HISTORY_PER_TENANT,
        ),
    )

    delivery_id = _one(
        cursor,
        """
        SELECT id
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s
          AND communication_task_id = %s
        ORDER BY attempt_no DESC
        LIMIT 1
        """,
        (organization_id, task_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            action_version,
            subject_kind,
            subject_id,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            max_attempts
        )
        SELECT %s, 'communications', 'reconcile_delivery', 1,
               'CommunicationDelivery', uuidv7(),
               jsonb_build_object('delivery_id', uuidv7()::text),
               'g15-reconcile-history-' || %s || '-' || value,
               clock_timestamp() + interval '3 days'
                   + value * interval '1 second',
               clock_timestamp() + interval '3 days'
                   + value * interval '1 second',
               'pending', 12
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, base.HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            action_version,
            subject_kind,
            subject_id,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            max_attempts
        ) VALUES (
            %s, 'communications', 'reconcile_delivery', 1,
            'CommunicationDelivery', %s,
            jsonb_build_object('delivery_id', %s::uuid::text),
            %s,
            clock_timestamp() + interval '1 day',
            clock_timestamp() + interval '1 day',
            'pending', 12
        )
        """,
        (
            organization_id,
            delivery_id,
            delivery_id,
            f"g15-reconcile-target-{suffix}",
        ),
    )
    target["delivery_id"] = delivery_id
    target["global_identity_id"] = _one(
        cursor,
        """
        SELECT global_identity_id
        FROM request_engine.shared_capacity_identities
        WHERE id = %s
        """,
        (shared_identity_id,),
    )


def _vacuum_measurement_relations(connection: Any) -> None:
    for relation in MEASUREMENT_RELATIONS:
        connection.execute(f"VACUUM (ANALYZE) request_engine.{relation}")


def _prove_reconciliation(
    cursor: booking_base.CursorLike,
    report: dict[str, Any],
    target: dict[str, Any],
) -> None:
    organization_id = target["organization_id"]
    delivery_id = target["delivery_id"]
    db_now = _one(cursor, "SELECT clock_timestamp()", ())
    plan = _explain(
        cursor,
        """
        SELECT EXISTS (
            SELECT 1
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND owner_module = 'communications'
              AND action_type = 'reconcile_delivery'
              AND action_version = 1
              AND subject_kind = 'CommunicationDelivery'
              AND subject_id = %s
              AND CASE
                  WHEN pg_catalog.pg_input_is_valid(
                      payload ->> 'delivery_id', 'uuid'
                  )
                  THEN (payload ->> 'delivery_id')::uuid = %s
                  ELSE false
              END
              AND status IN ('pending', 'leased')
              AND attempt_count < max_attempts
              AND execute_at > %s
        )
        """,
        (organization_id, delivery_id, delivery_id, db_now),
    )
    booking_base._record(
        report,
        name="communications_future_reconciliation",
        plan=plan,
        relations={"scheduled_actions"},
        max_rows_removed={"scheduled_actions": 32},
        max_shared_hit_blocks=64,
    )


def _cleanup_seeded_tenants(
    cursor: booking_base.CursorLike,
    targets: list[dict[str, Any]],
) -> None:
    cursor.execute("SET LOCAL session_replication_role = replica")
    for target in targets:
        organization_id = target["organization_id"]
        cursor.execute(
            "DELETE FROM request_engine.scheduled_actions WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.communication_deliveries WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.communication_tasks WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.attendance_responses WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            """
            DELETE FROM request_engine.shared_capacity_claim_links link
            USING request_engine.capacity_claims c
            WHERE link.capacity_claim_id = c.id
              AND c.organization_id = %s
            """,
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.capacity_claims WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.shared_capacity_bindings WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.reservations WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            """
            DELETE FROM request_engine.resource_capability_assignments
            WHERE organization_id = %s
            """,
            (organization_id,),
        )
        cursor.execute(
            """
            DELETE FROM request_engine.offering_resource_requirements
            WHERE organization_id = %s
            """,
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.resources WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.resource_capabilities WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.offering_versions WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.offerings WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.party_contact_points WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.parties WHERE organization_id = %s",
            (organization_id,),
        )
        cursor.execute(
            "DELETE FROM request_engine.shared_capacity_identities WHERE id = %s",
            (target["shared_identity_id"],),
        )
        cursor.execute(
            "DELETE FROM request_engine.global_identities WHERE id = %s",
            (target["global_identity_id"],),
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
            "reservation_history_per_tenant": base.HISTORY_PER_TENANT,
            "binding_history_per_tenant": base.HISTORY_PER_TENANT,
            "reconciliation_history_per_tenant": base.HISTORY_PER_TENANT,
        },
        "proofs": [],
        "failures": [],
    }

    targets: list[dict[str, Any]] = []
    with psycopg.connect(autocommit=True) as connection:
        run_suffix = uuid.uuid4().hex
        try:
            with connection.transaction(), connection.cursor() as cursor:
                for tenant_index in range(base.TENANT_COUNT):
                    suffix = f"{run_suffix}-{tenant_index}"
                    target = base._seed_tenant(cursor, suffix)
                    _seed_scale_history(cursor, target, suffix)
                    targets.append(target)

            _vacuum_measurement_relations(connection)

            with connection.transaction(), connection.cursor() as cursor:
                base._prove(cursor, report, targets[0])
                _prove_reconciliation(cursor, report, targets[0])
        finally:
            if targets:
                with connection.transaction(), connection.cursor() as cursor:
                    _cleanup_seeded_tenants(cursor, targets)

    if report["failures"]:
        report["status"] = "FAIL"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    if report["failures"]:
        details = "; ".join(
            f"{failure['name']}: {failure['reason']}"
            for failure in report["failures"]
        )
        raise SystemExit(f"measured operational query-plan failures: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
