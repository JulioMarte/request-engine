BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

ALTER TABLE request_engine.outbox_messages
    ADD COLUMN correlation_data jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE request_engine.outbox_messages
    ADD CONSTRAINT outbox_messages_correlation_data_object_ck
    CHECK (jsonb_typeof(correlation_data) = 'object');

ALTER TABLE request_engine.scheduled_actions
    ADD COLUMN correlation_data jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE request_engine.scheduled_actions
    ADD CONSTRAINT scheduled_actions_correlation_data_object_ck
    CHECK (jsonb_typeof(correlation_data) = 'object');

COMMENT ON COLUMN request_engine.outbox_messages.correlation_data IS
    'Durable request/causation metadata copied from trusted transaction context.';

COMMENT ON COLUMN request_engine.scheduled_actions.correlation_data IS
    'Durable request/causation metadata copied from trusted transaction context.';

COMMIT;
