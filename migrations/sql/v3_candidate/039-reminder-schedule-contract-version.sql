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
        AND jsonb_typeof(schedule_spec -> 'version') = 'number'
        AND schedule_spec -> 'version' = '1'::jsonb
    );

COMMIT;
