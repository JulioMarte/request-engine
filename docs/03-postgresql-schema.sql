-- Request Engine V2.6 — PostgreSQL reference schema
-- Target: PostgreSQL 18+
-- Canonical documents:
--   docs/00-product-definition.md
--   docs/01-architecture-v2.md
--   docs/02-pre-sql-domain-contract.md
--
-- Physical conventions
-- --------------------
-- * snake_case, unquoted identifiers, explicit constraint/index names.
-- * bigint GENERATED ALWAYS AS IDENTITY for internal FK/lock keys.
-- * uuidv7() for public identifiers. Public IDs never grant authority.
-- * organization_id participates in every authoritative tenant-owned FK.
-- * timestamptz for instants; reservable intervals are bounded [start,end).
-- * monetary values are integer minor units + ISO-4217 currency code.
-- * jsonb stores snapshots/config/provenance, never critical untyped FKs.
-- * historical outcome/financial/audit facts are append-oriented.
-- * cross-row races serialize on stable rows described by docs/02.
--
-- PostgreSQL 18 is intentional: uuidv7() is native. btree_gist is a trusted
-- PostgreSQL extension and is used only to support GiST operator classes.

BEGIN;

CREATE SCHEMA IF NOT EXISTS request_engine;
SET search_path = request_engine, public;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ==========================================================================
-- Utility functions
-- ==========================================================================

CREATE OR REPLACE FUNCTION request_engine.prevent_fact_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = '55000';
END;
$$;

CREATE OR REPLACE FUNCTION request_engine.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

-- ==========================================================================
-- Tenancy / identity / authority
-- ==========================================================================

CREATE TABLE organizations (
    organization_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    slug text NOT NULL,
    display_name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_organizations_public_id UNIQUE (public_id),
    CONSTRAINT uq_organizations_slug UNIQUE (slug),
    CONSTRAINT ck_organizations_slug CHECK (slug = lower(slug) AND slug ~ '^[a-z0-9][a-z0-9_-]{1,62}$'),
    CONSTRAINT ck_organizations_status CHECK (status IN ('active','suspended','closed'))
);

CREATE TABLE principals (
    principal_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    principal_kind text NOT NULL,
    display_name text,
    external_subject text,
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_principals_public_id UNIQUE (public_id),
    CONSTRAINT uq_principals_tenant_key UNIQUE (organization_id, principal_id),
    CONSTRAINT uq_principals_external_subject UNIQUE (organization_id, external_subject),
    CONSTRAINT fk_principals_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_principals_kind CHECK (principal_kind IN ('human','employee','service_account','agent_runtime','provider','worker')),
    CONSTRAINT ck_principals_status CHECK (status IN ('active','disabled','revoked')),
    CONSTRAINT ck_principals_revision CHECK (revision > 0)
);

CREATE TABLE parties (
    party_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    party_kind text NOT NULL,
    display_name text NOT NULL,
    external_ref text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_parties_public_id UNIQUE (public_id),
    CONSTRAINT uq_parties_tenant_key UNIQUE (organization_id, party_id),
    CONSTRAINT uq_parties_external_ref UNIQUE (organization_id, external_ref),
    CONSTRAINT fk_parties_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_parties_kind CHECK (party_kind IN ('person','organization'))
);

CREATE TABLE representations (
    representation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    represented_party_id bigint NOT NULL,
    authorized_principal_id bigint,
    authorized_party_id bigint,
    scope_code text NOT NULL,
    source_kind text NOT NULL,
    source_reference text,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    verified_at timestamptz,
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    revoked_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_representations_public_id UNIQUE (public_id),
    CONSTRAINT uq_representations_tenant_key UNIQUE (organization_id, representation_id),
    CONSTRAINT fk_representations_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_representations_represented_party FOREIGN KEY (organization_id, represented_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT fk_representations_authorized_principal FOREIGN KEY (organization_id, authorized_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT fk_representations_authorized_party FOREIGN KEY (organization_id, authorized_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT ck_representations_actor_xor CHECK (num_nonnulls(authorized_principal_id, authorized_party_id) = 1),
    CONSTRAINT ck_representations_validity CHECK (valid_until IS NULL OR valid_until > valid_from),
    CONSTRAINT ck_representations_revision CHECK (revision > 0)
);

-- ==========================================================================
-- Offerings / requests / typed scope
-- ==========================================================================

CREATE TABLE offerings (
    offering_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    code text NOT NULL,
    offering_kind text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_offerings_public_id UNIQUE (public_id),
    CONSTRAINT uq_offerings_tenant_key UNIQUE (organization_id, offering_id),
    CONSTRAINT uq_offerings_code UNIQUE (organization_id, code),
    CONSTRAINT fk_offerings_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_offerings_kind CHECK (offering_kind IN ('service','product','package','custom')),
    CONSTRAINT ck_offerings_status CHECK (status IN ('draft','active','inactive','retired'))
);

CREATE TABLE offering_versions (
    offering_version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    offering_id bigint NOT NULL,
    version_no integer NOT NULL,
    name text NOT NULL,
    description text,
    fulfillment_model text NOT NULL,
    excess_policy text,
    unit_code text,
    configuration_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
    outcome_definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    retired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_offering_versions_tenant_key UNIQUE (organization_id, offering_version_id),
    CONSTRAINT uq_offering_versions_number UNIQUE (organization_id, offering_id, version_no),
    CONSTRAINT fk_offering_versions_offering FOREIGN KEY (organization_id, offering_id)
        REFERENCES offerings (organization_id, offering_id) ON DELETE RESTRICT,
    CONSTRAINT ck_offering_versions_version CHECK (version_no > 0),
    CONSTRAINT ck_offering_versions_model CHECK (fulfillment_model IN ('binary','quantity','components','external_authoritative')),
    CONSTRAINT ck_offering_versions_quantity_model CHECK (
        (fulfillment_model = 'quantity' AND excess_policy IN ('reject_excess','allow_excess') AND unit_code IS NOT NULL)
        OR (fulfillment_model <> 'quantity' AND excess_policy IS NULL)
    ),
    CONSTRAINT ck_offering_versions_effective CHECK (retired_at IS NULL OR retired_at > effective_from)
);

CREATE TABLE requests (
    request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_type text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    completion_validity text,
    revision bigint NOT NULL DEFAULT 1,
    workflow_key text NOT NULL,
    workflow_version text NOT NULL,
    completion_policy_key text,
    completion_policy_version text,
    created_by_principal_id bigint,
    completed_at timestamptz,
    terminal_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_requests_public_id UNIQUE (public_id),
    CONSTRAINT uq_requests_tenant_key UNIQUE (organization_id, request_id),
    CONSTRAINT fk_requests_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_requests_creator FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_requests_type CHECK (request_type IN ('reserve_offering','purchase_offering','request_quote','request_information','request_callback','reschedule_reservation','cancel_reservation','submit_intake')),
    CONSTRAINT ck_requests_status CHECK (status IN ('active','waiting','completed','cancelled','failed_terminal')),
    CONSTRAINT ck_requests_completion CHECK (
        (status = 'completed' AND completion_validity IN ('valid','under_review','invalidated') AND completed_at IS NOT NULL)
        OR (status <> 'completed' AND completion_validity IS NULL AND completed_at IS NULL)
    ),
    CONSTRAINT ck_requests_terminal_at CHECK (
        (status IN ('completed','cancelled','failed_terminal') AND terminal_at IS NOT NULL)
        OR (status IN ('active','waiting') AND terminal_at IS NULL)
    ),
    CONSTRAINT ck_requests_revision CHECK (revision > 0)
);

CREATE TABLE request_participants (
    request_participant_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    request_id bigint NOT NULL,
    party_id bigint NOT NULL,
    role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_request_participants_tenant_key UNIQUE (organization_id, request_participant_id),
    CONSTRAINT uq_request_participants_role UNIQUE (organization_id, request_id, party_id, role),
    CONSTRAINT fk_request_participants_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_request_participants_party FOREIGN KEY (organization_id, party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT ck_request_participants_role CHECK (role IN ('requester','recipient','payer','guardian','authorized_contact'))
);

CREATE TABLE offering_selections (
    offering_selection_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    offering_version_id bigint NOT NULL,
    recipient_party_id bigint,
    quantity numeric(28,9) NOT NULL,
    unit_code text NOT NULL,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    historical_snapshot jsonb NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_offering_selections_public_id UNIQUE (public_id),
    CONSTRAINT uq_offering_selections_tenant_key UNIQUE (organization_id, offering_selection_id),
    CONSTRAINT uq_offering_selections_request_key UNIQUE (organization_id, request_id, offering_selection_id),
    CONSTRAINT fk_offering_selections_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_offering_selections_version FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES offering_versions (organization_id, offering_version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_offering_selections_recipient FOREIGN KEY (organization_id, recipient_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT ck_offering_selections_quantity CHECK (quantity > 0),
    CONSTRAINT ck_offering_selections_revision CHECK (revision > 0)
);

CREATE TABLE external_correlations (
    external_correlation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    channel text NOT NULL,
    provider text NOT NULL,
    external_identity text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_external_correlations_tenant_key UNIQUE (organization_id, external_correlation_id),
    CONSTRAINT uq_external_correlations_identity UNIQUE (organization_id, channel, provider, external_identity),
    CONSTRAINT fk_external_correlations_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT
);

CREATE TABLE request_external_correlations (
    organization_id bigint NOT NULL,
    request_id bigint NOT NULL,
    external_correlation_id bigint NOT NULL,
    linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, request_id, external_correlation_id),
    CONSTRAINT fk_request_external_correlations_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_request_external_correlations_correlation FOREIGN KEY (organization_id, external_correlation_id)
        REFERENCES external_correlations (organization_id, external_correlation_id) ON DELETE RESTRICT
);

-- ==========================================================================
-- Outcome truth
-- ==========================================================================

CREATE TABLE outcome_scopes (
    outcome_scope_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    offering_selection_id bigint NOT NULL,
    recipient_party_id bigint,
    fulfillment_model text NOT NULL,
    fulfillment_model_version text NOT NULL,
    excess_policy text,
    requested_quantity numeric(28,9),
    unit_code text,
    requested_components jsonb,
    required_result jsonb,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_outcome_scopes_public_id UNIQUE (public_id),
    CONSTRAINT uq_outcome_scopes_tenant_key UNIQUE (organization_id, outcome_scope_id),
    CONSTRAINT uq_outcome_scopes_request_key UNIQUE (organization_id, request_id, outcome_scope_id),
    CONSTRAINT fk_outcome_scopes_selection FOREIGN KEY (organization_id, request_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, request_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_outcome_scopes_recipient FOREIGN KEY (organization_id, recipient_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT ck_outcome_scopes_model CHECK (fulfillment_model IN ('binary','quantity','components','external_authoritative')),
    CONSTRAINT ck_outcome_scopes_quantity CHECK (
        (fulfillment_model = 'quantity' AND requested_quantity > 0 AND unit_code IS NOT NULL AND excess_policy IN ('reject_excess','allow_excess'))
        OR (fulfillment_model <> 'quantity' AND requested_quantity IS NULL AND excess_policy IS NULL)
    ),
    CONSTRAINT ck_outcome_scopes_revision CHECK (revision > 0)
);

CREATE TABLE fulfillments (
    fulfillment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    outcome_scope_id bigint NOT NULL,
    offering_selection_id bigint NOT NULL,
    recipient_party_id bigint,
    service_session_id bigint,
    source_kind text NOT NULL,
    source_reference text,
    model text NOT NULL,
    model_version text NOT NULL,
    quantity numeric(28,9),
    unit_code text,
    components jsonb,
    result jsonb,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    recorded_by_principal_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_fulfillments_public_id UNIQUE (public_id),
    CONSTRAINT uq_fulfillments_tenant_key UNIQUE (organization_id, fulfillment_id),
    CONSTRAINT fk_fulfillments_scope FOREIGN KEY (organization_id, request_id, outcome_scope_id)
        REFERENCES outcome_scopes (organization_id, request_id, outcome_scope_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fulfillments_selection FOREIGN KEY (organization_id, request_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, request_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fulfillments_recipient FOREIGN KEY (organization_id, recipient_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fulfillments_recorder FOREIGN KEY (organization_id, recorded_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_fulfillments_model CHECK (model IN ('binary','quantity','components','external_authoritative')),
    CONSTRAINT ck_fulfillments_value CHECK (
        (model = 'quantity' AND quantity > 0 AND unit_code IS NOT NULL AND components IS NULL)
        OR (model = 'components' AND components IS NOT NULL AND quantity IS NULL)
        OR (model IN ('binary','external_authoritative') AND quantity IS NULL)
    )
);

CREATE TABLE fulfillment_corrections (
    fulfillment_correction_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    fulfillment_id bigint NOT NULL,
    outcome_scope_id bigint NOT NULL,
    correction_kind text NOT NULL,
    corrected_quantity numeric(28,9),
    corrected_components jsonb,
    corrected_result jsonb,
    reason text NOT NULL,
    source_reference text,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    corrected_by_principal_id bigint,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_fulfillment_corrections_public_id UNIQUE (public_id),
    CONSTRAINT uq_fulfillment_corrections_tenant_key UNIQUE (organization_id, fulfillment_correction_id),
    CONSTRAINT fk_fulfillment_corrections_fulfillment FOREIGN KEY (organization_id, fulfillment_id)
        REFERENCES fulfillments (organization_id, fulfillment_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fulfillment_corrections_scope FOREIGN KEY (organization_id, outcome_scope_id)
        REFERENCES outcome_scopes (organization_id, outcome_scope_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fulfillment_corrections_principal FOREIGN KEY (organization_id, corrected_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_fulfillment_corrections_kind CHECK (correction_kind IN ('invalidate','replace_value','supersede'))
);

-- Quantity reject_excess is protected by locking the OutcomeScope. Corrections
-- still require the command protocol because they may invalidate completion.
CREATE OR REPLACE FUNCTION request_engine.enforce_fulfillment_budget()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_model text;
    v_policy text;
    v_requested numeric(28,9);
    v_unit text;
    v_current numeric(38,9);
BEGIN
    SELECT fulfillment_model, excess_policy, requested_quantity, unit_code
      INTO v_model, v_policy, v_requested, v_unit
      FROM request_engine.outcome_scopes
     WHERE organization_id = NEW.organization_id
       AND outcome_scope_id = NEW.outcome_scope_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'OutcomeScope not found' USING ERRCODE = '23503';
    END IF;

    IF NEW.model <> v_model THEN
        RAISE EXCEPTION 'Fulfillment model does not match OutcomeScope' USING ERRCODE = '23514';
    END IF;

    IF v_model = 'quantity' THEN
        IF NEW.unit_code <> v_unit THEN
            RAISE EXCEPTION 'Fulfillment unit does not match OutcomeScope' USING ERRCODE = '23514';
        END IF;

        IF v_policy = 'reject_excess' THEN
            SELECT COALESCE(sum(f.quantity), 0)
              INTO v_current
              FROM request_engine.fulfillments f
             WHERE f.organization_id = NEW.organization_id
               AND f.outcome_scope_id = NEW.outcome_scope_id
               AND NOT EXISTS (
                    SELECT 1
                      FROM request_engine.fulfillment_corrections fc
                     WHERE fc.organization_id = f.organization_id
                       AND fc.fulfillment_id = f.fulfillment_id
                       AND fc.correction_kind IN ('invalidate','supersede')
               );

            IF v_current + NEW.quantity > v_requested THEN
                RAISE EXCEPTION 'Fulfillment would exceed reject_excess OutcomeScope budget'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_fulfillments_budget
BEFORE INSERT ON fulfillments
FOR EACH ROW EXECUTE FUNCTION request_engine.enforce_fulfillment_budget();

-- ==========================================================================
-- Pricing / obligations
-- ==========================================================================

CREATE TABLE price_determinations (
    price_determination_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    offering_selection_id bigint,
    currency char(3) NOT NULL,
    base_amount_minor bigint NOT NULL,
    final_amount_minor bigint NOT NULL,
    quantity_inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
    adjustments jsonb NOT NULL DEFAULT '[]'::jsonb,
    pricing_source text NOT NULL,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    override_principal_id bigint,
    override_reason text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_price_determinations_public_id UNIQUE (public_id),
    CONSTRAINT uq_price_determinations_tenant_key UNIQUE (organization_id, price_determination_id),
    CONSTRAINT fk_price_determinations_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_price_determinations_selection FOREIGN KEY (organization_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_price_determinations_override FOREIGN KEY (organization_id, override_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_price_determinations_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_price_determinations_amounts CHECK (base_amount_minor >= 0 AND final_amount_minor >= 0),
    CONSTRAINT ck_price_determinations_override CHECK ((override_principal_id IS NULL) = (override_reason IS NULL))
);

CREATE TABLE payment_requirements (
    payment_requirement_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    payer_party_id bigint NOT NULL,
    price_determination_id bigint,
    supersedes_payment_requirement_id bigint,
    purpose text NOT NULL,
    commercial_basis jsonb NOT NULL,
    payment_policy_key text NOT NULL,
    payment_policy_version text NOT NULL,
    calculation_inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
    currency char(3) NOT NULL,
    required_amount_minor bigint NOT NULL,
    disposition text NOT NULL DEFAULT 'active',
    due_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_requirements_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_requirements_tenant_key UNIQUE (organization_id, payment_requirement_id),
    CONSTRAINT fk_payment_requirements_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_requirements_payer FOREIGN KEY (organization_id, payer_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_requirements_price FOREIGN KEY (organization_id, price_determination_id)
        REFERENCES price_determinations (organization_id, price_determination_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_requirements_supersedes FOREIGN KEY (organization_id, supersedes_payment_requirement_id)
        REFERENCES payment_requirements (organization_id, payment_requirement_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_requirements_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_payment_requirements_amount CHECK (required_amount_minor >= 0),
    CONSTRAINT ck_payment_requirements_disposition CHECK (disposition IN ('active','waived','cancelled'))
);

-- ==========================================================================
-- Resources / capacity authority / schedules
-- ==========================================================================

CREATE TABLE resources (
    resource_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    code text NOT NULL,
    resource_kind text NOT NULL,
    display_name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    operating_location jsonb,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_resources_public_id UNIQUE (public_id),
    CONSTRAINT uq_resources_tenant_key UNIQUE (organization_id, resource_id),
    CONSTRAINT uq_resources_code UNIQUE (organization_id, code),
    CONSTRAINT fk_resources_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_resources_kind CHECK (resource_kind IN ('person','facility','room','chair','equipment','vehicle')),
    CONSTRAINT ck_resources_status CHECK (status IN ('active','unavailable','inactive','retired')),
    CONSTRAINT ck_resources_revision CHECK (revision > 0)
);

CREATE TABLE resource_capabilities (
    resource_capability_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    code text NOT NULL,
    display_name text NOT NULL,
    version_no integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_resource_capabilities_tenant_key UNIQUE (organization_id, resource_capability_id),
    CONSTRAINT uq_resource_capabilities_code_version UNIQUE (organization_id, code, version_no),
    CONSTRAINT fk_resource_capabilities_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_resource_capabilities_version CHECK (version_no > 0)
);

CREATE TABLE resource_capability_assignments (
    organization_id bigint NOT NULL,
    resource_id bigint NOT NULL,
    resource_capability_id bigint NOT NULL,
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    PRIMARY KEY (organization_id, resource_id, resource_capability_id, valid_from),
    CONSTRAINT fk_resource_capability_assignments_resource FOREIGN KEY (organization_id, resource_id)
        REFERENCES resources (organization_id, resource_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_capability_assignments_capability FOREIGN KEY (organization_id, resource_capability_id)
        REFERENCES resource_capabilities (organization_id, resource_capability_id) ON DELETE RESTRICT,
    CONSTRAINT ck_resource_capability_assignments_validity CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE TABLE resource_requirement_templates (
    resource_requirement_template_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    offering_version_id bigint NOT NULL,
    requirement_key text NOT NULL,
    capability_id bigint,
    capacity_model text NOT NULL,
    quantity numeric(20,6) NOT NULL DEFAULT 1,
    mandatory boolean NOT NULL DEFAULT true,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_resource_requirement_templates_tenant_key UNIQUE (organization_id, resource_requirement_template_id),
    CONSTRAINT uq_resource_requirement_templates_key UNIQUE (organization_id, offering_version_id, requirement_key),
    CONSTRAINT fk_resource_requirement_templates_version FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES offering_versions (organization_id, offering_version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_requirement_templates_capability FOREIGN KEY (organization_id, capability_id)
        REFERENCES resource_capabilities (organization_id, resource_capability_id) ON DELETE RESTRICT,
    CONSTRAINT ck_resource_requirement_templates_model CHECK (capacity_model IN ('exclusive','units')),
    CONSTRAINT ck_resource_requirement_templates_quantity CHECK (quantity > 0)
);

CREATE TABLE capacity_pools (
    capacity_pool_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    code text NOT NULL,
    display_name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    fungibility_policy_key text NOT NULL,
    fungibility_policy_version text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_capacity_pools_public_id UNIQUE (public_id),
    CONSTRAINT uq_capacity_pools_tenant_key UNIQUE (organization_id, capacity_pool_id),
    CONSTRAINT uq_capacity_pools_code UNIQUE (organization_id, code),
    CONSTRAINT fk_capacity_pools_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_pools_status CHECK (status IN ('active','inactive','retired')),
    CONSTRAINT ck_capacity_pools_revision CHECK (revision > 0)
);

CREATE TABLE capacity_pool_memberships (
    capacity_pool_membership_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    capacity_pool_id bigint NOT NULL,
    resource_id bigint NOT NULL,
    contribution_units numeric(20,6) NOT NULL DEFAULT 1,
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    membership_version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_capacity_pool_memberships_tenant_key UNIQUE (organization_id, capacity_pool_membership_id),
    CONSTRAINT uq_capacity_pool_memberships_version UNIQUE (organization_id, capacity_pool_id, resource_id, membership_version),
    CONSTRAINT fk_capacity_pool_memberships_pool FOREIGN KEY (organization_id, capacity_pool_id)
        REFERENCES capacity_pools (organization_id, capacity_pool_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_pool_memberships_resource FOREIGN KEY (organization_id, resource_id)
        REFERENCES resources (organization_id, resource_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_pool_memberships_units CHECK (contribution_units > 0),
    CONSTRAINT ck_capacity_pool_memberships_validity CHECK (valid_until IS NULL OR valid_until > valid_from),
    CONSTRAINT ck_capacity_pool_memberships_version CHECK (membership_version > 0)
);

CREATE TABLE capacity_authorities (
    capacity_authority_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    resource_id bigint,
    capacity_pool_id bigint,
    capacity_model text NOT NULL,
    base_capacity_units numeric(20,6) NOT NULL DEFAULT 1,
    configuration_revision bigint NOT NULL DEFAULT 1,
    schedule_revision bigint NOT NULL DEFAULT 1,
    planning_revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_capacity_authorities_public_id UNIQUE (public_id),
    CONSTRAINT uq_capacity_authorities_tenant_key UNIQUE (organization_id, capacity_authority_id),
    CONSTRAINT uq_capacity_authorities_resource UNIQUE (organization_id, resource_id),
    CONSTRAINT uq_capacity_authorities_pool UNIQUE (organization_id, capacity_pool_id),
    CONSTRAINT fk_capacity_authorities_resource FOREIGN KEY (organization_id, resource_id)
        REFERENCES resources (organization_id, resource_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_authorities_pool FOREIGN KEY (organization_id, capacity_pool_id)
        REFERENCES capacity_pools (organization_id, capacity_pool_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_authorities_target_xor CHECK (num_nonnulls(resource_id, capacity_pool_id) = 1),
    CONSTRAINT ck_capacity_authorities_model CHECK (capacity_model IN ('exclusive','units')),
    CONSTRAINT ck_capacity_authorities_units CHECK (
        (capacity_model = 'exclusive' AND base_capacity_units = 1)
        OR (capacity_model = 'units' AND base_capacity_units > 0)
    ),
    CONSTRAINT ck_capacity_authorities_revisions CHECK (configuration_revision > 0 AND schedule_revision > 0 AND planning_revision > 0)
);

CREATE TABLE availability_schedules (
    availability_schedule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    capacity_authority_id bigint NOT NULL,
    timezone_name text NOT NULL,
    schedule_definition jsonb NOT NULL,
    version_no bigint NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_availability_schedules_tenant_key UNIQUE (organization_id, availability_schedule_id),
    CONSTRAINT uq_availability_schedules_version UNIQUE (organization_id, capacity_authority_id, version_no),
    CONSTRAINT fk_availability_schedules_authority FOREIGN KEY (organization_id, capacity_authority_id)
        REFERENCES capacity_authorities (organization_id, capacity_authority_id) ON DELETE RESTRICT,
    CONSTRAINT ck_availability_schedules_version CHECK (version_no > 0),
    CONSTRAINT ck_availability_schedules_validity CHECK (effective_until IS NULL OR effective_until > effective_from)
);

CREATE TABLE schedule_exceptions (
    schedule_exception_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    capacity_authority_id bigint NOT NULL,
    exception_range tstzrange NOT NULL,
    capacity_units numeric(20,6),
    reason text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_schedule_exceptions_tenant_key UNIQUE (organization_id, schedule_exception_id),
    CONSTRAINT fk_schedule_exceptions_authority FOREIGN KEY (organization_id, capacity_authority_id)
        REFERENCES capacity_authorities (organization_id, capacity_authority_id) ON DELETE RESTRICT,
    CONSTRAINT ck_schedule_exceptions_range CHECK (NOT isempty(exception_range) AND lower_inc(exception_range) AND NOT upper_inc(exception_range) AND lower(exception_range) IS NOT NULL AND upper(exception_range) IS NOT NULL),
    CONSTRAINT ck_schedule_exceptions_capacity CHECK (capacity_units IS NULL OR capacity_units >= 0),
    CONSTRAINT ck_schedule_exceptions_revision CHECK (revision > 0)
);

CREATE TABLE planning_contexts (
    planning_context_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    context_key text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_planning_contexts_public_id UNIQUE (public_id),
    CONSTRAINT uq_planning_contexts_tenant_key UNIQUE (organization_id, planning_context_id),
    CONSTRAINT uq_planning_contexts_key UNIQUE (organization_id, context_key),
    CONSTRAINT fk_planning_contexts_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_planning_contexts_revision CHECK (revision > 0)
);

-- ==========================================================================
-- Holds / common capacity claim space
-- ==========================================================================

CREATE TABLE capacity_holds (
    capacity_hold_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    state text NOT NULL DEFAULT 'active',
    commitment_group_key text NOT NULL,
    expires_at timestamptz NOT NULL,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    confirmed_at timestamptz,
    released_at timestamptz,
    CONSTRAINT uq_capacity_holds_public_id UNIQUE (public_id),
    CONSTRAINT uq_capacity_holds_tenant_key UNIQUE (organization_id, capacity_hold_id),
    CONSTRAINT fk_capacity_holds_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_holds_state CHECK (state IN ('active','confirmed','released','expired')),
    CONSTRAINT ck_capacity_holds_expiry CHECK (expires_at > created_at),
    CONSTRAINT ck_capacity_holds_revision CHECK (revision > 0),
    CONSTRAINT ck_capacity_holds_timestamps CHECK (
        (state = 'confirmed' AND confirmed_at IS NOT NULL AND released_at IS NULL)
        OR (state = 'released' AND released_at IS NOT NULL AND confirmed_at IS NULL)
        OR (state IN ('active','expired') AND confirmed_at IS NULL AND released_at IS NULL)
    )
);

CREATE TABLE capacity_hold_requirement_intents (
    capacity_hold_requirement_intent_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    capacity_hold_id bigint NOT NULL,
    offering_selection_id bigint NOT NULL,
    resource_requirement_template_id bigint,
    requirement_key text NOT NULL,
    mandatory boolean NOT NULL DEFAULT true,
    quantity numeric(20,6) NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_capacity_hold_requirement_intents_tenant_key UNIQUE (organization_id, capacity_hold_requirement_intent_id),
    CONSTRAINT uq_capacity_hold_requirement_intents_key UNIQUE (organization_id, capacity_hold_id, requirement_key),
    CONSTRAINT fk_capacity_hold_requirement_intents_hold FOREIGN KEY (organization_id, capacity_hold_id)
        REFERENCES capacity_holds (organization_id, capacity_hold_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_hold_requirement_intents_selection FOREIGN KEY (organization_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_hold_requirement_intents_template FOREIGN KEY (organization_id, resource_requirement_template_id)
        REFERENCES resource_requirement_templates (organization_id, resource_requirement_template_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_hold_requirement_intents_quantity CHECK (quantity > 0)
);

CREATE TABLE capacity_claims (
    capacity_claim_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    capacity_authority_id bigint NOT NULL,
    claim_kind text NOT NULL,
    capacity_hold_id bigint,
    resource_allocation_id bigint,
    state text NOT NULL DEFAULT 'active',
    conflict_range tstzrange NOT NULL,
    quantity numeric(20,6) NOT NULL DEFAULT 1,
    hold_expires_at timestamptz,
    authority_configuration_revision bigint NOT NULL,
    authority_schedule_revision bigint NOT NULL,
    planning_revision bigint,
    released_at timestamptz,
    replaced_by_capacity_claim_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_capacity_claims_public_id UNIQUE (public_id),
    CONSTRAINT uq_capacity_claims_tenant_key UNIQUE (organization_id, capacity_claim_id),
    CONSTRAINT fk_capacity_claims_authority FOREIGN KEY (organization_id, capacity_authority_id)
        REFERENCES capacity_authorities (organization_id, capacity_authority_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_claims_hold FOREIGN KEY (organization_id, capacity_hold_id)
        REFERENCES capacity_holds (organization_id, capacity_hold_id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_claims_replacement FOREIGN KEY (organization_id, replaced_by_capacity_claim_id)
        REFERENCES capacity_claims (organization_id, capacity_claim_id) ON DELETE RESTRICT,
    CONSTRAINT ck_capacity_claims_kind CHECK (claim_kind IN ('hold','allocation')),
    CONSTRAINT ck_capacity_claims_owner_xor CHECK (
        (claim_kind = 'hold' AND capacity_hold_id IS NOT NULL AND resource_allocation_id IS NULL AND hold_expires_at IS NOT NULL)
        OR (claim_kind = 'allocation' AND capacity_hold_id IS NULL AND resource_allocation_id IS NOT NULL AND hold_expires_at IS NULL)
    ),
    CONSTRAINT ck_capacity_claims_state CHECK (state IN ('active','released','replaced')),
    CONSTRAINT ck_capacity_claims_range CHECK (NOT isempty(conflict_range) AND lower_inc(conflict_range) AND NOT upper_inc(conflict_range) AND lower(conflict_range) IS NOT NULL AND upper(conflict_range) IS NOT NULL),
    CONSTRAINT ck_capacity_claims_quantity CHECK (quantity > 0),
    CONSTRAINT ck_capacity_claims_revisions CHECK (authority_configuration_revision > 0 AND authority_schedule_revision > 0 AND (planning_revision IS NULL OR planning_revision > 0)),
    CONSTRAINT ck_capacity_claims_release CHECK ((state = 'active' AND released_at IS NULL) OR (state <> 'active' AND released_at IS NOT NULL))
);

CREATE INDEX ix_capacity_claims_live_overlap
    ON capacity_claims USING gist (organization_id, capacity_authority_id, conflict_range)
    WHERE state = 'active';
CREATE INDEX ix_capacity_claims_hold_expiry
    ON capacity_claims (organization_id, capacity_authority_id, hold_expires_at)
    WHERE claim_kind = 'hold' AND state = 'active';

CREATE OR REPLACE FUNCTION request_engine.enforce_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_model text;
    v_base_capacity numeric(20,6);
    v_current numeric(30,6);
    v_now timestamptz := clock_timestamp();
BEGIN
    SELECT capacity_model, base_capacity_units
      INTO v_model, v_base_capacity
      FROM request_engine.capacity_authorities
     WHERE organization_id = NEW.organization_id
       AND capacity_authority_id = NEW.capacity_authority_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'capacity authority not found for tenant' USING ERRCODE = '23503';
    END IF;

    IF NEW.claim_kind = 'hold' AND NEW.hold_expires_at <= v_now THEN
        RAISE EXCEPTION 'cannot create an already-expired hold claim' USING ERRCODE = '23514';
    END IF;

    IF NEW.state <> 'active' THEN
        RETURN NEW;
    END IF;

    IF v_model = 'exclusive' THEN
        IF EXISTS (
            SELECT 1
              FROM request_engine.capacity_claims c
             WHERE c.organization_id = NEW.organization_id
               AND c.capacity_authority_id = NEW.capacity_authority_id
               AND c.state = 'active'
               AND c.conflict_range && NEW.conflict_range
               AND (c.claim_kind = 'allocation' OR c.hold_expires_at > v_now)
               AND c.capacity_claim_id <> COALESCE(NEW.capacity_claim_id, -1)
        ) THEN
            RAISE EXCEPTION 'exclusive capacity conflict on authority %', NEW.capacity_authority_id
                USING ERRCODE = '23P01';
        END IF;
    ELSE
        SELECT COALESCE(sum(c.quantity), 0)
          INTO v_current
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = NEW.organization_id
           AND c.capacity_authority_id = NEW.capacity_authority_id
           AND c.state = 'active'
           AND c.conflict_range && NEW.conflict_range
           AND (c.claim_kind = 'allocation' OR c.hold_expires_at > v_now)
           AND c.capacity_claim_id <> COALESCE(NEW.capacity_claim_id, -1);

        IF v_current + NEW.quantity > v_base_capacity THEN
            RAISE EXCEPTION 'unit capacity exceeded on authority %', NEW.capacity_authority_id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capacity_claims_enforce
BEFORE INSERT OR UPDATE OF capacity_authority_id, state, conflict_range, quantity, hold_expires_at
ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.enforce_capacity_claim();

-- The trigger is a DB backstop using the common authority lock. Variable
-- schedule capacity, capability/location eligibility and pool fungibility are
-- validated by the command protocol against the same locked authority/revisions.

-- ==========================================================================
-- Reservations / allocations / typed targets
-- ==========================================================================

CREATE TABLE reservations (
    reservation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    originating_request_id bigint NOT NULL,
    replaces_reservation_id bigint,
    status text NOT NULL DEFAULT 'confirmed',
    planned_service_range tstzrange NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    cancelled_at timestamptz,
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_reservations_public_id UNIQUE (public_id),
    CONSTRAINT uq_reservations_tenant_key UNIQUE (organization_id, reservation_id),
    CONSTRAINT fk_reservations_request FOREIGN KEY (organization_id, originating_request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reservations_replaces FOREIGN KEY (organization_id, replaces_reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT ck_reservations_status CHECK (status IN ('confirmed','cancelled','closed')),
    CONSTRAINT ck_reservations_range CHECK (NOT isempty(planned_service_range) AND lower_inc(planned_service_range) AND NOT upper_inc(planned_service_range) AND lower(planned_service_range) IS NOT NULL AND upper(planned_service_range) IS NOT NULL),
    CONSTRAINT ck_reservations_revision CHECK (revision > 0),
    CONSTRAINT ck_reservations_terminal_timestamps CHECK (
        (status = 'confirmed' AND cancelled_at IS NULL AND closed_at IS NULL)
        OR (status = 'cancelled' AND cancelled_at IS NOT NULL AND closed_at IS NULL)
        OR (status = 'closed' AND closed_at IS NOT NULL AND cancelled_at IS NULL)
    )
);

CREATE TABLE reservation_items (
    reservation_item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    reservation_id bigint NOT NULL,
    offering_selection_id bigint NOT NULL,
    planned_service_range tstzrange NOT NULL,
    state text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_reservation_items_public_id UNIQUE (public_id),
    CONSTRAINT uq_reservation_items_tenant_key UNIQUE (organization_id, reservation_item_id),
    CONSTRAINT uq_reservation_items_reservation_key UNIQUE (organization_id, reservation_id, reservation_item_id),
    CONSTRAINT fk_reservation_items_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reservation_items_selection FOREIGN KEY (organization_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_reservation_items_range CHECK (NOT isempty(planned_service_range) AND lower_inc(planned_service_range) AND NOT upper_inc(planned_service_range) AND lower(planned_service_range) IS NOT NULL AND upper(planned_service_range) IS NOT NULL),
    CONSTRAINT ck_reservation_items_state CHECK (state IN ('active','cancelled','replaced'))
);

CREATE TABLE commitment_requirements (
    commitment_requirement_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    reservation_id bigint NOT NULL,
    requirement_key text NOT NULL,
    template_id bigint,
    mandatory boolean NOT NULL DEFAULT true,
    required_quantity numeric(20,6) NOT NULL DEFAULT 1,
    capacity_model text NOT NULL,
    state text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_commitment_requirements_public_id UNIQUE (public_id),
    CONSTRAINT uq_commitment_requirements_tenant_key UNIQUE (organization_id, commitment_requirement_id),
    CONSTRAINT uq_commitment_requirements_key UNIQUE (organization_id, reservation_id, requirement_key),
    CONSTRAINT fk_commitment_requirements_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_commitment_requirements_template FOREIGN KEY (organization_id, template_id)
        REFERENCES resource_requirement_templates (organization_id, resource_requirement_template_id) ON DELETE RESTRICT,
    CONSTRAINT ck_commitment_requirements_quantity CHECK (required_quantity > 0),
    CONSTRAINT ck_commitment_requirements_model CHECK (capacity_model IN ('exclusive','units')),
    CONSTRAINT ck_commitment_requirements_state CHECK (state IN ('active','released','replaced'))
);

CREATE TABLE commitment_requirement_items (
    organization_id bigint NOT NULL,
    commitment_requirement_id bigint NOT NULL,
    reservation_item_id bigint NOT NULL,
    PRIMARY KEY (organization_id, commitment_requirement_id, reservation_item_id),
    CONSTRAINT fk_commitment_requirement_items_requirement FOREIGN KEY (organization_id, commitment_requirement_id)
        REFERENCES commitment_requirements (organization_id, commitment_requirement_id) ON DELETE RESTRICT,
    CONSTRAINT fk_commitment_requirement_items_item FOREIGN KEY (organization_id, reservation_item_id)
        REFERENCES reservation_items (organization_id, reservation_item_id) ON DELETE RESTRICT
);

CREATE TABLE resource_allocations (
    resource_allocation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    reservation_id bigint NOT NULL,
    commitment_requirement_id bigint NOT NULL,
    capacity_authority_id bigint NOT NULL,
    concrete_resource_id bigint,
    source_capacity_hold_id bigint,
    quantity numeric(20,6) NOT NULL DEFAULT 1,
    conflict_range tstzrange NOT NULL,
    state text NOT NULL DEFAULT 'active',
    replaced_by_resource_allocation_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    released_at timestamptz,
    CONSTRAINT uq_resource_allocations_public_id UNIQUE (public_id),
    CONSTRAINT uq_resource_allocations_tenant_key UNIQUE (organization_id, resource_allocation_id),
    CONSTRAINT fk_resource_allocations_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_allocations_requirement FOREIGN KEY (organization_id, commitment_requirement_id)
        REFERENCES commitment_requirements (organization_id, commitment_requirement_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_allocations_authority FOREIGN KEY (organization_id, capacity_authority_id)
        REFERENCES capacity_authorities (organization_id, capacity_authority_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_allocations_resource FOREIGN KEY (organization_id, concrete_resource_id)
        REFERENCES resources (organization_id, resource_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_allocations_source_hold FOREIGN KEY (organization_id, source_capacity_hold_id)
        REFERENCES capacity_holds (organization_id, capacity_hold_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resource_allocations_replacement FOREIGN KEY (organization_id, replaced_by_resource_allocation_id)
        REFERENCES resource_allocations (organization_id, resource_allocation_id) ON DELETE RESTRICT,
    CONSTRAINT ck_resource_allocations_quantity CHECK (quantity > 0),
    CONSTRAINT ck_resource_allocations_range CHECK (NOT isempty(conflict_range) AND lower_inc(conflict_range) AND NOT upper_inc(conflict_range) AND lower(conflict_range) IS NOT NULL AND upper(conflict_range) IS NOT NULL),
    CONSTRAINT ck_resource_allocations_state CHECK (state IN ('active','released','replaced')),
    CONSTRAINT ck_resource_allocations_release CHECK ((state = 'active' AND released_at IS NULL) OR (state <> 'active' AND released_at IS NOT NULL))
);

ALTER TABLE capacity_claims
    ADD CONSTRAINT fk_capacity_claims_allocation
    FOREIGN KEY (organization_id, resource_allocation_id)
    REFERENCES resource_allocations (organization_id, resource_allocation_id)
    ON DELETE RESTRICT;

CREATE TABLE request_target_reservations (
    organization_id bigint NOT NULL,
    request_id bigint NOT NULL,
    reservation_id bigint NOT NULL,
    target_role text NOT NULL DEFAULT 'primary',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, request_id, reservation_id, target_role),
    CONSTRAINT fk_request_target_reservations_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_request_target_reservations_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT
);

-- ==========================================================================
-- External commitments
-- ==========================================================================

CREATE TABLE provider_connections (
    provider_connection_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    provider_kind text NOT NULL,
    provider_account_ref text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_provider_connections_public_id UNIQUE (public_id),
    CONSTRAINT uq_provider_connections_tenant_key UNIQUE (organization_id, provider_connection_id),
    CONSTRAINT uq_provider_connections_account UNIQUE (organization_id, provider_kind, provider_account_ref),
    CONSTRAINT fk_provider_connections_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_provider_connections_status CHECK (status IN ('active','disabled','retired'))
);

CREATE TABLE external_commitments (
    external_commitment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    provider_connection_id bigint NOT NULL,
    external_commitment_ref text NOT NULL,
    offering_selection_id bigint,
    status text NOT NULL,
    scope_snapshot jsonb NOT NULL,
    verified_at timestamptz NOT NULL,
    valid_until timestamptz,
    source_policy_key text NOT NULL,
    source_policy_version text NOT NULL,
    release_capability text NOT NULL DEFAULT 'unknown',
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_external_commitments_public_id UNIQUE (public_id),
    CONSTRAINT uq_external_commitments_tenant_key UNIQUE (organization_id, external_commitment_id),
    CONSTRAINT uq_external_commitments_provider_ref UNIQUE (organization_id, provider_connection_id, external_commitment_ref),
    CONSTRAINT fk_external_commitments_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_external_commitments_selection FOREIGN KEY (organization_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_external_commitments_status CHECK (status IN ('pending','committed','released','expired','failed','unknown')),
    CONSTRAINT ck_external_commitments_validity CHECK (valid_until IS NULL OR valid_until > verified_at),
    CONSTRAINT ck_external_commitments_release_capability CHECK (release_capability IN ('supported','unsupported','unknown'))
);

CREATE TABLE reservation_external_commitments (
    organization_id bigint NOT NULL,
    reservation_id bigint NOT NULL,
    external_commitment_id bigint NOT NULL,
    mandatory boolean NOT NULL DEFAULT true,
    linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, reservation_id, external_commitment_id),
    CONSTRAINT fk_reservation_external_commitments_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reservation_external_commitments_commitment FOREIGN KEY (organization_id, external_commitment_id)
        REFERENCES external_commitments (organization_id, external_commitment_id) ON DELETE RESTRICT
);

-- ==========================================================================
-- Admission / execution / dispatch
-- ==========================================================================

CREATE TABLE queue_entries (
    queue_entry_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    admission_context text NOT NULL,
    reservation_item_id bigint,
    offering_selection_id bigint,
    status text NOT NULL DEFAULT 'active',
    priority_class integer NOT NULL DEFAULT 0,
    enqueued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz,
    CONSTRAINT uq_queue_entries_public_id UNIQUE (public_id),
    CONSTRAINT uq_queue_entries_tenant_key UNIQUE (organization_id, queue_entry_id),
    CONSTRAINT fk_queue_entries_item FOREIGN KEY (organization_id, reservation_item_id)
        REFERENCES reservation_items (organization_id, reservation_item_id) ON DELETE RESTRICT,
    CONSTRAINT fk_queue_entries_selection FOREIGN KEY (organization_id, offering_selection_id)
        REFERENCES offering_selections (organization_id, offering_selection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_queue_entries_scope_xor CHECK (num_nonnulls(reservation_item_id, offering_selection_id) = 1),
    CONSTRAINT ck_queue_entries_status CHECK (status IN ('active','called','admitted','cancelled','no_show','expired')),
    CONSTRAINT ck_queue_entries_end CHECK ((status IN ('active','called') AND ended_at IS NULL) OR (status NOT IN ('active','called') AND ended_at IS NOT NULL))
);

CREATE UNIQUE INDEX uq_queue_entries_active_reservation_scope
    ON queue_entries (organization_id, admission_context, reservation_item_id)
    WHERE status IN ('active','called') AND reservation_item_id IS NOT NULL;
CREATE UNIQUE INDEX uq_queue_entries_active_walkin_scope
    ON queue_entries (organization_id, admission_context, offering_selection_id)
    WHERE status IN ('active','called') AND offering_selection_id IS NOT NULL;

CREATE TABLE service_sessions (
    service_session_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    status text NOT NULL DEFAULT 'planned',
    planned_range tstzrange,
    actual_started_at timestamptz,
    actual_ended_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_service_sessions_public_id UNIQUE (public_id),
    CONSTRAINT uq_service_sessions_tenant_key UNIQUE (organization_id, service_session_id),
    CONSTRAINT fk_service_sessions_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_service_sessions_status CHECK (status IN ('planned','active','completed','cancelled')),
    CONSTRAINT ck_service_sessions_planned_range CHECK (planned_range IS NULL OR (NOT isempty(planned_range) AND lower_inc(planned_range) AND NOT upper_inc(planned_range) AND lower(planned_range) IS NOT NULL AND upper(planned_range) IS NOT NULL)),
    CONSTRAINT ck_service_sessions_actual CHECK (actual_ended_at IS NULL OR (actual_started_at IS NOT NULL AND actual_ended_at >= actual_started_at)),
    CONSTRAINT ck_service_sessions_revision CHECK (revision > 0)
);

CREATE TABLE reservation_service_sessions (
    organization_id bigint NOT NULL,
    reservation_id bigint NOT NULL,
    service_session_id bigint NOT NULL,
    linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, reservation_id, service_session_id),
    CONSTRAINT fk_reservation_service_sessions_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reservation_service_sessions_session FOREIGN KEY (organization_id, service_session_id)
        REFERENCES service_sessions (organization_id, service_session_id) ON DELETE RESTRICT
);

ALTER TABLE fulfillments
    ADD CONSTRAINT fk_fulfillments_service_session
    FOREIGN KEY (organization_id, service_session_id)
    REFERENCES service_sessions (organization_id, service_session_id)
    ON DELETE RESTRICT;

CREATE TABLE dispatches (
    dispatch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    reservation_id bigint NOT NULL,
    planning_context_id bigint,
    status text NOT NULL DEFAULT 'pending',
    destination_snapshot jsonb NOT NULL,
    feasibility_revision bigint,
    feasibility_snapshot jsonb,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_dispatches_public_id UNIQUE (public_id),
    CONSTRAINT uq_dispatches_tenant_key UNIQUE (organization_id, dispatch_id),
    CONSTRAINT fk_dispatches_reservation FOREIGN KEY (organization_id, reservation_id)
        REFERENCES reservations (organization_id, reservation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_dispatches_planning_context FOREIGN KEY (organization_id, planning_context_id)
        REFERENCES planning_contexts (organization_id, planning_context_id) ON DELETE RESTRICT,
    CONSTRAINT ck_dispatches_status CHECK (status IN ('pending','ready','en_route','arrived','completed','cancelled','blocked')),
    CONSTRAINT ck_dispatches_revision CHECK (revision > 0)
);

CREATE TABLE dispatch_destination_changes (
    dispatch_destination_change_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    dispatch_id bigint NOT NULL,
    before_destination jsonb NOT NULL,
    after_destination jsonb NOT NULL,
    before_feasibility_revision bigint,
    reason text NOT NULL,
    changed_by_principal_id bigint,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_dispatch_destination_changes_tenant_key UNIQUE (organization_id, dispatch_destination_change_id),
    CONSTRAINT fk_dispatch_destination_changes_dispatch FOREIGN KEY (organization_id, dispatch_id)
        REFERENCES dispatches (organization_id, dispatch_id) ON DELETE RESTRICT,
    CONSTRAINT fk_dispatch_destination_changes_principal FOREIGN KEY (organization_id, changed_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT
);

-- ==========================================================================
-- Financial truth
-- ==========================================================================

CREATE TABLE payment_attempts (
    payment_attempt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint NOT NULL,
    provider_connection_id bigint,
    external_attempt_ref text,
    status text NOT NULL,
    currency char(3) NOT NULL,
    requested_amount_minor bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_attempts_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_attempts_tenant_key UNIQUE (organization_id, payment_attempt_id),
    CONSTRAINT fk_payment_attempts_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_attempts_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_attempts_status CHECK (status IN ('created','pending','succeeded','failed','cancelled')),
    CONSTRAINT ck_payment_attempts_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_payment_attempts_amount CHECK (requested_amount_minor >= 0)
);

CREATE TABLE payment_evidence (
    payment_evidence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    request_id bigint,
    evidence_kind text NOT NULL,
    evidence_payload jsonb NOT NULL,
    interpreted_by text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_evidence_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_evidence_tenant_key UNIQUE (organization_id, payment_evidence_id),
    CONSTRAINT fk_payment_evidence_request FOREIGN KEY (organization_id, request_id)
        REFERENCES requests (organization_id, request_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_evidence_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT
);

CREATE TABLE payment_transactions (
    payment_transaction_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    provider_connection_id bigint,
    external_transaction_ref text,
    transaction_kind text NOT NULL,
    currency char(3) NOT NULL,
    nominal_amount_minor bigint NOT NULL,
    current_finality text NOT NULL DEFAULT 'observed_pending',
    current_eligible_amount_minor bigint NOT NULL DEFAULT 0,
    interpretation_policy_key text NOT NULL,
    interpretation_policy_version text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_transactions_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_transactions_tenant_key UNIQUE (organization_id, payment_transaction_id),
    CONSTRAINT uq_payment_transactions_provider_ref UNIQUE (organization_id, provider_connection_id, external_transaction_ref),
    CONSTRAINT fk_payment_transactions_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_transactions_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_transactions_kind CHECK (transaction_kind IN ('payment','manual_payment','bank_transfer','cash','other')),
    CONSTRAINT ck_payment_transactions_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_payment_transactions_amount CHECK (nominal_amount_minor >= 0 AND current_eligible_amount_minor >= 0),
    CONSTRAINT ck_payment_transactions_finality CHECK (current_finality IN ('observed_pending','observed_available','observed_final','under_review','invalidated')),
    CONSTRAINT ck_payment_transactions_revision CHECK (revision > 0)
);

CREATE TABLE financial_observations (
    financial_observation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    provider_connection_id bigint,
    source_event_id text,
    source_status text NOT NULL,
    normalized_finality text NOT NULL,
    currency char(3) NOT NULL,
    observed_value_minor bigint NOT NULL,
    eligible_value_minor bigint NOT NULL DEFAULT 0,
    source_policy_key text NOT NULL,
    source_policy_version text NOT NULL,
    occurred_at timestamptz,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_financial_observations_public_id UNIQUE (public_id),
    CONSTRAINT uq_financial_observations_tenant_key UNIQUE (organization_id, financial_observation_id),
    CONSTRAINT uq_financial_observations_source_event UNIQUE (organization_id, provider_connection_id, source_event_id),
    CONSTRAINT fk_financial_observations_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_financial_observations_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_financial_observations_finality CHECK (normalized_finality IN ('observed_pending','observed_available','observed_final','invalidated')),
    CONSTRAINT ck_financial_observations_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_financial_observations_values CHECK (observed_value_minor >= 0 AND eligible_value_minor >= 0)
);

CREATE TABLE observation_corrections (
    observation_correction_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    target_financial_observation_id bigint NOT NULL,
    correction_kind text NOT NULL,
    eligible_value_delta_minor bigint NOT NULL,
    reason text NOT NULL,
    source_reference text,
    policy_key text NOT NULL,
    policy_version text NOT NULL,
    corrected_by_principal_id bigint,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_observation_corrections_public_id UNIQUE (public_id),
    CONSTRAINT uq_observation_corrections_tenant_key UNIQUE (organization_id, observation_correction_id),
    CONSTRAINT fk_observation_corrections_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_observation_corrections_observation FOREIGN KEY (organization_id, target_financial_observation_id)
        REFERENCES financial_observations (organization_id, financial_observation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_observation_corrections_principal FOREIGN KEY (organization_id, corrected_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_observation_corrections_kind CHECK (correction_kind IN ('invalidate','replace_interpretation','duplicate','misidentified'))
);

CREATE TABLE financial_reversals (
    financial_reversal_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    provider_connection_id bigint,
    external_reversal_ref text,
    reversal_kind text NOT NULL,
    currency char(3) NOT NULL,
    amount_minor bigint NOT NULL,
    source_policy_key text NOT NULL,
    source_policy_version text NOT NULL,
    occurred_at timestamptz,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_financial_reversals_public_id UNIQUE (public_id),
    CONSTRAINT uq_financial_reversals_tenant_key UNIQUE (organization_id, financial_reversal_id),
    CONSTRAINT uq_financial_reversals_provider_ref UNIQUE (organization_id, provider_connection_id, external_reversal_ref),
    CONSTRAINT fk_financial_reversals_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_financial_reversals_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_financial_reversals_kind CHECK (reversal_kind IN ('chargeback','return','voided_settlement','provider_reversal','other')),
    CONSTRAINT ck_financial_reversals_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_financial_reversals_amount CHECK (amount_minor > 0)
);

CREATE TABLE payment_allocations (
    payment_allocation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    payment_requirement_id bigint NOT NULL,
    currency char(3) NOT NULL,
    allocated_amount_minor bigint NOT NULL,
    created_by_principal_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_allocations_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_allocations_tenant_key UNIQUE (organization_id, payment_allocation_id),
    CONSTRAINT fk_payment_allocations_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_allocations_requirement FOREIGN KEY (organization_id, payment_requirement_id)
        REFERENCES payment_requirements (organization_id, payment_requirement_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_allocations_principal FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_allocations_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_payment_allocations_amount CHECK (allocated_amount_minor > 0)
);

CREATE TABLE payment_allocation_adjustments (
    payment_allocation_adjustment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_allocation_id bigint NOT NULL,
    observation_correction_id bigint,
    financial_reversal_id bigint,
    amount_minor bigint NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_payment_allocation_adjustments_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_allocation_adjustments_tenant_key UNIQUE (organization_id, payment_allocation_adjustment_id),
    CONSTRAINT fk_payment_allocation_adjustments_allocation FOREIGN KEY (organization_id, payment_allocation_id)
        REFERENCES payment_allocations (organization_id, payment_allocation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_allocation_adjustments_correction FOREIGN KEY (organization_id, observation_correction_id)
        REFERENCES observation_corrections (organization_id, observation_correction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_allocation_adjustments_reversal FOREIGN KEY (organization_id, financial_reversal_id)
        REFERENCES financial_reversals (organization_id, financial_reversal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_allocation_adjustments_source_xor CHECK (num_nonnulls(observation_correction_id, financial_reversal_id) = 1),
    CONSTRAINT ck_payment_allocation_adjustments_amount CHECK (amount_minor > 0)
);

CREATE TABLE refunds (
    refund_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    provider_connection_id bigint,
    external_refund_ref text,
    status text NOT NULL DEFAULT 'requested',
    currency char(3) NOT NULL,
    amount_minor bigint NOT NULL,
    reason text NOT NULL,
    requested_by_principal_id bigint,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    CONSTRAINT uq_refunds_public_id UNIQUE (public_id),
    CONSTRAINT uq_refunds_tenant_key UNIQUE (organization_id, refund_id),
    CONSTRAINT fk_refunds_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_refunds_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT fk_refunds_principal FOREIGN KEY (organization_id, requested_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_refunds_status CHECK (status IN ('requested','processing','succeeded','failed','cancelled')),
    CONSTRAINT ck_refunds_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_refunds_amount CHECK (amount_minor > 0)
);

CREATE TABLE payment_disputes (
    payment_dispute_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint NOT NULL,
    provider_connection_id bigint,
    external_dispute_ref text,
    status text NOT NULL,
    amount_minor bigint,
    currency char(3),
    opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_payment_disputes_public_id UNIQUE (public_id),
    CONSTRAINT uq_payment_disputes_tenant_key UNIQUE (organization_id, payment_dispute_id),
    CONSTRAINT fk_payment_disputes_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_payment_disputes_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_payment_disputes_status CHECK (status IN ('open','under_review','won','lost','closed')),
    CONSTRAINT ck_payment_disputes_amount CHECK (amount_minor IS NULL OR amount_minor > 0),
    CONSTRAINT ck_payment_disputes_currency CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$')
);

CREATE TABLE reconciliation_cases (
    reconciliation_case_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    payment_transaction_id bigint,
    status text NOT NULL DEFAULT 'open',
    reason_code text NOT NULL,
    details jsonb NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    resolved_by_principal_id bigint,
    resolution jsonb,
    CONSTRAINT uq_reconciliation_cases_public_id UNIQUE (public_id),
    CONSTRAINT uq_reconciliation_cases_tenant_key UNIQUE (organization_id, reconciliation_case_id),
    CONSTRAINT fk_reconciliation_cases_transaction FOREIGN KEY (organization_id, payment_transaction_id)
        REFERENCES payment_transactions (organization_id, payment_transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reconciliation_cases_principal FOREIGN KEY (organization_id, resolved_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_reconciliation_cases_status CHECK (status IN ('open','under_review','resolved','cancelled')),
    CONSTRAINT ck_reconciliation_cases_revision CHECK (revision > 0),
    CONSTRAINT ck_reconciliation_cases_resolution CHECK (
        (status = 'resolved' AND resolved_at IS NOT NULL AND resolved_by_principal_id IS NOT NULL AND resolution IS NOT NULL)
        OR status <> 'resolved'
    )
);

-- ==========================================================================
-- Callback ingress / idempotency / audit / events / outbox
-- ==========================================================================

CREATE TABLE provider_events (
    provider_event_row_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    provider_connection_id bigint NOT NULL,
    provider_event_id text NOT NULL,
    canonical_payload_hash bytea NOT NULL,
    payload jsonb NOT NULL,
    authentication_result jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    processed_at timestamptz,
    CONSTRAINT uq_provider_events_tenant_key UNIQUE (organization_id, provider_event_row_id),
    CONSTRAINT uq_provider_events_identity UNIQUE (organization_id, provider_connection_id, provider_event_id),
    CONSTRAINT fk_provider_events_provider FOREIGN KEY (organization_id, provider_connection_id)
        REFERENCES provider_connections (organization_id, provider_connection_id) ON DELETE RESTRICT,
    CONSTRAINT ck_provider_events_hash CHECK (octet_length(canonical_payload_hash) >= 32)
);

CREATE TABLE idempotency_records (
    idempotency_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    scope text NOT NULL,
    idempotency_key text NOT NULL,
    canonical_request_hash bytea NOT NULL,
    state text NOT NULL DEFAULT 'in_progress',
    logical_result jsonb,
    created_by_principal_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    CONSTRAINT uq_idempotency_records_tenant_key UNIQUE (organization_id, idempotency_record_id),
    CONSTRAINT uq_idempotency_records_key UNIQUE (organization_id, scope, idempotency_key),
    CONSTRAINT fk_idempotency_records_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_idempotency_records_principal FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT ck_idempotency_records_hash CHECK (octet_length(canonical_request_hash) >= 32),
    CONSTRAINT ck_idempotency_records_state CHECK (state IN ('in_progress','completed','failed_terminal')),
    CONSTRAINT ck_idempotency_records_result CHECK ((state = 'completed' AND logical_result IS NOT NULL AND completed_at IS NOT NULL) OR state <> 'completed')
);

CREATE TABLE audit_records (
    audit_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    operation_id uuid NOT NULL,
    action text NOT NULL,
    principal_id bigint,
    represented_party_id bigint,
    representation_id bigint,
    representation_snapshot jsonb,
    policy_key text,
    policy_version text,
    reason text,
    entity_kind text,
    entity_public_id uuid,
    before_revision bigint,
    after_revision bigint,
    evaluated_inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_audit_records_public_id UNIQUE (public_id),
    CONSTRAINT uq_audit_records_tenant_key UNIQUE (organization_id, audit_record_id),
    CONSTRAINT fk_audit_records_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_records_principal FOREIGN KEY (organization_id, principal_id)
        REFERENCES principals (organization_id, principal_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_records_party FOREIGN KEY (organization_id, represented_party_id)
        REFERENCES parties (organization_id, party_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_records_representation FOREIGN KEY (organization_id, representation_id)
        REFERENCES representations (organization_id, representation_id) ON DELETE RESTRICT
);

CREATE TABLE domain_events (
    domain_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    operation_id uuid NOT NULL,
    event_type text NOT NULL,
    aggregate_kind text NOT NULL,
    aggregate_public_id uuid NOT NULL,
    aggregate_revision bigint,
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_domain_events_public_id UNIQUE (public_id),
    CONSTRAINT uq_domain_events_tenant_key UNIQUE (organization_id, domain_event_id),
    CONSTRAINT fk_domain_events_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT
);

CREATE TABLE outbox_messages (
    outbox_message_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id bigint NOT NULL,
    public_id uuid NOT NULL DEFAULT uuidv7(),
    domain_event_id bigint,
    message_type text NOT NULL,
    destination text NOT NULL,
    idempotency_key text NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    claimed_at timestamptz,
    claimed_by text,
    attempt_count integer NOT NULL DEFAULT 0,
    delivered_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_outbox_messages_public_id UNIQUE (public_id),
    CONSTRAINT uq_outbox_messages_tenant_key UNIQUE (organization_id, outbox_message_id),
    CONSTRAINT uq_outbox_messages_idempotency UNIQUE (organization_id, destination, idempotency_key),
    CONSTRAINT fk_outbox_messages_event FOREIGN KEY (organization_id, domain_event_id)
        REFERENCES domain_events (organization_id, domain_event_id) ON DELETE RESTRICT,
    CONSTRAINT fk_outbox_messages_org FOREIGN KEY (organization_id)
        REFERENCES organizations (organization_id) ON DELETE RESTRICT,
    CONSTRAINT ck_outbox_messages_attempts CHECK (attempt_count >= 0)
);

CREATE INDEX ix_outbox_messages_ready
    ON outbox_messages (available_at, outbox_message_id)
    WHERE delivered_at IS NULL;

-- ==========================================================================
-- Mutation guards and concurrency backstops
-- ==========================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_request_terminality()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('completed','cancelled','failed_terminal') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'terminal Request status is monotonic' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_requests_guard_terminality
BEFORE UPDATE OF status ON requests FOR EACH ROW EXECUTE FUNCTION request_engine.guard_request_terminality();

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_hold_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state <> 'active' AND NEW.state IS DISTINCT FROM OLD.state THEN
        RAISE EXCEPTION 'terminal CapacityHold state cannot transition' USING ERRCODE = '55000';
    END IF;
    IF NEW.state = 'confirmed' AND OLD.expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'expired CapacityHold cannot confirm' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_capacity_holds_guard_transition
BEFORE UPDATE OF state ON capacity_holds FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_hold_transition();

CREATE OR REPLACE FUNCTION request_engine.guard_reservation_terminal_claims()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IN ('cancelled','closed') AND OLD.status = 'confirmed' THEN
        IF EXISTS (
            SELECT 1
              FROM request_engine.resource_allocations ra
              JOIN request_engine.capacity_claims cc
                ON cc.organization_id = ra.organization_id
               AND cc.resource_allocation_id = ra.resource_allocation_id
               AND cc.claim_kind = 'allocation'
             WHERE ra.organization_id = NEW.organization_id
               AND ra.reservation_id = NEW.reservation_id
               AND ra.state = 'active'
               AND cc.state = 'active'
        ) THEN
            RAISE EXCEPTION 'terminal Reservation cannot retain active capacity claims' USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_reservations_guard_terminal_claims
BEFORE UPDATE OF status ON reservations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_terminal_claims();

CREATE OR REPLACE FUNCTION request_engine.guard_payment_requirement_repricing()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.required_amount_minor IS DISTINCT FROM OLD.required_amount_minor OR NEW.currency IS DISTINCT FROM OLD.currency)
       AND EXISTS (
            SELECT 1 FROM request_engine.payment_allocations pa
             WHERE pa.organization_id = OLD.organization_id
               AND pa.payment_requirement_id = OLD.payment_requirement_id
       ) THEN
        RAISE EXCEPTION 'financially-used PaymentRequirement cannot be destructively repriced; create a replacement requirement'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_payment_requirements_guard_repricing
BEFORE UPDATE OF required_amount_minor, currency ON payment_requirements
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_payment_requirement_repricing();

CREATE OR REPLACE FUNCTION request_engine.enforce_payment_allocation_budget()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_tx_currency char(3);
    v_req_currency char(3);
    v_req_disposition text;
    v_eligible bigint;
    v_required bigint;
    v_tx_net bigint;
    v_req_net bigint;
BEGIN
    SELECT currency, current_eligible_amount_minor
      INTO v_tx_currency, v_eligible
      FROM request_engine.payment_transactions
     WHERE organization_id = NEW.organization_id
       AND payment_transaction_id = NEW.payment_transaction_id
     FOR UPDATE;

    SELECT currency, disposition, required_amount_minor
      INTO v_req_currency, v_req_disposition, v_required
      FROM request_engine.payment_requirements
     WHERE organization_id = NEW.organization_id
       AND payment_requirement_id = NEW.payment_requirement_id
     FOR UPDATE;

    IF v_tx_currency IS NULL OR v_req_currency IS NULL THEN
        RAISE EXCEPTION 'payment transaction or requirement not found' USING ERRCODE = '23503';
    END IF;
    IF NEW.currency <> v_tx_currency OR NEW.currency <> v_req_currency THEN
        RAISE EXCEPTION 'implicit FX is forbidden for PaymentAllocation' USING ERRCODE = '23514';
    END IF;
    IF v_req_disposition <> 'active' THEN
        RAISE EXCEPTION 'cannot allocate to non-active PaymentRequirement' USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(sum(pa.allocated_amount_minor),0)
           - COALESCE((SELECT sum(adj.amount_minor)
                         FROM request_engine.payment_allocation_adjustments adj
                         JOIN request_engine.payment_allocations pa2
                           ON pa2.organization_id = adj.organization_id
                          AND pa2.payment_allocation_id = adj.payment_allocation_id
                        WHERE pa2.organization_id = NEW.organization_id
                          AND pa2.payment_transaction_id = NEW.payment_transaction_id),0)
      INTO v_tx_net
      FROM request_engine.payment_allocations pa
     WHERE pa.organization_id = NEW.organization_id
       AND pa.payment_transaction_id = NEW.payment_transaction_id;

    SELECT COALESCE(sum(pa.allocated_amount_minor),0)
           - COALESCE((SELECT sum(adj.amount_minor)
                         FROM request_engine.payment_allocation_adjustments adj
                         JOIN request_engine.payment_allocations pa2
                           ON pa2.organization_id = adj.organization_id
                          AND pa2.payment_allocation_id = adj.payment_allocation_id
                        WHERE pa2.organization_id = NEW.organization_id
                          AND pa2.payment_requirement_id = NEW.payment_requirement_id),0)
      INTO v_req_net
      FROM request_engine.payment_allocations pa
     WHERE pa.organization_id = NEW.organization_id
       AND pa.payment_requirement_id = NEW.payment_requirement_id;

    IF v_tx_net + NEW.allocated_amount_minor > v_eligible THEN
        RAISE EXCEPTION 'PaymentAllocation exceeds current eligible transaction value' USING ERRCODE = '23514';
    END IF;
    IF v_req_net + NEW.allocated_amount_minor > v_required THEN
        RAISE EXCEPTION 'PaymentAllocation exceeds PaymentRequirement amount' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_payment_allocations_budget
BEFORE INSERT ON payment_allocations FOR EACH ROW EXECUTE FUNCTION request_engine.enforce_payment_allocation_budget();

CREATE OR REPLACE FUNCTION request_engine.enforce_allocation_adjustment_budget()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_allocated bigint;
    v_adjusted bigint;
    v_source_amount bigint;
    v_source_adjusted bigint;
BEGIN
    SELECT allocated_amount_minor INTO v_allocated
      FROM request_engine.payment_allocations
     WHERE organization_id = NEW.organization_id
       AND payment_allocation_id = NEW.payment_allocation_id
     FOR UPDATE;

    SELECT COALESCE(sum(amount_minor),0) INTO v_adjusted
      FROM request_engine.payment_allocation_adjustments
     WHERE organization_id = NEW.organization_id
       AND payment_allocation_id = NEW.payment_allocation_id;

    IF v_adjusted + NEW.amount_minor > v_allocated THEN
        RAISE EXCEPTION 'allocation adjustments exceed historical allocation contribution' USING ERRCODE = '23514';
    END IF;

    IF NEW.financial_reversal_id IS NOT NULL THEN
        SELECT amount_minor INTO v_source_amount
          FROM request_engine.financial_reversals
         WHERE organization_id = NEW.organization_id
           AND financial_reversal_id = NEW.financial_reversal_id
         FOR UPDATE;

        SELECT COALESCE(sum(amount_minor),0) INTO v_source_adjusted
          FROM request_engine.payment_allocation_adjustments
         WHERE organization_id = NEW.organization_id
           AND financial_reversal_id = NEW.financial_reversal_id;

        IF v_source_adjusted + NEW.amount_minor > v_source_amount THEN
            RAISE EXCEPTION 'reversal-sourced adjustments exceed reversal amount' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_payment_allocation_adjustments_budget
BEFORE INSERT ON payment_allocation_adjustments
FOR EACH ROW EXECUTE FUNCTION request_engine.enforce_allocation_adjustment_budget();

-- ==========================================================================
-- Append-only history protection
-- ==========================================================================

CREATE TRIGGER trg_fulfillments_append_only BEFORE UPDATE OR DELETE ON fulfillments FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_fulfillment_corrections_append_only BEFORE UPDATE OR DELETE ON fulfillment_corrections FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_price_determinations_append_only BEFORE UPDATE OR DELETE ON price_determinations FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_financial_observations_append_only BEFORE UPDATE OR DELETE ON financial_observations FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_observation_corrections_append_only BEFORE UPDATE OR DELETE ON observation_corrections FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_financial_reversals_append_only BEFORE UPDATE OR DELETE ON financial_reversals FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_payment_allocations_append_only BEFORE UPDATE OR DELETE ON payment_allocations FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_payment_allocation_adjustments_append_only BEFORE UPDATE OR DELETE ON payment_allocation_adjustments FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_dispatch_destination_changes_append_only BEFORE UPDATE OR DELETE ON dispatch_destination_changes FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_audit_records_append_only BEFORE UPDATE OR DELETE ON audit_records FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();
CREATE TRIGGER trg_domain_events_append_only BEFORE UPDATE OR DELETE ON domain_events FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_fact_mutation();

-- ==========================================================================
-- Transactional indexes
-- ==========================================================================

CREATE INDEX ix_requests_org_status_created ON requests (organization_id, status, created_at DESC);
CREATE INDEX ix_offering_selections_request ON offering_selections (organization_id, request_id, offering_selection_id);
CREATE INDEX ix_outcome_scopes_request ON outcome_scopes (organization_id, request_id, outcome_scope_id);
CREATE INDEX ix_fulfillments_scope ON fulfillments (organization_id, outcome_scope_id, created_at);
CREATE INDEX ix_fulfillment_corrections_fulfillment ON fulfillment_corrections (organization_id, fulfillment_id, occurred_at);
CREATE INDEX ix_capacity_holds_request ON capacity_holds (organization_id, request_id, state, expires_at);
CREATE INDEX ix_reservation_items_selection ON reservation_items (organization_id, offering_selection_id, reservation_id);
CREATE INDEX ix_commitment_requirements_reservation ON commitment_requirements (organization_id, reservation_id, state);
CREATE INDEX ix_resource_allocations_reservation ON resource_allocations (organization_id, reservation_id, state);
CREATE INDEX ix_resource_allocations_requirement ON resource_allocations (organization_id, commitment_requirement_id, state);
CREATE INDEX ix_external_commitments_status ON external_commitments (organization_id, status, valid_until);
CREATE INDEX ix_service_sessions_status ON service_sessions (organization_id, status, created_at);
CREATE INDEX ix_payment_requirements_request ON payment_requirements (organization_id, request_id, disposition);
CREATE INDEX ix_financial_observations_transaction ON financial_observations (organization_id, payment_transaction_id, observed_at, financial_observation_id);
CREATE INDEX ix_observation_corrections_transaction ON observation_corrections (organization_id, payment_transaction_id, occurred_at);
CREATE INDEX ix_financial_reversals_transaction ON financial_reversals (organization_id, payment_transaction_id, observed_at);
CREATE INDEX ix_payment_allocations_transaction ON payment_allocations (organization_id, payment_transaction_id, created_at);
CREATE INDEX ix_payment_allocations_requirement ON payment_allocations (organization_id, payment_requirement_id, created_at);
CREATE INDEX ix_reconciliation_cases_open ON reconciliation_cases (organization_id, status, opened_at) WHERE status IN ('open','under_review');

-- ==========================================================================
-- updated_at triggers on mutable roots
-- ==========================================================================

CREATE TRIGGER trg_organizations_touch BEFORE UPDATE ON organizations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_principals_touch BEFORE UPDATE ON principals FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_parties_touch BEFORE UPDATE ON parties FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_offerings_touch BEFORE UPDATE ON offerings FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_requests_touch BEFORE UPDATE ON requests FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_offering_selections_touch BEFORE UPDATE ON offering_selections FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_resources_touch BEFORE UPDATE ON resources FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_capacity_pools_touch BEFORE UPDATE ON capacity_pools FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_capacity_authorities_touch BEFORE UPDATE ON capacity_authorities FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_planning_contexts_touch BEFORE UPDATE ON planning_contexts FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_reservations_touch BEFORE UPDATE ON reservations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_service_sessions_touch BEFORE UPDATE ON service_sessions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_dispatches_touch BEFORE UPDATE ON dispatches FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_payment_attempts_touch BEFORE UPDATE ON payment_attempts FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER trg_payment_transactions_touch BEFORE UPDATE ON payment_transactions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

-- ==========================================================================
-- Enforcement classification / DBA contract
-- ==========================================================================
--
-- Hard DB enforcement represented here:
-- * tenant equality: composite organization_id FKs on authoritative relations;
-- * typed relationships instead of authoritative entity_type/entity_id pairs;
-- * terminal Request monotonicity;
-- * explicit quantity/unit and bounded [start,end) interval checks;
-- * stable OutcomeScope + reject_excess serialization backstop;
-- * one common CapacityClaim space for Hold + Allocation claims;
-- * wall-clock Hold expiry checked with clock_timestamp(), not transaction now();
-- * active QueueEntry uniqueness per AdmissionScope/context;
-- * terminal Reservation cannot retain active allocation claims;
-- * immutable financially-used PaymentRequirement amount;
-- * PaymentTransaction / Observation / Correction / Reversal type separation;
-- * transaction eligible-value, requirement-value and adjustment budgets;
-- * provider event uniqueness; idempotency key+hash persistence;
-- * append-only outcome/financial/audit history;
-- * domain mutation + outbox can commit in the same PostgreSQL transaction.
--
-- Stable-row transaction protocols still required by docs/02:
-- * Representation revocation vs authority-dependent mutation.
-- * CompleteRequest vs outcome mutation/correction.
-- * CorrectFulfillment re-evaluation of completion_validity.
-- * complete compound Hold all-or-none acquisition across authorities.
-- * unit capacity across variable schedule change-points.
-- * schedule/location/pool membership mutation vs capacity claims.
-- * pool contributor/direct-resource conflict proof.
-- * ConfirmReservation complete mandatory coverage.
-- * atomic replacement reschedule and shared-requirement partial cancellation.
-- * PlanningRevision binding for external field-service feasibility.
-- * execution/admission/cancellation races.
-- * financial observation/correction/reversal reduction and reconciliation.
-- * refund/refund and refund/reversal budget coordination.
-- * provider same-ID/different-hash conflict handling.
-- * current read authorization on idempotent replay.
-- * at-least-once outbox and external compensation consumers.
--
-- Canonical multi-root lock class order remains the order in docs/02:
-- REPRESENTATION -> REQUEST -> OUTCOME_SCOPE -> RESERVATION ->
-- ADMISSION_SCOPE_ROOT -> CAPACITY_HOLD -> CAPACITY_AUTHORITY ->
-- SERVICE_SESSION -> PAYMENT_TRANSACTION -> PAYMENT_REQUIREMENT ->
-- FINANCIAL_REVERSAL_OR_CORRECTION -> RECONCILIATION_CASE.
-- Within a class, lock ascending internal bigint IDs.
--
-- RLS is intentionally not enabled in this reference DDL. Composite FKs are
-- structural tenant integrity. Deployment RLS depends on the eventual role /
-- connection model (tenant-scoped API sessions vs cross-tenant workers). Add it
-- as defense-in-depth once roles are fixed; do not make session RLS state the
-- sole authorization proof.

COMMIT;
