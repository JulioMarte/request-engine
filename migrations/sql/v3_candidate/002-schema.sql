BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE TABLE request_engine.organizations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_key text NOT NULL UNIQUE,
    display_name text NOT NULL,
    public_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (organization_key <> ''),
    CHECK (display_name <> ''),
    CHECK (jsonb_typeof(public_profile) = 'object')
);

CREATE TABLE request_engine.principals (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    principal_kind text NOT NULL,
    external_subject text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, principal_kind, external_subject),
    CHECK (principal_kind IN ('human', 'service', 'agent', 'integration', 'provider', 'worker')),
    CHECK (external_subject <> '')
);

CREATE TABLE request_engine.parties (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_kind text NOT NULL,
    display_name text NOT NULL,
    external_ref text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, external_ref),
    CHECK (party_kind IN ('person', 'organization')),
    CHECK (display_name <> '')
);

CREATE TABLE request_engine.party_contact_points (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    verified boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, party_id, channel, normalized_value),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (channel IN ('phone', 'email', 'whatsapp')),
    CHECK (normalized_value <> '')
);

CREATE TABLE request_engine.representations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    represented_party_id uuid NOT NULL,
    scope_key text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, represented_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (scope_key <> ''),
    CHECK (status IN ('active', 'revoked', 'expired')),
    CHECK (valid_until IS NULL OR valid_until > valid_from),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.locations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    location_key text NOT NULL,
    display_name text NOT NULL,
    timezone text NOT NULL,
    public_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, location_key),
    CHECK (location_key <> ''),
    CHECK (display_name <> ''),
    CHECK (timezone <> ''),
    CHECK (jsonb_typeof(public_data) = 'object')
);

CREATE TABLE request_engine.offerings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    offering_key text NOT NULL,
    display_name text NOT NULL,
    description text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, offering_key),
    CHECK (offering_key <> ''),
    CHECK (display_name <> '')
);

CREATE TABLE request_engine.offering_versions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    version integer NOT NULL,
    duration_minutes integer,
    bookable boolean NOT NULL DEFAULT false,
    requestable boolean NOT NULL DEFAULT true,
    booking_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    public_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, offering_id, version),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    CHECK (version > 0),
    CHECK (duration_minutes IS NULL OR duration_minutes > 0),
    CHECK (NOT bookable OR duration_minutes IS NOT NULL),
    CHECK (jsonb_typeof(booking_policy) = 'object'),
    CHECK (jsonb_typeof(public_data) = 'object')
);

CREATE TABLE request_engine.resource_capabilities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    capability_key text NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, capability_key),
    CHECK (capability_key <> ''),
    CHECK (display_name <> '')
);

CREATE TABLE request_engine.offering_resource_requirements (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    ordinal integer NOT NULL,
    quantity integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, offering_version_id, ordinal),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    FOREIGN KEY (organization_id, capability_id)
        REFERENCES request_engine.resource_capabilities (organization_id, id),
    CHECK (ordinal > 0),
    CHECK (quantity > 0)
);

CREATE TABLE request_engine.resources (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    location_id uuid,
    resource_key text NOT NULL,
    display_name text NOT NULL,
    capacity_model text NOT NULL,
    capacity_units integer NOT NULL DEFAULT 1,
    active boolean NOT NULL DEFAULT true,
    availability_revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, resource_key),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (resource_key <> ''),
    CHECK (display_name <> ''),
    CHECK (capacity_model IN ('exclusive', 'units')),
    CHECK (capacity_units > 0),
    CHECK (capacity_model <> 'exclusive' OR capacity_units = 1),
    CHECK (availability_revision > 0)
);

CREATE TABLE request_engine.resource_capability_assignments (
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, resource_id, capability_id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, capability_id)
        REFERENCES request_engine.resource_capabilities (organization_id, id)
);

CREATE TABLE request_engine.availability_schedules (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    weekday smallint NOT NULL,
    local_start time NOT NULL,
    local_end time NOT NULL,
    timezone text NOT NULL,
    valid_from date,
    valid_until date,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    CHECK (weekday BETWEEN 0 AND 6),
    CHECK (local_start < local_end),
    CHECK (timezone <> ''),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

CREATE TABLE request_engine.schedule_exceptions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    CHECK (exception_kind IN ('available', 'unavailable')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during))
);

CREATE TABLE request_engine.request_definitions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    request_key text NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, request_key),
    CHECK (request_key <> ''),
    CHECK (display_name <> '')
);

CREATE TABLE request_engine.request_definition_versions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    request_definition_id uuid NOT NULL,
    version integer NOT NULL,
    input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_schema jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, request_definition_id, version),
    FOREIGN KEY (organization_id, request_definition_id)
        REFERENCES request_engine.request_definitions (organization_id, id),
    CHECK (version > 0),
    CHECK (jsonb_typeof(input_schema) = 'object'),
    CHECK (result_schema IS NULL OR jsonb_typeof(result_schema) = 'object')
);

CREATE TABLE request_engine.requests (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    request_definition_version_id uuid NOT NULL,
    requester_party_id uuid,
    recipient_party_id uuid,
    status text NOT NULL DEFAULT 'open',
    payload jsonb NOT NULL,
    result_payload jsonb,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, request_definition_version_id)
        REFERENCES request_engine.request_definition_versions (organization_id, id),
    FOREIGN KEY (organization_id, requester_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, recipient_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (status IN ('open', 'completed', 'cancelled', 'failed')),
    CHECK (revision > 0),
    CHECK ((status = 'open' AND completed_at IS NULL) OR status <> 'open')
);

CREATE TABLE request_engine.request_participants (
    organization_id uuid NOT NULL,
    request_id uuid NOT NULL,
    party_id uuid NOT NULL,
    role_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, request_id, party_id, role_key),
    FOREIGN KEY (organization_id, request_id)
        REFERENCES request_engine.requests (organization_id, id),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (role_key <> '')
);

CREATE TABLE request_engine.external_correlations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    request_id uuid,
    correlation_kind text NOT NULL,
    provider_key text NOT NULL,
    external_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, correlation_kind, provider_key, external_key),
    FOREIGN KEY (organization_id, request_id)
        REFERENCES request_engine.requests (organization_id, id),
    CHECK (correlation_kind <> ''),
    CHECK (provider_key <> ''),
    CHECK (external_key <> '')
);

CREATE TABLE request_engine.capacity_holds (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    during tstzrange NOT NULL,
    status text NOT NULL DEFAULT 'active',
    expires_at timestamptz NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (status IN ('active', 'consumed', 'released', 'expired')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CHECK (expires_at > created_at),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.reservations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    origin_request_id uuid,
    during tstzrange NOT NULL,
    status text NOT NULL DEFAULT 'confirmed',
    booking_policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    cancelled_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, origin_request_id)
        REFERENCES request_engine.requests (organization_id, id),
    CHECK (status IN ('confirmed', 'cancelled')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CHECK (jsonb_typeof(booking_policy_snapshot) = 'object'),
    CHECK (revision > 0),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);

CREATE TABLE request_engine.capacity_claims (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    requirement_id uuid NOT NULL,
    hold_id uuid,
    reservation_id uuid,
    during tstzrange NOT NULL,
    quantity integer NOT NULL,
    status text NOT NULL DEFAULT 'active',
    released_at timestamptz,
    replaced_by_claim_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, requirement_id)
        REFERENCES request_engine.offering_resource_requirements (organization_id, id),
    FOREIGN KEY (organization_id, hold_id)
        REFERENCES request_engine.capacity_holds (organization_id, id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, replaced_by_claim_id)
        REFERENCES request_engine.capacity_claims (organization_id, id),
    CHECK (hold_id IS NOT NULL OR reservation_id IS NOT NULL),
    CHECK (quantity > 0),
    CHECK (status IN ('active', 'released', 'replaced')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CHECK ((status = 'active') = (released_at IS NULL)),
    CHECK (status <> 'replaced' OR replaced_by_claim_id IS NOT NULL)
);

CREATE UNIQUE INDEX capacity_claims_active_reservation_requirement_uq
    ON request_engine.capacity_claims (organization_id, reservation_id, requirement_id)
    WHERE status = 'active' AND reservation_id IS NOT NULL;

CREATE UNIQUE INDEX capacity_claims_active_hold_requirement_uq
    ON request_engine.capacity_claims (organization_id, hold_id, requirement_id)
    WHERE status = 'active' AND reservation_id IS NULL AND hold_id IS NOT NULL;

CREATE INDEX capacity_claims_resource_during_idx
    ON request_engine.capacity_claims USING gist (resource_id, during);

CREATE TABLE request_engine.attendance_responses (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    response text NOT NULL,
    actor_principal_id uuid,
    source_key text NOT NULL,
    responded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, actor_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (response IN ('accepted', 'declined')),
    CHECK (source_key <> '')
);

CREATE INDEX attendance_responses_current_idx
    ON request_engine.attendance_responses (organization_id, reservation_id, responded_at DESC, id DESC);

CREATE TABLE request_engine.service_queues (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    location_id uuid,
    offering_id uuid,
    queue_key text NOT NULL,
    display_name text NOT NULL,
    policy_key text NOT NULL DEFAULT 'fifo',
    active boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, queue_key),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    CHECK (queue_key <> ''),
    CHECK (display_name <> ''),
    CHECK (policy_key = 'fifo'),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.queue_entries (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    reservation_id uuid,
    offering_id uuid,
    status text NOT NULL DEFAULT 'waiting',
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    called_at timestamptz,
    service_started_at timestamptz,
    completed_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, service_queue_id)
        REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    CHECK (status IN ('waiting', 'called', 'serving', 'completed', 'cancelled', 'no_show')),
    CHECK (revision > 0)
);

CREATE UNIQUE INDEX queue_entries_one_active_subject_uq
    ON request_engine.queue_entries (organization_id, service_queue_id, subject_party_id)
    WHERE status IN ('waiting', 'called', 'serving');

CREATE INDEX queue_entries_fifo_idx
    ON request_engine.queue_entries (organization_id, service_queue_id, status, admitted_at, id);

CREATE TABLE request_engine.waitlist_entries (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    preferred_resource_id uuid,
    earliest_start timestamptz,
    latest_start timestamptz,
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, preferred_resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    CHECK (status IN ('active', 'fulfilled', 'cancelled', 'expired')),
    CHECK (latest_start IS NULL OR earliest_start IS NULL OR latest_start >= earliest_start),
    CHECK (revision > 0)
);

CREATE INDEX waitlist_entries_selection_idx
    ON request_engine.waitlist_entries (organization_id, offering_id, status, created_at, id);

CREATE TABLE request_engine.slot_opportunities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    location_id uuid,
    source_reservation_id uuid,
    source_event_id uuid NOT NULL,
    during tstzrange NOT NULL,
    status text NOT NULL DEFAULT 'open',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, source_event_id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, source_reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    CHECK (status IN ('open', 'filled', 'closed', 'expired')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.slot_offers (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    slot_opportunity_id uuid NOT NULL,
    waitlist_entry_id uuid NOT NULL,
    capacity_hold_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'offered',
    expires_at timestamptz NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, capacity_hold_id),
    FOREIGN KEY (organization_id, slot_opportunity_id)
        REFERENCES request_engine.slot_opportunities (organization_id, id),
    FOREIGN KEY (organization_id, waitlist_entry_id)
        REFERENCES request_engine.waitlist_entries (organization_id, id),
    FOREIGN KEY (organization_id, capacity_hold_id)
        REFERENCES request_engine.capacity_holds (organization_id, id),
    CHECK (status IN ('offered', 'accepted', 'declined', 'expired', 'cancelled')),
    CHECK (expires_at > created_at),
    CHECK (revision > 0)
);

CREATE UNIQUE INDEX slot_offers_one_active_per_opportunity_uq
    ON request_engine.slot_offers (organization_id, slot_opportunity_id)
    WHERE status = 'offered';

CREATE TABLE request_engine.communication_tasks (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    recipient_party_id uuid NOT NULL,
    contact_point_id uuid,
    purpose text NOT NULL,
    source_kind text,
    source_id uuid,
    channel_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    template_key text NOT NULL,
    template_version integer NOT NULL,
    render_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key text,
    not_before timestamptz,
    expires_at timestamptz,
    status text NOT NULL DEFAULT 'pending',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, recipient_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, contact_point_id)
        REFERENCES request_engine.party_contact_points (organization_id, id),
    CHECK (purpose <> ''),
    CHECK (template_key <> ''),
    CHECK (template_version > 0),
    CHECK (jsonb_typeof(channel_policy) = 'object'),
    CHECK (jsonb_typeof(render_context) = 'object'),
    CHECK (status IN ('pending', 'delivering', 'completed', 'cancelled', 'failed')),
    CHECK (expires_at IS NULL OR not_before IS NULL OR expires_at > not_before),
    CHECK (revision > 0)
);

CREATE UNIQUE INDEX communication_tasks_dedupe_uq
    ON request_engine.communication_tasks (organization_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

CREATE TABLE request_engine.communication_deliveries (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    communication_task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    channel text NOT NULL,
    provider_key text NOT NULL,
    provider_idempotency_key text NOT NULL,
    provider_message_id text,
    status text NOT NULL,
    result_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, communication_task_id, attempt_no),
    UNIQUE (organization_id, provider_key, provider_idempotency_key),
    FOREIGN KEY (organization_id, communication_task_id)
        REFERENCES request_engine.communication_tasks (organization_id, id),
    CHECK (attempt_no > 0),
    CHECK (channel <> ''),
    CHECK (provider_key <> ''),
    CHECK (provider_idempotency_key <> ''),
    CHECK (status IN ('attempting', 'accepted', 'delivered', 'failed', 'ambiguous')),
    CHECK (jsonb_typeof(result_data) = 'object')
);

CREATE UNIQUE INDEX communication_deliveries_provider_message_uq
    ON request_engine.communication_deliveries (organization_id, provider_key, provider_message_id)
    WHERE provider_message_id IS NOT NULL;

CREATE TABLE request_engine.reminder_plans (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    purpose text NOT NULL,
    timezone text NOT NULL,
    schedule_spec jsonb NOT NULL,
    channel_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    template_key text NOT NULL,
    template_version integer NOT NULL,
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (purpose <> ''),
    CHECK (timezone <> ''),
    CHECK (jsonb_typeof(schedule_spec) = 'object'),
    CHECK (schedule_spec ->> 'type' = 'daily_times'),
    CHECK (jsonb_typeof(channel_policy) = 'object'),
    CHECK (template_key <> ''),
    CHECK (template_version > 0),
    CHECK (status IN ('active', 'cancelled', 'completed')),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.reminder_acknowledgements (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    reminder_plan_id uuid NOT NULL,
    occurrence_at timestamptz NOT NULL,
    subject_party_id uuid NOT NULL,
    source_key text NOT NULL,
    reported_value text,
    acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, reminder_plan_id, occurrence_at, subject_party_id),
    FOREIGN KEY (organization_id, reminder_plan_id)
        REFERENCES request_engine.reminder_plans (organization_id, id),
    FOREIGN KEY (organization_id, subject_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    CHECK (source_key <> '')
);

CREATE TABLE request_engine.scheduled_actions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    owner_module text NOT NULL,
    action_type text NOT NULL,
    action_version integer NOT NULL DEFAULT 1,
    subject_kind text,
    subject_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key text NOT NULL,
    execute_at timestamptz NOT NULL,
    next_attempt_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    claim_token uuid,
    lease_until timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 8,
    last_error_class text,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, dedupe_key),
    CHECK (owner_module <> ''),
    CHECK (action_type <> ''),
    CHECK (action_version > 0),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (dedupe_key <> ''),
    CHECK (status IN ('pending', 'leased', 'completed', 'cancelled', 'dead')),
    CHECK (attempt_count >= 0),
    CHECK (max_attempts > 0),
    CHECK ((status = 'leased') = (claim_token IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK (status <> 'completed' OR completed_at IS NOT NULL)
);

CREATE INDEX scheduled_actions_due_idx
    ON request_engine.scheduled_actions (next_attempt_at, id)
    WHERE status = 'pending';
CREATE INDEX scheduled_actions_reclaim_idx
    ON request_engine.scheduled_actions (lease_until, id)
    WHERE status = 'leased';

CREATE TABLE request_engine.idempotency_records (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    capability text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    status text NOT NULL DEFAULT 'in_progress',
    result_data jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, principal_id, capability, idempotency_key),
    FOREIGN KEY (organization_id, principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (capability <> ''),
    CHECK (idempotency_key <> ''),
    CHECK (request_fingerprint <> ''),
    CHECK (status IN ('in_progress', 'completed')),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL))
);

CREATE TABLE request_engine.provider_events (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    provider_key text NOT NULL,
    connection_key text NOT NULL,
    provider_event_id text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'received',
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    processed_at timestamptz,
    error_class text,
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, provider_key, connection_key, provider_event_id),
    CHECK (provider_key <> ''),
    CHECK (connection_key <> ''),
    CHECK (provider_event_id <> ''),
    CHECK (payload_hash <> ''),
    CHECK (status IN ('received', 'processed', 'rejected'))
);

CREATE TABLE request_engine.audit_records (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    actor_principal_id uuid,
    command_name text NOT NULL,
    aggregate_kind text,
    aggregate_id uuid,
    represented_party_id uuid,
    representation_id uuid,
    policy_key text,
    idempotency_record_id uuid,
    correlation_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, actor_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, represented_party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, representation_id)
        REFERENCES request_engine.representations (organization_id, id),
    FOREIGN KEY (organization_id, idempotency_record_id)
        REFERENCES request_engine.idempotency_records (organization_id, id),
    CHECK (command_name <> ''),
    CHECK (jsonb_typeof(correlation_data) = 'object'),
    CHECK (jsonb_typeof(details) = 'object')
);

CREATE TABLE request_engine.outbox_messages (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    event_type text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,
    aggregate_kind text,
    aggregate_id uuid,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    claim_token uuid,
    lease_until timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 12,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_error_class text,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    delivered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    CHECK (event_type <> ''),
    CHECK (schema_version > 0),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (status IN ('pending', 'leased', 'delivered', 'dead')),
    CHECK (attempt_count >= 0),
    CHECK (max_attempts > 0),
    CHECK ((status = 'leased') = (claim_token IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK (status <> 'delivered' OR delivered_at IS NOT NULL)
);

CREATE INDEX outbox_messages_due_idx
    ON request_engine.outbox_messages (next_attempt_at, id)
    WHERE status = 'pending';
CREATE INDEX outbox_messages_reclaim_idx
    ON request_engine.outbox_messages (lease_until, id)
    WHERE status = 'leased';

RESET ROLE;
COMMIT;
