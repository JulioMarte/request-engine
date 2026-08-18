from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

import prove_v3_booking_query_plans as base

TENANT_COUNT = 4
HISTORY_PER_TENANT = 1_500


def _explain(cursor: base.CursorLike, sql: str, params: object = ()) -> dict[str, Any]:
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params)
    row = cursor.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload[0]


def _one(cursor: base.CursorLike, sql: str, params: object) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _seed_tenant(cursor: base.CursorLike, suffix: str) -> dict[str, Any]:
    organization_id = _one(
        cursor,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'G15 operational plan proof')
        RETURNING id
        """,
        (f"g15-operational-{suffix}",),
    )
    party_id = _one(
        cursor,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'G15 operational subject')
        RETURNING id
        """,
        (organization_id,),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified, active
        )
        SELECT %s, %s, 'email',
               'history-' || value || '-' || %s || '@example.test', false, true
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, party_id, suffix, HISTORY_PER_TENANT),
    )
    contact_point_id = _one(
        cursor,
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified, active
        ) VALUES (%s, %s, 'email', %s, true, true)
        RETURNING id
        """,
        (organization_id, party_id, f"target-{suffix}@example.test"),
    )

    task_id = _one(
        cursor,
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, purpose, channel_policy,
            template_key, template_version, render_context, status
        ) VALUES (
            %s, %s, 'g15', '{"channels":[{"channel":"email","provider_key":"test"}]}'::jsonb,
            'g15', 1, '{}'::jsonb, 'pending'
        )
        RETURNING id
        """,
        (organization_id, party_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, status, result_data
        )
        SELECT %s, %s, value, 'email', 'test',
               'g15:' || %s || ':' || value, 'failed', '{"retryable":true}'::jsonb
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, task_id, suffix, HISTORY_PER_TENANT),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at, status, max_attempts
        )
        SELECT %s, 'communications', 'dispatch_task', 1,
               'CommunicationTask', uuidv7(),
               jsonb_build_object('communication_task_id', uuidv7()::text),
               'g15-history-' || %s || '-' || value,
               clock_timestamp() + interval '2 days' + value * interval '1 second',
               clock_timestamp() + interval '2 days' + value * interval '1 second',
               'pending', 8
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, suffix, HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at, status, max_attempts
        ) VALUES (
            %s, 'communications', 'dispatch_task', 1,
            'CommunicationTask', %s,
            jsonb_build_object('communication_task_id', %s::uuid::text),
            %s, clock_timestamp() + interval '1 day',
            clock_timestamp() + interval '1 day', 'pending', 8
        )
        """,
        (organization_id, task_id, task_id, f"g15-target-{suffix}"),
    )

    offering_id = _one(
        cursor,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'G15 operational offering')
        RETURNING id
        """,
        (organization_id, f"g15-operational-offering-{suffix}"),
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
        ) VALUES (%s, %s, 'G15 operational capability')
        RETURNING id
        """,
        (organization_id, f"g15-operational-capability-{suffix}"),
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
        ) VALUES (%s, %s, 'G15 operational resource', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"g15-operational-resource-{suffix}"),
    )
    reservation_id = _one(
        cursor,
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id, during, status
        ) VALUES (
            %s, %s, %s,
            tstzrange(clock_timestamp() + interval '1 day',
                      clock_timestamp() + interval '1 day 30 minutes', '[)'),
            'confirmed'
        )
        RETURNING id
        """,
        (organization_id, offering_version_id, party_id),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.attendance_responses (
            organization_id, reservation_id, response, source_key, responded_at
        )
        SELECT %s, %s,
               CASE WHEN value %% 2 = 0 THEN 'accepted' ELSE 'declined' END,
               'g15-' || value,
               timestamptz '2024-01-01 00:00:00+00' + value * interval '1 minute'
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, reservation_id, HISTORY_PER_TENANT),
    )

    global_identity_id = _one(
        cursor,
        """
        INSERT INTO request_engine.global_identities (
            identity_kind, created_authority_ref, creation_reason
        ) VALUES ('person', 'g15-proof', 'query-plan evidence')
        RETURNING id
        """,
        (),
    )
    shared_identity_id = _one(
        cursor,
        """
        INSERT INTO request_engine.shared_capacity_identities (
            global_identity_id, created_authority_ref, creation_reason
        ) VALUES (%s, 'g15-proof', 'query-plan evidence')
        RETURNING id
        """,
        (global_identity_id,),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.shared_capacity_bindings (
            shared_capacity_identity_id, organization_id, resource_id,
            authorized_by, authorization_reason
        ) VALUES (%s, %s, %s, 'g15-proof', 'query-plan evidence')
        """,
        (shared_identity_id, organization_id, resource_id),
    )

    cursor.execute(
        """
        INSERT INTO request_engine.capacity_claims (
            organization_id, resource_id, requirement_id, reservation_id,
            during, quantity, status, released_at
        )
        SELECT %s, %s, %s, %s,
               tstzrange(
                   timestamptz '2020-01-01 00:00:00+00' + value * interval '2 hours',
                   timestamptz '2020-01-01 01:00:00+00' + value * interval '2 hours', '[)'),
               1, 'released', clock_timestamp()
        FROM generate_series(1, %s) AS value
        """,
        (organization_id, resource_id, requirement_id, reservation_id, HISTORY_PER_TENANT),
    )
    cursor.execute(
        """
        INSERT INTO request_engine.shared_capacity_claim_links (
            capacity_claim_id, shared_capacity_identity_id
        )
        SELECT id, %s
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND resource_id = %s
          AND status = 'released'
        """,
        (shared_identity_id, organization_id, resource_id),
    )
    active_claim_id = _one(
        cursor,
        """
        INSERT INTO request_engine.capacity_claims (
            organization_id, resource_id, requirement_id, reservation_id,
            during, quantity, status
        )
        SELECT %s, %s, %s, r.id, r.during, 1, 'active'
        FROM request_engine.reservations r
        WHERE r.organization_id = %s AND r.id = %s
        RETURNING id
        """,
        (organization_id, resource_id, requirement_id, organization_id, reservation_id),
    )

    return {
        "organization_id": organization_id,
        "party_id": party_id,
        "contact_point_id": contact_point_id,
        "task_id": task_id,
        "reservation_id": reservation_id,
        "resource_id": resource_id,
        "shared_identity_id": shared_identity_id,
        "active_claim_id": active_claim_id,
    }


def _prove(cursor: base.CursorLike, report: dict[str, Any], target: dict[str, Any]) -> None:
    for relation in (
        "party_contact_points",
        "communication_deliveries",
        "scheduled_actions",
        "reservations",
        "attendance_responses",
        "shared_capacity_bindings",
        "shared_capacity_claim_links",
        "capacity_claims",
    ):
        cursor.execute(f"ANALYZE request_engine.{relation}")

    org = target["organization_id"]
    party = target["party_id"]
    task = target["task_id"]
    reservation = target["reservation_id"]
    resource = target["resource_id"]
    shared_identity = target["shared_identity_id"]
    active_claim = target["active_claim_id"]

    latest_delivery = _explain(
        cursor,
        """
        SELECT * FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        ORDER BY attempt_no DESC LIMIT 1 FOR UPDATE
        """,
        (org, task),
    )
    base._record(
        report,
        name="communications_latest_delivery",
        plan=latest_delivery,
        relations={"communication_deliveries"},
        max_rows_removed={"communication_deliveries": 8},
        max_shared_hit_blocks=16,
    )

    contacts = _explain(
        cursor,
        """
        SELECT id, channel, normalized_value
        FROM request_engine.party_contact_points
        WHERE organization_id = %s AND party_id = %s AND active AND verified
        ORDER BY created_at, id
        """,
        (org, party),
    )
    base._record(
        report,
        name="communications_verified_contacts",
        plan=contacts,
        relations={"party_contact_points"},
        max_rows_removed={"party_contact_points": 16},
        max_shared_hit_blocks=32,
    )

    future_dispatch = _explain(
        cursor,
        """
        SELECT EXISTS (
            SELECT 1 FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND owner_module = 'communications'
              AND action_type = 'dispatch_task'
              AND action_version = 1
              AND subject_kind = 'CommunicationTask'
              AND subject_id = %s
              AND CASE
                  WHEN pg_catalog.pg_input_is_valid(payload ->> 'communication_task_id', 'uuid')
                  THEN (payload ->> 'communication_task_id')::uuid = %s
                  ELSE false
              END
              AND status IN ('pending', 'leased')
              AND attempt_count < max_attempts
              AND execute_at > clock_timestamp()
        )
        """,
        (org, task, task),
    )
    base._record(
        report,
        name="communications_future_dispatch",
        plan=future_dispatch,
        relations={"scheduled_actions"},
        max_rows_removed={"scheduled_actions": 32},
        max_shared_hit_blocks=64,
    )

    reservation_status = _explain(
        cursor,
        """
        SELECT reservation_id, attendance_status
        FROM request_read.reservation_status_v1
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (org, reservation),
    )
    base._record(
        report,
        name="reservation_status_latest_attendance",
        plan=reservation_status,
        relations={"reservations", "attendance_responses"},
        max_rows_removed={"reservations": 8, "attendance_responses": 8},
        max_shared_hit_blocks=24,
    )

    shared_root = _explain(
        cursor,
        """
        SELECT s.id
        FROM request_engine.shared_capacity_identities s
        JOIN request_engine.shared_capacity_bindings b
          ON b.shared_capacity_identity_id = s.id AND b.status = 'active'
        WHERE b.organization_id = %s AND b.resource_id = %s
          AND s.status = 'active'
        ORDER BY s.id
        FOR UPDATE OF s
        """,
        (org, resource),
    )
    base._record(
        report,
        name="shared_capacity_root_resolution",
        plan=shared_root,
        relations={"shared_capacity_bindings", "shared_capacity_identities"},
        max_rows_removed={"shared_capacity_bindings": 8},
        max_shared_hit_blocks=24,
    )

    shared_conflict = _explain(
        cursor,
        """
        SELECT EXISTS (
            SELECT 1
            FROM request_engine.shared_capacity_claim_links link
            JOIN request_engine.capacity_claims c ON c.id = link.capacity_claim_id
            LEFT JOIN request_engine.reservations r
              ON r.organization_id = c.organization_id AND r.id = c.reservation_id
            LEFT JOIN request_engine.capacity_holds h
              ON h.organization_id = c.organization_id AND h.id = c.hold_id
            WHERE link.shared_capacity_identity_id = %s
              AND c.id <> %s
              AND c.status = 'active'
              AND c.during && tstzrange(
                  clock_timestamp() + interval '1 day',
                  clock_timestamp() + interval '1 day 30 minutes', '[)')
              AND (
                  (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
                  OR (c.reservation_id IS NULL AND h.status = 'active'
                      AND h.expires_at > clock_timestamp())
              )
        )
        """,
        (shared_identity, uuid.UUID(int=0)),
    )
    base._record(
        report,
        name="shared_capacity_live_conflict",
        plan=shared_conflict,
        relations={"shared_capacity_claim_links", "capacity_claims"},
        max_rows_removed={"shared_capacity_claim_links": 32, "capacity_claims": 32},
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
        suffix = uuid.uuid4().hex
        target: dict[str, Any] | None = None
        for tenant_index in range(TENANT_COUNT):
            seeded = _seed_tenant(cursor, f"{suffix}-{tenant_index}")
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
        raise SystemExit(f"measured operational query-plan failures: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
