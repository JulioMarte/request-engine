"""Self-service business owner accounts (ADR 0021).

A platform Principal holding ``organization.provision`` invites a future business
owner (shared one-time code or email). The invitee enrolls their OWN native
identity with the code, which grants an account entitlement
``account.organization.create`` (bounded organization count). The entitled human
then creates businesses they control through ``POST /v1/me/organizations``.

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Tenancy (account invitation, account entitlement, organization
  root). Operations: ``platform_account_invitation_create|list|get|revoke``
  (control plane), ``account_invitation_enroll``, ``self_account_get`` and
  ``self_organization_create`` (runtime plane).
* Guarantees: INV-SELF-SERVICE-ACCOUNT-001 (new), INV-AUTHORITY-001,
  INV-IDEMPOTENCY-001, INV-ATOMICITY-001, INV-PROVENANCE-001, INV-PRIVILEGE-001,
  INV-TENANT-001. Platform authority never becomes tenant authority: the root fact
  keeps a platform provenance principal (the invitation issuer, unchanged
  ``guard_authority_reference_tenant`` rule) while the creating human becomes the
  root controller with the current initial controller policy.
* Change class: CONTROLLED additive. Four new private tables, seven new functions,
  one narrow session-lock boundary, three reviewed column INSERT grants on
  ``organizations`` (default timezone/locale/currency) and SELECT(revision) on
  ``initial_controller_policies`` for the control definer. No
  existing table, function, policy or row is changed or backfilled.
* Authoritative objects: ``account_invitations`` (digest-only token, state CHECK),
  ``account_invitation_facts`` (append-only), ``account_entitlements``
  (``CHECK organizations_created <= max_organizations``, one per native identity,
  platform-plane grantor trigger), ``account_organization_creations`` (append-only,
  ``UNIQUE (entitlement_id, sequence)`` and ``UNIQUE (entitlement_id, key digest)``).
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT of ``request_auth.create_self_service_organization``:
  topology share gate -> session/identity FOR SHARE (``request_auth.lock_active_native_session``)
  -> entitlement row FOR UPDATE (serialization root of the limit) -> idempotency
  replay/conflict -> limit/status/policy validation -> credentialed identity FOR SHARE
  -> organization root writes (same rows/triggers as platform root provisioning)
  -> counter and creation fact. All native locks are SHARE, so two creations by the
  same identity serialize only on the entitlement row (no lock upgrade, no deadlock).
* Enrollment: invitation row FOR UPDATE by token digest; a concurrent second use
  observes ``accepted`` and fails like an unknown token.
* Tenant/RLS/roles: the four tables ENABLE + FORCE RLS with no policy; no runtime role
  has table privileges. Functions are SECURITY DEFINER with pinned search_path, owned
  by ``request_platform_control_definer`` (column-level grants only). Runtime
  ``request_engine_app`` may execute exactly ``request_auth.enroll_account_invitation``,
  ``request_auth.read_account_entitlement`` and
  ``request_auth.create_self_service_organization``; ``request_platform_control``
  executes the three control commands; the platform read function is granted to the
  deployment's platform-read LOGIN like every other platform read.
* Failure/concurrency: limit race -> exactly ``max_organizations`` winners, losers get
  ``RE429``; changed idempotent intent -> ``RE409``; occupied organization key -> 23505.
* Roll-forward only; downgrade refused (accepted ownership facts are history).
* Falsification: tests/db/test_self_service_business_accounts.py (privileges, RLS,
  limit race with independent connections, idempotency, revoked/expired/used codes,
  stale session), tests/e2e/test_self_service_business_http.py (invite -> enroll ->
  create -> tenant authority), tests/unit/test_self_service_business_http.py.
"""

from alembic import op

revision: str = "0006_self_service_accounts"
down_revision: str | None = "0005_staff_representations"
branch_labels: str | None = None
depends_on: str | None = None

_D = "request_platform_control_definer"

_TABLES = r"""
CREATE TABLE request_engine.account_invitations (
    id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    delivery_channel text NOT NULL,
    destination_email text,
    max_organizations integer NOT NULL,
    status text DEFAULT 'pending' NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    delivery_status text,
    invited_by_principal_id uuid NOT NULL,
    native_identity_id uuid,
    provenance_reference text NOT NULL,
    idempotency_key_digest text NOT NULL,
    intent_digest text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoke_reason_code text,
    CONSTRAINT account_invitations_pkey PRIMARY KEY (id),
    CONSTRAINT account_invitations_token_digest_key UNIQUE (token_digest),
    CONSTRAINT account_invitations_actor_key_uq
        UNIQUE (invited_by_principal_id, idempotency_key_digest),
    CONSTRAINT account_invitations_token_digest_check CHECK (octet_length(token_digest) = 32),
    CONSTRAINT account_invitations_token_fingerprint_check
        CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
    CONSTRAINT account_invitations_channel_check
        CHECK (delivery_channel IN ('email', 'shared_code')),
    CONSTRAINT account_invitations_max_check CHECK (max_organizations BETWEEN 1 AND 10),
    CONSTRAINT account_invitations_status_check
        CHECK (status IN ('pending', 'accepted', 'revoked')),
    CONSTRAINT account_invitations_revision_check CHECK (revision > 0),
    CONSTRAINT account_invitations_delivery_status_check
        CHECK (delivery_status IS NULL
               OR delivery_status IN ('pending', 'sent', 'failed', 'unknown')),
    CONSTRAINT account_invitations_destination_check CHECK (
        (delivery_channel = 'email' AND destination_email IS NOT NULL
             AND delivery_status IS NOT NULL)
        OR (delivery_channel = 'shared_code' AND destination_email IS NULL
             AND delivery_status IS NULL)),
    CONSTRAINT account_invitations_email_check CHECK (
        destination_email IS NULL OR (
            destination_email = lower(btrim(destination_email))
            AND length(destination_email) BETWEEN 3 AND 254
            AND destination_email ~ '^[^@[:space:]]+@[^@[:space:]]+$')),
    CONSTRAINT account_invitations_provenance_check
        CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
    CONSTRAINT account_invitations_key_digest_check
        CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_invitations_intent_digest_check CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_invitations_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT account_invitations_state_check CHECK (
        (status = 'pending' AND native_identity_id IS NULL AND accepted_at IS NULL
             AND revoked_at IS NULL AND revoke_reason_code IS NULL)
        OR (status = 'accepted' AND native_identity_id IS NOT NULL
             AND accepted_at IS NOT NULL AND revoked_at IS NULL
             AND revoke_reason_code IS NULL)
        OR (status = 'revoked' AND native_identity_id IS NULL AND accepted_at IS NULL
             AND revoked_at IS NOT NULL AND revoke_reason_code IS NOT NULL)),
    CONSTRAINT account_invitations_invited_by_fkey FOREIGN KEY (invited_by_principal_id)
        REFERENCES request_engine.principals (id),
    CONSTRAINT account_invitations_native_identity_fkey FOREIGN KEY (native_identity_id)
        REFERENCES request_engine.native_identities (id)
);

CREATE TABLE request_engine.account_invitation_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    invitation_id uuid NOT NULL,
    action text NOT NULL,
    actor_principal_id uuid,
    native_identity_id uuid,
    revision_before bigint NOT NULL,
    revision_after bigint NOT NULL,
    reason_code text,
    delivery_status text,
    idempotency_key_digest text,
    intent_digest text,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT account_invitation_facts_pkey PRIMARY KEY (id),
    CONSTRAINT account_invitation_facts_idempotency_uq
        UNIQUE (actor_principal_id, action, idempotency_key_digest),
    CONSTRAINT account_invitation_facts_action_check
        CHECK (action IN ('create', 'accept', 'revoke', 'delivery')),
    CONSTRAINT account_invitation_facts_revision_check
        CHECK (revision_before >= 0 AND revision_after >= revision_before),
    CONSTRAINT account_invitation_facts_delivery_check
        CHECK ((action = 'delivery') = (delivery_status IS NOT NULL)),
    CONSTRAINT account_invitation_facts_key_digest_check
        CHECK (idempotency_key_digest IS NULL OR idempotency_key_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_invitation_facts_intent_digest_check
        CHECK (intent_digest IS NULL OR intent_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_invitation_facts_invitation_fkey FOREIGN KEY (invitation_id)
        REFERENCES request_engine.account_invitations (id),
    CONSTRAINT account_invitation_facts_actor_fkey FOREIGN KEY (actor_principal_id)
        REFERENCES request_engine.principals (id)
);

CREATE TABLE request_engine.account_entitlements (
    id uuid NOT NULL,
    identity_authority_id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    entitlement_key text NOT NULL,
    max_organizations integer NOT NULL,
    organizations_created integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'active' NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    granted_by_principal_id uuid NOT NULL,
    source_invitation_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT account_entitlements_pkey PRIMARY KEY (id),
    CONSTRAINT account_entitlements_native_identity_key UNIQUE (native_identity_id),
    CONSTRAINT account_entitlements_source_invitation_key UNIQUE (source_invitation_id),
    CONSTRAINT account_entitlements_key_check
        CHECK (entitlement_key = 'account.organization.create'),
    CONSTRAINT account_entitlements_max_check CHECK (max_organizations BETWEEN 1 AND 10),
    CONSTRAINT account_entitlements_limit_check
        CHECK (organizations_created >= 0 AND organizations_created <= max_organizations),
    CONSTRAINT account_entitlements_status_check CHECK (status IN ('active', 'revoked')),
    CONSTRAINT account_entitlements_revision_check CHECK (revision > 0),
    CONSTRAINT account_entitlements_authority_fkey FOREIGN KEY (identity_authority_id)
        REFERENCES request_engine.identity_authorities (id),
    CONSTRAINT account_entitlements_native_identity_fkey FOREIGN KEY (native_identity_id)
        REFERENCES request_engine.native_identities (id),
    CONSTRAINT account_entitlements_granted_by_fkey FOREIGN KEY (granted_by_principal_id)
        REFERENCES request_engine.principals (id),
    CONSTRAINT account_entitlements_source_invitation_fkey FOREIGN KEY (source_invitation_id)
        REFERENCES request_engine.account_invitations (id)
);

CREATE TABLE request_engine.account_organization_creations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    entitlement_id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    controller_principal_id uuid NOT NULL,
    sequence integer NOT NULL,
    idempotency_key_digest text NOT NULL,
    intent_digest text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT account_organization_creations_pkey PRIMARY KEY (id),
    CONSTRAINT account_organization_creations_organization_key UNIQUE (organization_id),
    CONSTRAINT account_organization_creations_key_uq
        UNIQUE (entitlement_id, idempotency_key_digest),
    CONSTRAINT account_organization_creations_sequence_uq UNIQUE (entitlement_id, sequence),
    CONSTRAINT account_organization_creations_sequence_check CHECK (sequence BETWEEN 1 AND 10),
    CONSTRAINT account_organization_creations_key_digest_check
        CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_organization_creations_intent_digest_check
        CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT account_organization_creations_entitlement_fkey FOREIGN KEY (entitlement_id)
        REFERENCES request_engine.account_entitlements (id),
    CONSTRAINT account_organization_creations_identity_fkey FOREIGN KEY (native_identity_id)
        REFERENCES request_engine.native_identities (id),
    CONSTRAINT account_organization_creations_organization_fkey FOREIGN KEY (organization_id)
        REFERENCES request_engine.organizations (id),
    CONSTRAINT account_organization_creations_controller_fkey
        FOREIGN KEY (organization_id, controller_principal_id)
        REFERENCES request_engine.principals (organization_id, id)
);
CREATE INDEX account_entitlements_granted_by_idx
    ON request_engine.account_entitlements USING btree (granted_by_principal_id);
CREATE INDEX account_invitation_facts_invitation_idx
    ON request_engine.account_invitation_facts USING btree (invitation_id, created_at);
CREATE INDEX account_organization_creations_identity_idx
    ON request_engine.account_organization_creations USING btree (native_identity_id);
CREATE INDEX account_invitations_native_identity_idx
    ON request_engine.account_invitations USING btree (native_identity_id)
    WHERE native_identity_id IS NOT NULL;
CREATE INDEX account_organization_creations_controller_idx
    ON request_engine.account_organization_creations
    USING btree (organization_id, controller_principal_id);

CREATE FUNCTION request_engine.guard_account_entitlement_grantor() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM request_engine.principals p
         WHERE p.id = NEW.granted_by_principal_id
           AND p.principal_plane = 'platform' AND p.organization_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Account entitlement grantor must be a platform Principal'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.native_identity_id <> OLD.native_identity_id
        OR NEW.identity_authority_id <> OLD.identity_authority_id
        OR NEW.granted_by_principal_id <> OLD.granted_by_principal_id
        OR NEW.source_invitation_id <> OLD.source_invitation_id
        OR NEW.max_organizations <> OLD.max_organizations
        OR NEW.organizations_created < OLD.organizations_created
        OR NEW.revision <= OLD.revision
    ) THEN
        RAISE EXCEPTION 'Account entitlement provenance is immutable and counters monotone'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
ALTER FUNCTION request_engine.guard_account_entitlement_grantor()
    OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_engine.guard_account_entitlement_grantor() FROM PUBLIC;
CREATE TRIGGER account_entitlements_guard
    BEFORE INSERT OR UPDATE ON request_engine.account_entitlements
    FOR EACH ROW EXECUTE FUNCTION request_engine.guard_account_entitlement_grantor();
CREATE TRIGGER account_invitation_facts_append_only
    BEFORE DELETE OR UPDATE ON request_engine.account_invitation_facts
    FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
CREATE TRIGGER account_organization_creations_append_only
    BEFORE DELETE OR UPDATE ON request_engine.account_organization_creations
    FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
"""

_OWNERSHIP_AND_PRIVILEGES = rf"""
ALTER TABLE request_engine.account_invitations OWNER TO request_engine_schema_owner;
ALTER TABLE request_engine.account_invitation_facts OWNER TO request_engine_schema_owner;
ALTER TABLE request_engine.account_entitlements OWNER TO request_engine_schema_owner;
ALTER TABLE request_engine.account_organization_creations OWNER TO request_engine_schema_owner;
ALTER TABLE request_engine.account_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ONLY request_engine.account_invitations FORCE ROW LEVEL SECURITY;
ALTER TABLE request_engine.account_invitation_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ONLY request_engine.account_invitation_facts FORCE ROW LEVEL SECURITY;
ALTER TABLE request_engine.account_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE ONLY request_engine.account_entitlements FORCE ROW LEVEL SECURITY;
ALTER TABLE request_engine.account_organization_creations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ONLY request_engine.account_organization_creations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE request_engine.account_invitations FROM PUBLIC;
REVOKE ALL ON TABLE request_engine.account_invitation_facts FROM PUBLIC;
REVOKE ALL ON TABLE request_engine.account_entitlements FROM PUBLIC;
REVOKE ALL ON TABLE request_engine.account_organization_creations FROM PUBLIC;

GRANT SELECT (id, token_digest, delivery_channel, destination_email, max_organizations,
              status, revision, delivery_status, invited_by_principal_id,
              native_identity_id, intent_digest, idempotency_key_digest, created_at,
              expires_at, accepted_at, revoked_at),
      INSERT (id, token_digest, token_fingerprint, delivery_channel, destination_email,
              max_organizations, delivery_status, invited_by_principal_id,
              provenance_reference, idempotency_key_digest, intent_digest, expires_at),
      UPDATE (status, revision, delivery_status, native_identity_id, accepted_at,
              revoked_at, revoke_reason_code)
    ON TABLE request_engine.account_invitations TO {_D};
GRANT SELECT (invitation_id, action, actor_principal_id, idempotency_key_digest,
              intent_digest),
      INSERT (invitation_id, action, actor_principal_id, native_identity_id,
              revision_before, revision_after, reason_code, delivery_status,
              idempotency_key_digest, intent_digest, correlation_id)
    ON TABLE request_engine.account_invitation_facts TO {_D};
GRANT SELECT (id, identity_authority_id, native_identity_id, max_organizations,
              organizations_created, status, revision, granted_by_principal_id,
              source_invitation_id),
      INSERT (id, identity_authority_id, native_identity_id, entitlement_key,
              max_organizations, granted_by_principal_id, source_invitation_id),
      UPDATE (organizations_created, revision, updated_at)
    ON TABLE request_engine.account_entitlements TO {_D};
GRANT SELECT (entitlement_id, organization_id, controller_principal_id,
              idempotency_key_digest, intent_digest),
      INSERT (entitlement_id, native_identity_id, organization_id, controller_principal_id,
              sequence, idempotency_key_digest, intent_digest, correlation_id)
    ON TABLE request_engine.account_organization_creations TO {_D};
GRANT INSERT (default_timezone, default_locale, default_currency)
    ON TABLE request_engine.organizations TO {_D};
GRANT SELECT (revision) ON TABLE request_engine.initial_controller_policies TO {_D};
"""

# Narrow native-session boundary in the style of request_auth.lock_credentialed_native_identity:
# owned by the table owner, executable only by the control definer, returns a boolean,
# exposes no session material and takes only SHARE locks.
_SESSION_LOCK = r"""
CREATE FUNCTION request_auth.lock_active_native_session(
    p_identity_authority_id uuid, p_native_identity_id uuid, p_session_id uuid
) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
       OR p_session_id IS NULL THEN
        RETURN false;
    END IF;
    PERFORM 1 FROM request_engine.identity_authorities
     WHERE id = p_identity_authority_id AND kind = 'native' AND status = 'active'
     FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM 1 FROM request_engine.native_identities AS i
     WHERE i.id = p_native_identity_id
       AND i.identity_authority_id = p_identity_authority_id
       AND i.status = 'active'
     FOR SHARE OF i;
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM 1
      FROM request_engine.native_sessions AS s
      JOIN request_engine.native_identities AS i ON i.id = s.native_identity_id
      LEFT JOIN request_engine.native_credentials AS c ON c.id = s.password_credential_id
      LEFT JOIN request_engine.webauthn_credentials AS w ON w.id = s.webauthn_credential_id
      LEFT JOIN request_engine.native_identity_recovery_state AS r
             ON r.native_identity_id = i.id
     WHERE s.id = p_session_id AND s.native_identity_id = p_native_identity_id
       AND s.status = 'active' AND s.expires_at > clock_timestamp()
       AND s.session_epoch = i.session_epoch
       AND NOT s.recovery_derived
       AND coalesce(r.state, 'normal') <> 'recovery_restricted'
       AND (c.status = 'active' OR w.status = 'active')
     FOR SHARE OF s;
    RETURN FOUND;
END
$$;
ALTER FUNCTION request_auth.lock_active_native_session(uuid, uuid, uuid)
    OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_auth.lock_active_native_session(uuid, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_auth.lock_active_native_session(uuid, uuid, uuid)
    TO request_platform_control_definer;
"""

_PLATFORM_ACTOR = r"""
            BEGIN
                v_actor := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true), '')::bigint;
                v_correlation := NULLIF(current_setting(
                    'request_engine.correlation_id', true), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_actor IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;
            PERFORM 1 FROM request_engine.principals AS p
             WHERE p.id = v_actor AND p.principal_plane = 'platform'
               AND p.organization_id IS NULL AND p.active AND p.principal_kind = 'human'
               AND p.authority_revision = v_actor_revision
             FOR UPDATE OF p;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Platform Principal is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS g
                 WHERE g.principal_id = v_actor AND g.principal_plane = 'platform'
                   AND g.authority_plane = 'platform'
                   AND g.capability_key = 'organization.provision' AND g.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks organization.provision'
                    USING ERRCODE = '42501';
            END IF;
"""

_CONTROL_FUNCTIONS = (
    r"""
CREATE FUNCTION request_platform.create_account_invitation(
    p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text,
    p_delivery_channel text, p_destination_email text, p_max_organizations integer,
    p_expires_at timestamp with time zone, p_provenance_reference text,
    p_idempotency_key_digest text, p_intent_digest text
) RETURNS TABLE(invitation_id uuid, created boolean, status text, revision bigint,
                delivery_status text, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_actor uuid;
            v_actor_revision bigint;
            v_correlation uuid;
            v_existing record;
        BEGIN
            IF p_invitation_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_delivery_channel IS NULL
               OR p_delivery_channel NOT IN ('email', 'shared_code')
               OR (p_delivery_channel = 'email') <> (p_destination_email IS NOT NULL)
               OR p_max_organizations IS NULL OR p_max_organizations NOT BETWEEN 1 AND 10
               OR p_expires_at IS NULL OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '7 days 1 minute'
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Account invitation input is invalid' USING ERRCODE = '22023';
            END IF;
"""
    + _PLATFORM_ACTOR
    + r"""
            SELECT i.id, i.status, i.revision, i.delivery_status, i.expires_at,
                   i.intent_digest
              INTO v_existing
              FROM request_engine.account_invitations AS i
             WHERE i.invited_by_principal_id = v_actor
               AND i.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another invitation'
                        USING ERRCODE = 'RE409';
                END IF;
                RETURN QUERY SELECT v_existing.id, false, v_existing.status,
                    v_existing.revision, v_existing.delivery_status, v_existing.expires_at;
                RETURN;
            END IF;

            INSERT INTO request_engine.account_invitations (
                id, token_digest, token_fingerprint, delivery_channel, destination_email,
                max_organizations, delivery_status, invited_by_principal_id,
                provenance_reference, idempotency_key_digest, intent_digest, expires_at
            ) VALUES (
                p_invitation_id, p_token_digest, p_token_fingerprint, p_delivery_channel,
                p_destination_email, p_max_organizations,
                CASE WHEN p_delivery_channel = 'email' THEN 'pending' END,
                v_actor, btrim(p_provenance_reference), p_idempotency_key_digest,
                p_intent_digest, p_expires_at
            );
            INSERT INTO request_engine.account_invitation_facts (
                invitation_id, action, actor_principal_id, revision_before, revision_after,
                idempotency_key_digest, intent_digest, correlation_id
            ) VALUES (
                p_invitation_id, 'create', v_actor, 0, 1, p_idempotency_key_digest,
                p_intent_digest, v_correlation
            );
            RETURN QUERY SELECT p_invitation_id, true, 'pending'::text, 1::bigint,
                CASE WHEN p_delivery_channel = 'email' THEN 'pending' END::text,
                p_expires_at;
        END
        $fn$;
""",
    r"""
CREATE FUNCTION request_platform.record_account_invitation_delivery(
    p_invitation_id uuid, p_delivery_status text
) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_actor uuid;
            v_correlation uuid;
            v_invitation record;
        BEGIN
            IF p_invitation_id IS NULL OR p_delivery_status IS NULL
               OR p_delivery_status NOT IN ('sent', 'failed', 'unknown') THEN
                RAISE EXCEPTION 'Delivery outcome is invalid' USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_actor := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true), '')::uuid;
                v_correlation := NULLIF(current_setting(
                    'request_engine.correlation_id', true), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed' USING ERRCODE = '28000';
            END;
            SELECT i.id, i.revision, i.delivery_status, i.invited_by_principal_id
              INTO v_invitation
              FROM request_engine.account_invitations AS i
             WHERE i.id = p_invitation_id AND i.delivery_channel = 'email'
             FOR UPDATE;
            IF NOT FOUND OR v_actor IS NULL OR v_invitation.invited_by_principal_id <> v_actor
            THEN
                RAISE EXCEPTION 'Only the issuer records its delivery outcome'
                    USING ERRCODE = '42501';
            END IF;
            IF v_invitation.delivery_status <> 'pending' THEN
                RETURN v_invitation.delivery_status;
            END IF;
            UPDATE request_engine.account_invitations
               SET delivery_status = p_delivery_status
             WHERE id = p_invitation_id;
            INSERT INTO request_engine.account_invitation_facts (
                invitation_id, action, actor_principal_id, revision_before, revision_after,
                delivery_status, correlation_id
            ) VALUES (
                p_invitation_id, 'delivery', v_actor, v_invitation.revision,
                v_invitation.revision, p_delivery_status, v_correlation
            );
            RETURN p_delivery_status;
        END
        $fn$;
""",
    r"""
CREATE FUNCTION request_platform.revoke_account_invitation(
    p_invitation_id uuid, p_expected_revision bigint, p_reason_code text,
    p_idempotency_key_digest text, p_intent_digest text
) RETURNS TABLE(invitation_id uuid, status text, revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_actor uuid;
            v_actor_revision bigint;
            v_correlation uuid;
            v_fact record;
            v_invitation record;
        BEGIN
            IF p_invitation_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL OR p_reason_code !~ '^[a-z][a-z0-9_]{0,79}$'
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Account invitation revocation is invalid'
                    USING ERRCODE = '22023';
            END IF;
"""
    + _PLATFORM_ACTOR
    + r"""
            SELECT f.invitation_id, f.intent_digest INTO v_fact
              FROM request_engine.account_invitation_facts AS f
             WHERE f.actor_principal_id = v_actor AND f.action = 'revoke'
               AND f.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_fact.intent_digest <> p_intent_digest
                   OR v_fact.invitation_id <> p_invitation_id THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another revocation'
                        USING ERRCODE = 'RE409';
                END IF;
                RETURN QUERY SELECT i.id, i.status, i.revision
                  FROM request_engine.account_invitations AS i WHERE i.id = p_invitation_id;
                RETURN;
            END IF;
            SELECT i.id, i.status, i.revision INTO v_invitation
              FROM request_engine.account_invitations AS i
             WHERE i.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Account invitation not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_invitation.status <> 'pending' THEN
                RAISE EXCEPTION 'Account invitation is no longer pending'
                    USING ERRCODE = '55000';
            END IF;
            IF v_invitation.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Account invitation revision is stale' USING ERRCODE = '40001';
            END IF;
            UPDATE request_engine.account_invitations
               SET status = 'revoked', revision = revision + 1,
                   revoked_at = clock_timestamp(), revoke_reason_code = p_reason_code
             WHERE id = p_invitation_id;
            INSERT INTO request_engine.account_invitation_facts (
                invitation_id, action, actor_principal_id, revision_before, revision_after,
                reason_code, idempotency_key_digest, intent_digest, correlation_id
            ) VALUES (
                p_invitation_id, 'revoke', v_actor, v_invitation.revision,
                v_invitation.revision + 1, p_reason_code, p_idempotency_key_digest,
                p_intent_digest, v_correlation
            );
            RETURN QUERY SELECT p_invitation_id, 'revoked'::text, v_invitation.revision + 1;
        END
        $fn$;
""",
)

_READ_FUNCTION = r"""
CREATE FUNCTION request_platform.read_account_invitations(
    p_invitation_id uuid, p_after uuid, p_limit integer
) RETURNS TABLE(invitation_id uuid, delivery_channel text, destination_email text,
                max_organizations integer, status text, expired boolean, revision bigint,
                delivery_status text, invited_by_principal_id uuid,
                native_identity_id uuid, entitlement_id uuid,
                organizations_created integer, created_at timestamp with time zone,
                expires_at timestamp with time zone, accepted_at timestamp with time zone,
                revoked_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_actor uuid;
            v_revision bigint;
        BEGIN
            BEGIN
                v_actor := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true), '')::uuid;
                v_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true), '')::bigint;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_actor IS NULL OR NOT EXISTS (
                SELECT 1 FROM request_engine.principals p
                JOIN request_engine.principal_authority_grants g ON g.principal_id = p.id
                WHERE p.id = v_actor AND p.principal_plane = 'platform'
                  AND p.principal_kind = 'human' AND p.active
                  AND p.authority_revision = v_revision
                  AND g.principal_plane = 'platform' AND g.authority_plane = 'platform'
                  AND g.capability_key = 'platform.organization.read' AND g.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal may not inspect account invitations'
                    USING ERRCODE = '42501';
            END IF;
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'Page limit must be between 1 and 100' USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT i.id, i.delivery_channel, i.destination_email, i.max_organizations,
                   i.status, (i.status = 'pending' AND i.expires_at <= statement_timestamp()),
                   i.revision, i.delivery_status, i.invited_by_principal_id,
                   i.native_identity_id, e.id, e.organizations_created, i.created_at,
                   i.expires_at, i.accepted_at, i.revoked_at
              FROM request_engine.account_invitations AS i
              LEFT JOIN request_engine.account_entitlements AS e
                     ON e.source_invitation_id = i.id
             WHERE (p_invitation_id IS NULL OR i.id = p_invitation_id)
               AND (p_after IS NULL OR i.id > p_after)
             ORDER BY i.id
             LIMIT CASE WHEN p_invitation_id IS NULL THEN p_limit + 1 ELSE 1 END;
        END
        $fn$;
"""

_RUNTIME_FUNCTIONS = (
    r"""
CREATE FUNCTION request_auth.enroll_account_invitation(
    p_identity_authority_id uuid, p_token_digest bytea, p_native_identity_id uuid,
    p_credential_id uuid, p_entitlement_id uuid, p_login_handle text,
    p_password_verifier text
) RETURNS TABLE(invitation_id uuid, native_identity_id uuid, entitlement_id uuid,
                max_organizations integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_invitation record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_native_identity_id IS NULL OR p_credential_id IS NULL
               OR p_entitlement_id IS NULL OR p_login_handle IS NULL
               OR p_login_handle <> lower(btrim(p_login_handle))
               OR length(p_login_handle) NOT BETWEEN 1 AND 320
               OR p_password_verifier IS NULL
               OR NOT (p_password_verifier LIKE '$argon2id$%'
                       OR p_password_verifier LIKE 'scrypt$%')
            THEN
                RETURN;
            END IF;
            SELECT i.id, i.status, i.revision, i.expires_at, i.max_organizations,
                   i.invited_by_principal_id
              INTO v_invitation
              FROM request_engine.account_invitations AS i
             WHERE i.token_digest = p_token_digest
             FOR UPDATE;
            IF NOT FOUND OR v_invitation.status <> 'pending'
               OR v_invitation.expires_at <= clock_timestamp() THEN
                RETURN;
            END IF;
            -- Revoking the issuer's organization authority voids its pending invitations.
            PERFORM 1 FROM request_engine.principals AS p
              JOIN request_engine.principal_authority_grants AS g
                ON g.principal_id = p.id AND g.principal_plane = 'platform'
               AND g.authority_plane = 'platform'
               AND g.capability_key = 'organization.provision' AND g.status = 'active'
             WHERE p.id = v_invitation.invited_by_principal_id
               AND p.principal_plane = 'platform' AND p.organization_id IS NULL
               AND p.active AND p.principal_kind = 'human'
             FOR SHARE OF p;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            -- No row lock (the definer holds no UPDATE on authorities); the
            -- native_identities FK still takes KEY SHARE on the authority row.
            PERFORM 1 FROM request_engine.identity_authorities AS a
             WHERE a.id = p_identity_authority_id AND a.kind = 'native'
               AND a.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Native identity authority unavailable' USING ERRCODE = '55000';
            END IF;
            BEGIN
                INSERT INTO request_engine.native_identities (
                    id, identity_authority_id, login_handle
                ) VALUES (p_native_identity_id, p_identity_authority_id, p_login_handle);
            EXCEPTION WHEN unique_violation THEN
                RAISE EXCEPTION 'Native login handle is unavailable' USING ERRCODE = '23505';
            END;
            INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier)
            VALUES (p_credential_id, p_native_identity_id, p_password_verifier);
            UPDATE request_engine.account_invitations
               SET status = 'accepted', revision = revision + 1,
                   native_identity_id = p_native_identity_id, accepted_at = clock_timestamp()
             WHERE id = v_invitation.id;
            INSERT INTO request_engine.account_entitlements (
                id, identity_authority_id, native_identity_id, entitlement_key,
                max_organizations, granted_by_principal_id, source_invitation_id
            ) VALUES (
                p_entitlement_id, p_identity_authority_id, p_native_identity_id,
                'account.organization.create', v_invitation.max_organizations,
                v_invitation.invited_by_principal_id, v_invitation.id
            );
            INSERT INTO request_engine.account_invitation_facts (
                invitation_id, action, native_identity_id, revision_before, revision_after
            ) VALUES (
                v_invitation.id, 'accept', p_native_identity_id, v_invitation.revision,
                v_invitation.revision + 1
            );
            RETURN QUERY SELECT v_invitation.id, p_native_identity_id, p_entitlement_id,
                v_invitation.max_organizations;
        END
        $fn$;
""",
    r"""
CREATE FUNCTION request_auth.read_account_entitlement(
    p_identity_authority_id uuid, p_native_identity_id uuid
) RETURNS TABLE(entitlement_id uuid, status text, max_organizations integer,
                organizations_created integer, revision bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        SELECT e.id, e.status, e.max_organizations, e.organizations_created, e.revision
          FROM request_engine.account_entitlements AS e
         WHERE e.identity_authority_id = p_identity_authority_id
           AND e.native_identity_id = p_native_identity_id;
    $fn$;
""",
    r"""
CREATE FUNCTION request_auth.create_self_service_organization(
    p_identity_authority_id uuid, p_native_identity_id uuid, p_session_id uuid,
    p_idempotency_key_digest text, p_intent_digest text, p_organization_id uuid,
    p_organization_party_id uuid, p_controller_principal_id uuid,
    p_organization_key text, p_display_name text, p_timezone text, p_locale text,
    p_currency text, p_policy_key text, p_correlation_id uuid
) RETURNS TABLE(organization_id uuid, organization_party_id uuid,
                controller_principal_id uuid, controller_binding_id uuid,
                membership_id uuid, organization_key text, display_name text,
                default_timezone text, default_locale text, default_currency text,
                initial_controller_policy_key text, created boolean,
                max_organizations integer, organizations_created integer,
                entitlement_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $fn$
        #variable_conflict use_column
        DECLARE
            v_entitlement record;
            v_existing record;
            v_binding uuid := pg_catalog.gen_random_uuid();
            v_membership uuid;
            v_provenance text;
            v_current_policy text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL OR p_intent_digest !~ '^[0-9a-f]{64}$'
               OR p_organization_id IS NULL OR p_organization_party_id IS NULL
               OR p_controller_principal_id IS NULL
               OR p_organization_key IS NULL
               OR p_organization_key !~ '^[a-z0-9]+(-[a-z0-9]+)*$'
               OR length(p_organization_key) NOT BETWEEN 3 AND 63
               OR p_display_name IS NULL OR p_display_name <> btrim(p_display_name)
               OR length(p_display_name) NOT BETWEEN 1 AND 200
               OR p_timezone IS NULL
               OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_timezone_names t
                               WHERE t.name = p_timezone)
               OR p_locale IS NULL OR p_locale !~ '^[a-z]{2,3}(-[A-Z]{2})?$'
               OR p_currency IS NULL OR p_currency !~ '^[A-Z]{3}$'
               OR p_policy_key IS NULL
            THEN
                RAISE EXCEPTION 'Self-service organization input is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT request_auth.lock_active_native_session(
                p_identity_authority_id, p_native_identity_id, p_session_id
            ) THEN
                RAISE EXCEPTION 'An active normal native session is required'
                    USING ERRCODE = '42501';
            END IF;
            SELECT e.id, e.status, e.max_organizations, e.organizations_created,
                   e.revision, e.granted_by_principal_id
              INTO v_entitlement
              FROM request_engine.account_entitlements AS e
             WHERE e.identity_authority_id = p_identity_authority_id
               AND e.native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'No account entitlement to create organizations'
                    USING ERRCODE = '42501';
            END IF;

            SELECT c.organization_id, c.controller_principal_id, c.intent_digest
              INTO v_existing
              FROM request_engine.account_organization_creations AS c
             WHERE c.entitlement_id = v_entitlement.id
               AND c.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another organization'
                        USING ERRCODE = 'RE409';
                END IF;
                RETURN QUERY
                SELECT root.organization_id, root.organization_party_id,
                       root.controller_principal_id, root.controller_binding_id,
                       (SELECT m.id FROM request_engine.staff_memberships AS m
                         WHERE m.organization_id = root.organization_id
                           AND m.principal_id = root.controller_principal_id
                         ORDER BY m.id LIMIT 1),
                       p_organization_key, p_display_name, p_timezone, p_locale,
                       p_currency, root.initial_controller_policy_key, false,
                       v_entitlement.max_organizations, v_entitlement.organizations_created,
                       v_entitlement.id
                  FROM request_engine.organization_root_provisioning_facts AS root
                 WHERE root.organization_id = v_existing.organization_id;
                RETURN;
            END IF;

            IF v_entitlement.status <> 'active' THEN
                RAISE EXCEPTION 'Account entitlement is not active' USING ERRCODE = '42501';
            END IF;
            IF v_entitlement.organizations_created >= v_entitlement.max_organizations THEN
                RAISE EXCEPTION 'Account organization limit reached' USING ERRCODE = 'RE429';
            END IF;
            SELECT policy.policy_key INTO v_current_policy
              FROM request_engine.initial_controller_policies AS policy
             ORDER BY policy.revision DESC LIMIT 1;
            IF v_current_policy IS DISTINCT FROM p_policy_key THEN
                RAISE EXCEPTION 'Self-service roots use the newest initial controller policy'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT request_auth.lock_credentialed_native_identity(
                p_identity_authority_id, p_native_identity_id
            ) THEN
                RAISE EXCEPTION 'Self-service controller requires a credentialed identity'
                    USING ERRCODE = '42501';
            END IF;

            v_provenance := 'self-service-v1:' || p_intent_digest
                || ':entitlement:' || v_entitlement.id::text;
            PERFORM set_config('request_engine.initial_controller_policy', p_policy_key, true);

            INSERT INTO request_engine.organizations (
                id, organization_key, display_name, default_timezone, default_locale,
                default_currency
            ) VALUES (
                p_organization_id, p_organization_key, p_display_name, p_timezone,
                p_locale, p_currency
            );
            INSERT INTO request_engine.parties (
                id, organization_id, party_kind, display_name
            ) VALUES (
                p_organization_party_id, p_organization_id, 'organization', p_display_name
            );
            INSERT INTO request_engine.party_identity_revisions (
                organization_id, party_id, revision, change_kind, display_name, active, state
            ) VALUES (
                p_organization_id, p_organization_party_id, 1, 'registered',
                p_display_name, true,
                pg_catalog.jsonb_build_object(
                    'display_name', p_display_name,
                    'active', true,
                    'contact_points', '[]'::jsonb,
                    'documents', '[]'::jsonb
                )
            );
            INSERT INTO request_engine.principals (
                id, organization_id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_controller_principal_id, p_organization_id, 'tenant', 'human',
                'native:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                v_binding, p_organization_id, p_controller_principal_id, 'tenant',
                p_identity_authority_id, p_native_identity_id::text, 'active'
            );
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT p_organization_id, p_controller_principal_id, 'tenant', 'tenant_control',
                   capability_key, false, v_entitlement.granted_by_principal_id,
                   'provisioning', v_provenance
              FROM (VALUES
                  ('staff.invite'),
                  ('staff.manage_membership'),
                  ('staff.manage_authority'),
                  ('agent.provision'),
                  ('agent.manage_authority'),
                  ('agent.suspend'),
                  ('identity.bind')
              ) AS root_control(capability_key);
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id, authority_kind, scope_key
            )
            SELECT p_organization_id, p_controller_principal_id, p_organization_party_id,
                   'delegated', scope_key
              FROM (VALUES
                  ('operations.manage_profile'),
                  ('operations.manage_supply'),
                  ('operations.manage_terms'),
                  ('operations.manage_discovery')
              ) AS root_operations(scope_key);
            INSERT INTO request_engine.organization_provisioning_facts (
                organization_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, v_entitlement.granted_by_principal_id, v_provenance
            );
            INSERT INTO request_engine.organization_root_provisioning_facts (
                organization_id, organization_party_id, controller_principal_id,
                controller_binding_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, p_organization_party_id, p_controller_principal_id,
                v_binding, v_entitlement.granted_by_principal_id, v_provenance
            );

            UPDATE request_engine.account_entitlements
               SET organizations_created = organizations_created + 1,
                   revision = revision + 1, updated_at = clock_timestamp()
             WHERE id = v_entitlement.id;
            INSERT INTO request_engine.account_organization_creations (
                entitlement_id, native_identity_id, organization_id, controller_principal_id,
                sequence, idempotency_key_digest, intent_digest, correlation_id
            ) VALUES (
                v_entitlement.id, p_native_identity_id, p_organization_id,
                p_controller_principal_id, v_entitlement.organizations_created + 1,
                p_idempotency_key_digest, p_intent_digest, p_correlation_id
            );
            SELECT m.id INTO v_membership FROM request_engine.staff_memberships AS m
             WHERE m.organization_id = p_organization_id
               AND m.principal_id = p_controller_principal_id
             ORDER BY m.id LIMIT 1;

            RETURN QUERY SELECT p_organization_id, p_organization_party_id,
                p_controller_principal_id, v_binding, v_membership, p_organization_key,
                p_display_name, p_timezone, p_locale, p_currency, p_policy_key, true,
                v_entitlement.max_organizations, v_entitlement.organizations_created + 1,
                v_entitlement.id;
        END
        $fn$;
""",
)

_FUNCTION_ACL = rf"""
ALTER FUNCTION request_platform.create_account_invitation(
    uuid, bytea, text, text, text, integer, timestamp with time zone, text, text, text
) OWNER TO {_D};
ALTER FUNCTION request_platform.record_account_invitation_delivery(uuid, text) OWNER TO {_D};
ALTER FUNCTION request_platform.revoke_account_invitation(uuid, bigint, text, text, text)
    OWNER TO {_D};
ALTER FUNCTION request_platform.read_account_invitations(uuid, uuid, integer) OWNER TO {_D};
ALTER FUNCTION request_auth.enroll_account_invitation(
    uuid, bytea, uuid, uuid, uuid, text, text
) OWNER TO {_D};
ALTER FUNCTION request_auth.read_account_entitlement(uuid, uuid) OWNER TO {_D};
ALTER FUNCTION request_auth.create_self_service_organization(
    uuid, uuid, uuid, text, text, uuid, uuid, uuid, text, text, text, text, text, text, uuid
) OWNER TO {_D};

REVOKE ALL ON FUNCTION request_platform.create_account_invitation(
    uuid, bytea, text, text, text, integer, timestamp with time zone, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_platform.record_account_invitation_delivery(uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION request_platform.revoke_account_invitation(
    uuid, bigint, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_platform.read_account_invitations(uuid, uuid, integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION request_auth.enroll_account_invitation(
    uuid, bytea, uuid, uuid, uuid, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_auth.read_account_entitlement(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_auth.create_self_service_organization(
    uuid, uuid, uuid, text, text, uuid, uuid, uuid, text, text, text, text, text, text, uuid
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_platform.create_account_invitation(
    uuid, bytea, text, text, text, integer, timestamp with time zone, text, text, text
) TO request_platform_control;
GRANT EXECUTE ON FUNCTION request_platform.record_account_invitation_delivery(uuid, text)
    TO request_platform_control;
GRANT EXECUTE ON FUNCTION request_platform.revoke_account_invitation(
    uuid, bigint, text, text, text
) TO request_platform_control;
GRANT EXECUTE ON FUNCTION request_auth.enroll_account_invitation(
    uuid, bytea, uuid, uuid, uuid, text, text
) TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_auth.read_account_entitlement(uuid, uuid)
    TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_auth.create_self_service_organization(
    uuid, uuid, uuid, text, text, uuid, uuid, uuid, text, text, text, text, text, text, uuid
) TO request_engine_app;
"""


def upgrade() -> None:
    op.execute(_TABLES)
    op.execute(_OWNERSHIP_AND_PRIVILEGES)
    op.execute(_SESSION_LOCK)
    for function in _CONTROL_FUNCTIONS:
        op.execute(function)
    op.execute(_READ_FUNCTION)
    for function in _RUNTIME_FUNCTIONS:
        op.execute(function)
    op.execute(_FUNCTION_ACL)


def downgrade() -> None:
    raise RuntimeError("account ownership facts are immutable history; roll forward")
