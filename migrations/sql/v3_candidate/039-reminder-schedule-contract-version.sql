BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- ReminderPlan schedule_spec is a versioned typed document. Aggregate revision
-- remains optimistic-concurrency state and must not double as document schema
-- version. Existing V3 rows were all produced by the v1 daily_times contract,
-- so backfill only rows that have no explicit document version.
UPDATE request_engine.reminder_plans
SET schedule_spec = jsonb_set(schedule_spec, '{version}', '1'::jsonb, true)
WHERE schedule_spec ->> 'type' = 'daily_times'
  AND NOT (schedule_spec ? 'version');

ALTER TABLE request_engine.reminder_plans
    ADD CONSTRAINT reminder_plans_schedule_contract_version_ck
    CHECK (
        jsonb_typeof(schedule_spec) = 'object'
        AND schedule_spec ->> 'type' = 'daily_times'
        AND schedule_spec ? 'version'
        AND jsonb_typeof(schedule_spec -> 'version') = 'number'
        AND schedule_spec -> 'version' = '1'::jsonb
    );

-- Active reminder work created before plan-revision provenance was added must
-- be upgraded before the runtime starts failing closed on missing provenance.
-- Terminal ScheduledAction history is intentionally left untouched.
UPDATE request_engine.scheduled_actions AS action
SET payload = jsonb_set(
    action.payload,
    '{plan_revision}',
    to_jsonb(plan.revision),
    true
)
FROM request_engine.reminder_plans AS plan
WHERE action.organization_id = plan.organization_id
  AND action.owner_module = 'communications'
  AND action.action_type = 'materialize_reminder_occurrence'
  AND action.action_version = 1
  AND action.subject_kind = 'ReminderPlan'
  AND action.subject_id = plan.id
  AND action.status IN ('pending', 'leased')
  AND NOT (action.payload ? 'plan_revision');

COMMIT;
