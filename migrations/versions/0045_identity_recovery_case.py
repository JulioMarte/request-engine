"""Govern native identity recovery with double control and secure delivery (C).

Revision ID: 0045_identity_recovery_case
Revises: 0044_identity_topology_gate
Create Date: 2026-09-15

Implements the accepted plan in
``docs/architecture/auth-production-completion-plan.md`` section C under the
D1/D2 policy ratified by ADR 0013:

- Tenancy owns an ``identity_recovery_cases`` aggregate with an explicit
  requested -> approved -> issued -> consumed / revoked state machine. Expiry
  is a bounded predicate (like native recovery intents), not invented
  authoritative state.
- Approval requires a different HUMAN platform operator than the requester
  (structural CHECK plus command revalidation) and a fresh actor authority
  revision.
- Issuance stages the raw proof outside authoritative locks through the
  technical secret-delivery port; only an opaque reference, its fingerprint,
  the token digest and the delivery ticket reach PostgreSQL. The authoritative
  transaction creates the native recovery intent, links the case, creates the
  delivery ticket and writes a private append-only fact.
- Delivery tickets are leased/fenced; the worker publishes outside locks and
  finalizes with a claim token. A revoked case revokes its intent atomically.
- Consumption is linked atomically to the case in the same transaction as
  ``request_auth.consume_native_recovery_intent``.

The identity-topology advisory gate is the first statement of every command
that can change credential reachability (request/approve/issue/revoke), before
any row lock. Reads and worker delivery claims do not take the gate.

Appends 0002+ history only; 0001-0044 are untouched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045_identity_recovery_case"
down_revision: str | Sequence[str] | None = "0044_identity_topology_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_READ_DEFINER = "request_platform_definer"

_ACTOR_HELPER = "request_platform.assert_platform_identity_actor(text)"
_CREATE_FUNCTION = (
    "request_platform.create_identity_recovery_case(uuid, uuid, text, text, text, text, text)"
)
_APPROVE_FUNCTION = (
    "request_platform.approve_identity_recovery_case(uuid, bigint, text, text, text)"
)
_PREPARE_FUNCTION = "request_platform.prepare_identity_recovery_issue(uuid, bigint, text, text)"
_ISSUE_FUNCTION = (
    "request_platform.issue_identity_recovery_case"
    "(uuid, bigint, integer, uuid, bytea, text, timestamptz, uuid, text, text, text, text)"
)
_REVOKE_FUNCTION = "request_platform.revoke_identity_recovery_case(uuid, bigint, text, text, text)"
_READ_FUNCTION = "request_platform.read_identity_recovery_cases(uuid, uuid, integer)"
_CLAIM_FUNCTION = "request_platform.claim_identity_recovery_delivery_tickets(integer, integer)"
_COMPLETE_FUNCTION = (
    "request_platform.complete_identity_recovery_delivery_ticket(uuid, uuid, text, text)"
)
_RETRY_FUNCTION = (
    "request_platform.retry_identity_recovery_delivery_ticket(uuid, uuid, integer, text)"
)
_RENEW_FUNCTION = (
    "request_platform.renew_identity_recovery_delivery_ticket_lease(uuid, uuid, integer)"
)
_CREATE_INTENT_FUNCTION = (
    "request_auth.create_native_recovery_intent(uuid, uuid, bytea, text, timestamptz)"
)
_CONSUME_INTENT_FUNCTION = "request_auth.consume_native_recovery_intent(uuid, bytea, uuid, text)"
_ESTABLISH_ROOT_FUNCTION = (
    "request_platform.establish_root(uuid, bytea, uuid, uuid, text, uuid, text, uuid, uuid)"
)

_CASE_VIEW_COLUMNS = """
            recovery_case.id,
            recovery_case.target_native_identity_id,
            recovery_case.status,
            recovery_case.delivery_status,
            recovery_case.revision,
            recovery_case.issuance_generation,
            recovery_case.approval_expires_at,
            recovery_case.proof_expires_at,
            recovery_case.created_at,
            recovery_case.approved_at,
            recovery_case.issued_at,
            recovery_case.consumed_at,
            recovery_case.revoked_at"""

_CASE_VIEW_RETURNS = """
        RETURNS TABLE (
            case_id uuid,
            target_native_identity_id uuid,
            status text,
            delivery_status text,
            revision bigint,
            issuance_generation integer,
            approval_expires_at timestamptz,
            proof_expires_at timestamptz,
            created_at timestamptz,
            approved_at timestamptz,
            issued_at timestamptz,
            consumed_at timestamptz,
            revoked_at timestamptz
        )"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # 1. Case, delivery-ticket and private append-only fact tables. Only the
    # control definer writes them through reviewed functions; runtime roles have
    # no direct table access and the facts table is append-only.
    op.execute(
        """
        CREATE TABLE request_engine.identity_recovery_cases (
            id uuid PRIMARY KEY,
            target_native_identity_id uuid NOT NULL
                REFERENCES request_engine.native_identities(id),
            requester_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            approver_principal_id uuid
                REFERENCES request_engine.principals(id),
            status text NOT NULL DEFAULT 'requested',
            delivery_status text NOT NULL DEFAULT 'pending',
            reason_code text NOT NULL,
            evidence_reference text NOT NULL,
            delivery_destination_reference text NOT NULL,
            recovery_intent_id uuid
                REFERENCES request_engine.native_recovery_intents(id),
            issuance_generation integer NOT NULL DEFAULT 0,
            approval_expires_at timestamptz,
            proof_expires_at timestamptz,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            approved_at timestamptz,
            issued_at timestamptz,
            consumed_at timestamptz,
            revoked_at timestamptz,
            revoke_reason_code text,
            CONSTRAINT identity_recovery_cases_status_check
                CHECK (status IN ('requested', 'approved', 'issued', 'consumed', 'revoked')),
            CONSTRAINT identity_recovery_cases_delivery_status_check
                CHECK (delivery_status IN
                       ('pending', 'sending', 'delivered', 'unknown', 'failed')),
            CONSTRAINT identity_recovery_cases_reason_check
                CHECK (length(btrim(reason_code)) BETWEEN 1 AND 80),
            CONSTRAINT identity_recovery_cases_evidence_check
                CHECK (length(btrim(evidence_reference)) BETWEEN 1 AND 400),
            CONSTRAINT identity_recovery_cases_destination_check
                CHECK (length(btrim(delivery_destination_reference)) BETWEEN 1 AND 200),
            CONSTRAINT identity_recovery_cases_revision_check CHECK (revision >= 1),
            CONSTRAINT identity_recovery_cases_generation_check
                CHECK (issuance_generation >= 0),
            CONSTRAINT identity_recovery_cases_approver_check
                CHECK (approver_principal_id IS NULL
                       OR approver_principal_id <> requester_principal_id),
            CONSTRAINT identity_recovery_cases_state_check CHECK (
                (status = 'requested'
                    AND approver_principal_id IS NULL AND approved_at IS NULL
                    AND recovery_intent_id IS NULL AND issued_at IS NULL
                    AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'approved'
                    AND approver_principal_id IS NOT NULL AND approved_at IS NOT NULL
                    AND approval_expires_at IS NOT NULL
                    AND recovery_intent_id IS NULL AND issued_at IS NULL
                    AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'issued'
                    AND approver_principal_id IS NOT NULL AND approved_at IS NOT NULL
                    AND recovery_intent_id IS NOT NULL AND issued_at IS NOT NULL
                    AND proof_expires_at IS NOT NULL
                    AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'consumed'
                    AND recovery_intent_id IS NOT NULL AND issued_at IS NOT NULL
                    AND consumed_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND revoked_at IS NOT NULL AND revoke_reason_code IS NOT NULL)
            )
        );
        ALTER TABLE request_engine.identity_recovery_cases
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.identity_recovery_cases
            FROM PUBLIC, request_engine_app, request_engine_worker;

        CREATE TABLE request_engine.identity_recovery_delivery_tickets (
            id uuid PRIMARY KEY,
            case_id uuid NOT NULL
                REFERENCES request_engine.identity_recovery_cases(id),
            generation integer NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            secret_reference text NOT NULL,
            secret_digest text NOT NULL,
            destination_reference text NOT NULL,
            expires_at timestamptz NOT NULL,
            claim_token uuid,
            lease_until timestamptz,
            attempt_count integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 8,
            next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_error_class text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            delivered_at timestamptz,
            CONSTRAINT identity_recovery_delivery_tickets_status_check
                CHECK (status IN
                       ('pending', 'sending', 'delivered', 'unknown', 'failed', 'cancelled')),
            CONSTRAINT identity_recovery_delivery_tickets_generation_check
                CHECK (generation >= 1),
            CONSTRAINT identity_recovery_delivery_tickets_secret_check
                CHECK (length(btrim(secret_reference)) BETWEEN 1 AND 400),
            CONSTRAINT identity_recovery_delivery_tickets_digest_check
                CHECK (secret_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT identity_recovery_delivery_tickets_destination_check
                CHECK (length(btrim(destination_reference)) BETWEEN 1 AND 200),
            CONSTRAINT identity_recovery_delivery_tickets_attempts_check
                CHECK (attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100),
            CONSTRAINT identity_recovery_delivery_tickets_lease_check CHECK (
                (status = 'sending' AND claim_token IS NOT NULL AND lease_until IS NOT NULL)
                OR (status <> 'sending' AND claim_token IS NULL AND lease_until IS NULL)
            ),
            CONSTRAINT identity_recovery_delivery_tickets_case_generation_uq
                UNIQUE (case_id, generation)
        );
        ALTER TABLE request_engine.identity_recovery_delivery_tickets
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.identity_recovery_delivery_tickets
            FROM PUBLIC, request_engine_app, request_engine_worker;

        CREATE TABLE request_engine.platform_identity_recovery_facts (
            id uuid PRIMARY KEY,
            case_id uuid NOT NULL
                REFERENCES request_engine.identity_recovery_cases(id),
            action text NOT NULL,
            actor_principal_id uuid REFERENCES request_engine.principals(id),
            actor_authentication_method text,
            reason_code text,
            external_case_reference text,
            revision_before bigint NOT NULL,
            revision_after bigint NOT NULL,
            correlation_id uuid,
            capability_key text NOT NULL,
            idempotency_key_digest text,
            intent_digest text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_identity_recovery_facts_action_check
                CHECK (action IN ('request', 'approve', 'issue', 'revoke', 'consume',
                                  'deliver', 'delivery_unknown', 'delivery_failed')),
            CONSTRAINT platform_identity_recovery_facts_method_check
                CHECK (actor_authentication_method IS NULL
                       OR length(btrim(actor_authentication_method)) > 0),
            CONSTRAINT platform_identity_recovery_facts_reason_check
                CHECK (reason_code IS NULL
                       OR length(btrim(reason_code)) BETWEEN 1 AND 80),
            CONSTRAINT platform_identity_recovery_facts_case_check
                CHECK (external_case_reference IS NULL
                       OR length(btrim(external_case_reference)) BETWEEN 1 AND 400),
            CONSTRAINT platform_identity_recovery_facts_revision_check
                CHECK (revision_before >= 1 AND revision_after >= revision_before),
            CONSTRAINT platform_identity_recovery_facts_capability_check
                CHECK (length(btrim(capability_key)) > 0),
            CONSTRAINT platform_identity_recovery_facts_key_check
                CHECK (idempotency_key_digest IS NULL
                       OR idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_identity_recovery_facts_intent_check
                CHECK (intent_digest IS NULL OR intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_identity_recovery_facts_actor_key_uq
                UNIQUE (actor_principal_id, action, idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_identity_recovery_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_identity_recovery_facts
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE TRIGGER platform_identity_recovery_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.platform_identity_recovery_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    # 2. Reviewed column authority for the control definer. The control login
    # never touches these tables directly.
    op.execute(
        f"GRANT SELECT (id, target_native_identity_id, requester_principal_id, "
        f"approver_principal_id, status, delivery_status, reason_code, evidence_reference, "
        f"delivery_destination_reference, recovery_intent_id, issuance_generation, "
        f"approval_expires_at, proof_expires_at, revision, created_at, updated_at, "
        f"approved_at, issued_at, consumed_at, revoked_at, revoke_reason_code), "
        f"INSERT (id, target_native_identity_id, requester_principal_id, status, "
        f"reason_code, evidence_reference, delivery_destination_reference), "
        f"UPDATE (status, delivery_status, approver_principal_id, approved_at, "
        f"approval_expires_at, recovery_intent_id, issuance_generation, issued_at, "
        f"proof_expires_at, revision, updated_at, revoked_at, revoke_reason_code) "
        f"ON request_engine.identity_recovery_cases TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, case_id, generation, status, secret_reference, secret_digest, "
        f"destination_reference, expires_at, claim_token, lease_until, attempt_count, "
        f"max_attempts, next_attempt_at, last_error_class, created_at, updated_at, "
        f"delivered_at), "
        f"INSERT (id, case_id, generation, status, secret_reference, secret_digest, "
        f"destination_reference, expires_at), "
        f"UPDATE (status, claim_token, lease_until, attempt_count, next_attempt_at, "
        f"last_error_class, updated_at, delivered_at) "
        f"ON request_engine.identity_recovery_delivery_tickets TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, case_id, action, intent_digest, revision_after, "
        f"actor_principal_id, capability_key, idempotency_key_digest), "
        f"INSERT (id, case_id, action, actor_principal_id, actor_authentication_method, "
        f"reason_code, external_case_reference, revision_before, revision_after, "
        f"correlation_id, capability_key, idempotency_key_digest, intent_digest) "
        f"ON request_engine.platform_identity_recovery_facts TO {_CONTROL_DEFINER}"
    )
    op.execute("GRANT USAGE ON SCHEMA request_platform TO request_engine_worker")
    op.execute(
        f"GRANT SELECT (id, kind, status) ON request_engine.identity_authorities "
        f"TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, status), UPDATE (status, revoked_at) "
        f"ON request_engine.native_recovery_intents TO {_CONTROL_DEFINER}"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {_CREATE_INTENT_FUNCTION} TO {_CONTROL_DEFINER}")
    op.execute(
        f"GRANT SELECT (id, target_native_identity_id, status, delivery_status, revision, "
        f"issuance_generation, approval_expires_at, proof_expires_at, created_at, "
        f"approved_at, issued_at, consumed_at, revoked_at) "
        f"ON request_engine.identity_recovery_cases TO {_READ_DEFINER}"
    )

    # 3. Shared platform actor revalidation. Owned by the control definer and not
    # callable by the runtime control login; only reviewed definer functions call it.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.assert_platform_identity_actor(p_capability text)
        RETURNS TABLE (actor_id uuid, actor_method text, correlation_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.identity.recover', 'platform.identity.recovery_approve'
            ) THEN
                RAISE EXCEPTION 'Unknown platform identity recovery capability'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot administer identity recovery'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.principal_plane = 'platform'
                   AND actor_grant.authority_plane = 'platform'
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks identity recovery authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $function$;
        ALTER FUNCTION {_ACTOR_HELPER} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_ACTOR_HELPER} FROM PUBLIC;
        """
    )

    # 4. Create a recovery case. The requester cannot approve their own case.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.create_identity_recovery_case(
            p_case_id uuid,
            p_target_native_identity_id uuid,
            p_reason_code text,
            p_evidence_reference text,
            p_delivery_destination_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        {_CASE_VIEW_RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_identity_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_target_native_identity_id IS NULL
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_evidence_reference IS NULL
               OR length(btrim(p_evidence_reference)) NOT BETWEEN 1 AND 400
               OR p_delivery_destination_reference IS NULL
               OR length(btrim(p_delivery_destination_reference)) NOT BETWEEN 1 AND 200
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Identity recovery case input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'request'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery request'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            -- Authority/identity locks belong to the auth primitives; this
            -- command only validates current reachability before creating the case.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_target_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
               AND native_identity.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Recovery target is not an active Native identity'
                    USING ERRCODE = '22023';
            END IF;

            INSERT INTO request_engine.identity_recovery_cases (
                id,
                target_native_identity_id,
                requester_principal_id,
                status,
                reason_code,
                evidence_reference,
                delivery_destination_reference
            ) VALUES (
                p_case_id,
                p_target_native_identity_id,
                v_actor_id,
                'requested',
                btrim(p_reason_code),
                btrim(p_evidence_reference),
                btrim(p_delivery_destination_reference)
            );
            INSERT INTO request_engine.platform_identity_recovery_facts (
                id,
                case_id,
                action,
                actor_principal_id,
                actor_authentication_method,
                reason_code,
                external_case_reference,
                revision_before,
                revision_after,
                correlation_id,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                uuidv7(),
                p_case_id,
                'request',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                btrim(p_evidence_reference),
                1,
                1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_CREATE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_CREATE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_CREATE_FUNCTION} TO request_platform_control;
        """
    )

    # 5. Approve a case. A distinct HUMAN platform operator must hold
    # platform.identity.recovery_approve; the target must still be reachable.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.approve_identity_recovery_case(
            p_case_id uuid,
            p_expected_revision bigint,
            p_reason_code text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        {_CASE_VIEW_RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_identity_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Identity recovery approval input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor(
                  'platform.identity.recovery_approve'
              );

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'approve'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery approval'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'requested' THEN
                RAISE EXCEPTION 'Only a requested recovery case can be approved'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.requester_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'The recovery requester cannot approve their own case'
                    USING ERRCODE = '42501';
            END IF;

            -- Authority/identity locks belong to the auth primitives; approval
            -- only revalidates that the target is still reachable today.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_case.target_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
               AND native_identity.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Recovery target is not an active Native identity'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'approved',
                   approver_principal_id = v_actor_id,
                   approved_at = clock_timestamp(),
                   approval_expires_at = clock_timestamp() + interval '24 hours',
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
            INSERT INTO request_engine.platform_identity_recovery_facts (
                id,
                case_id,
                action,
                actor_principal_id,
                actor_authentication_method,
                reason_code,
                external_case_reference,
                revision_before,
                revision_after,
                correlation_id,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                uuidv7(),
                p_case_id,
                'approve',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recovery_approve',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_APPROVE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_APPROVE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_APPROVE_FUNCTION} TO request_platform_control;
        """
    )

    # 6. Prepare an issuance. Revalidates actor and case, and returns the next
    # generation so the caller can stage the proof before the authoritative
    # transaction. Replay returns the current case without staging anything.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.prepare_identity_recovery_issue(
            p_case_id uuid,
            p_expected_revision bigint,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            replayed boolean,
            case_id uuid,
            target_native_identity_id uuid,
            status text,
            delivery_status text,
            revision bigint,
            issuance_generation integer,
            approval_expires_at timestamptz,
            proof_expires_at timestamptz,
            created_at timestamptz,
            approved_at timestamptz,
            issued_at timestamptz,
            consumed_at timestamptz,
            revoked_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Identity recovery issuance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'issue'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery issuance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    true,
{_CASE_VIEW_COLUMNS}
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;

            RETURN QUERY SELECT
                false,
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_PREPARE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_PREPARE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_PREPARE_FUNCTION} TO request_platform_control;
        """
    )

    # 7. Issue a proof. The authoritative transaction supersedes prior live
    # proofs for the same identity, creates the recovery intent, links the case,
    # creates the delivery ticket and writes the append-only fact.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.issue_identity_recovery_case(
            p_case_id uuid,
            p_expected_revision bigint,
            p_generation integer,
            p_recovery_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_proof_expires_at timestamptz,
            p_ticket_id uuid,
            p_secret_reference text,
            p_secret_digest text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        {_CASE_VIEW_RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_superseded record;
            v_created boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_generation IS NULL OR p_generation < 1
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{{16}}$'
               OR p_proof_expires_at IS NULL
               OR p_proof_expires_at <= clock_timestamp()
               OR p_proof_expires_at > clock_timestamp() + interval '30 minutes'
               OR p_ticket_id IS NULL
               OR p_secret_reference IS NULL
               OR length(btrim(p_secret_reference)) NOT BETWEEN 1 AND 400
               OR p_secret_digest IS NULL
               OR p_secret_digest !~ '^[0-9a-f]{{64}}$'
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Identity recovery issuance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'issue'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery issuance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF p_generation <> v_case.issuance_generation + 1 THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is stale'
                    USING ERRCODE = '40001';
            END IF;

            -- The auth primitive owns the authoritative authority/identity locks
            -- and revokes every prior pending intent for the target. Calling it
            -- before the case lock serializes concurrent issuances of the same
            -- identity on the identity row instead of on the case set.
            SELECT request_auth.create_native_recovery_intent(
                v_case.target_native_identity_id,
                p_recovery_id,
                p_token_digest,
                p_token_fingerprint,
                p_proof_expires_at
            ) INTO v_created;
            IF v_created IS NOT TRUE THEN
                RAISE EXCEPTION 'Recovery target is no longer eligible for issuance'
                    USING ERRCODE = '23514';
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF p_generation <> v_case.issuance_generation + 1 THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is stale'
                    USING ERRCODE = '40001';
            END IF;

            -- A new issuance supersedes every other live proof of this identity.
            FOR v_superseded IN
                SELECT candidate.id, candidate.revision
                  FROM request_engine.identity_recovery_cases AS candidate
                 WHERE candidate.target_native_identity_id = v_case.target_native_identity_id
                   AND candidate.status = 'issued'
                   AND candidate.id <> p_case_id
                 ORDER BY candidate.id
                 FOR UPDATE
            LOOP
                UPDATE request_engine.identity_recovery_cases
                   SET status = 'revoked',
                       revoked_at = clock_timestamp(),
                       revoke_reason_code = 'superseded_by_new_issuance',
                       revision = identity_recovery_cases.revision + 1,
                       updated_at = clock_timestamp()
                 WHERE id = v_superseded.id;
                UPDATE request_engine.identity_recovery_delivery_tickets
                   SET status = 'cancelled',
                       claim_token = NULL,
                       lease_until = NULL,
                       updated_at = clock_timestamp()
                 WHERE identity_recovery_delivery_tickets.case_id = v_superseded.id
                   AND identity_recovery_delivery_tickets.status IN ('pending', 'sending');
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_superseded.id,
                    'revoke',
                    v_actor_id,
                    v_actor_method,
                    'superseded_by_new_issuance',
                    NULL,
                    v_superseded.revision,
                    v_superseded.revision + 1,
                    v_correlation_id,
                    'platform.identity.recover',
                    NULL,
                    NULL
                );
            END LOOP;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'issued',
                   recovery_intent_id = p_recovery_id,
                   issuance_generation = p_generation,
                   issued_at = clock_timestamp(),
                   proof_expires_at = p_proof_expires_at,
                   delivery_status = 'pending',
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
            INSERT INTO request_engine.identity_recovery_delivery_tickets (
                id,
                case_id,
                generation,
                status,
                secret_reference,
                secret_digest,
                destination_reference,
                expires_at
            ) VALUES (
                p_ticket_id,
                p_case_id,
                p_generation,
                'pending',
                btrim(p_secret_reference),
                p_secret_digest,
                v_case.delivery_destination_reference,
                p_proof_expires_at
            );
            INSERT INTO request_engine.platform_identity_recovery_facts (
                id,
                case_id,
                action,
                actor_principal_id,
                actor_authentication_method,
                reason_code,
                external_case_reference,
                revision_before,
                revision_after,
                correlation_id,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                uuidv7(),
                p_case_id,
                'issue',
                v_actor_id,
                v_actor_method,
                'recovery_issued',
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_ISSUE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_ISSUE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_ISSUE_FUNCTION} TO request_platform_control;
        """
    )

    # 8. Revoke a case. Revocation atomically kills the linked intent and
    # cancels any live delivery ticket; a late publish cannot revive it.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.revoke_identity_recovery_case(
            p_case_id uuid,
            p_expected_revision bigint,
            p_reason_code text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        {_CASE_VIEW_RETURNS}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Identity recovery revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery revocation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status IN ('consumed', 'revoked') THEN
                RAISE EXCEPTION 'Identity recovery case is already terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF v_case.status = 'issued' THEN
                UPDATE request_engine.native_recovery_intents
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE id = v_case.recovery_intent_id
                   AND native_recovery_intents.status = 'pending';
                UPDATE request_engine.identity_recovery_delivery_tickets
                   SET status = 'cancelled',
                       claim_token = NULL,
                       lease_until = NULL,
                       updated_at = clock_timestamp()
                 WHERE identity_recovery_delivery_tickets.case_id = p_case_id
                   AND identity_recovery_delivery_tickets.status IN ('pending', 'sending');
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revoke_reason_code = btrim(p_reason_code),
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
            INSERT INTO request_engine.platform_identity_recovery_facts (
                id,
                case_id,
                action,
                actor_principal_id,
                actor_authentication_method,
                reason_code,
                external_case_reference,
                revision_before,
                revision_after,
                correlation_id,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                uuidv7(),
                p_case_id,
                'revoke',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_REVOKE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_REVOKE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_REVOKE_FUNCTION} TO request_platform_control;
        """
    )

    # 9. Bounded private read projection for the dedicated platform read login.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.read_identity_recovery_cases(
            p_case_id uuid,
            p_after uuid,
            p_limit integer
        )
        {_CASE_VIEW_RETURNS}
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Identity recovery case page limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY SELECT
{_CASE_VIEW_COLUMNS}
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE (p_case_id IS NULL OR recovery_case.id = p_case_id)
               AND (p_after IS NULL OR recovery_case.id > p_after)
             ORDER BY recovery_case.id
             LIMIT p_limit;
        END
        $function$;
        ALTER FUNCTION {_READ_FUNCTION} OWNER TO {_READ_DEFINER};
        REVOKE ALL ON FUNCTION {_READ_FUNCTION} FROM PUBLIC;
        """
    )

    # 10. Fenced delivery-ticket lease surface for the technical delivery worker.
    # The worker publishes outside locks and finalizes with its claim token.
    op.execute(
        f"""
        CREATE FUNCTION request_platform.claim_identity_recovery_delivery_tickets(
            p_limit integer,
            p_lease_seconds integer
        )
        RETURNS TABLE (
            ticket_id uuid,
            case_id uuid,
            generation integer,
            secret_reference text,
            secret_digest text,
            destination_reference text,
            expires_at timestamptz,
            attempt_count integer,
            claim_token uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Delivery ticket claim limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            IF p_lease_seconds IS NULL OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
                RAISE EXCEPTION 'Delivery ticket lease must be between 1 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;

            RETURN QUERY
            WITH candidate AS (
                SELECT ticket.id
                  FROM request_engine.identity_recovery_delivery_tickets AS ticket
                  JOIN request_engine.identity_recovery_cases AS recovery_case
                    ON recovery_case.id = ticket.case_id
                 WHERE ticket.status = 'pending'
                   AND ticket.next_attempt_at <= clock_timestamp()
                   AND ticket.expires_at > clock_timestamp()
                   AND ticket.attempt_count < ticket.max_attempts
                   AND recovery_case.status = 'issued'
                 ORDER BY ticket.next_attempt_at, ticket.id
                 LIMIT p_limit
                 FOR UPDATE OF ticket SKIP LOCKED
            )
            UPDATE request_engine.identity_recovery_delivery_tickets AS ticket
               SET status = 'sending',
                   claim_token = uuidv7(),
                   lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
                   attempt_count = ticket.attempt_count + 1,
                   updated_at = clock_timestamp()
              FROM candidate
             WHERE ticket.id = candidate.id
            RETURNING ticket.id,
                      ticket.case_id,
                      ticket.generation,
                      ticket.secret_reference,
                      ticket.secret_digest,
                      ticket.destination_reference,
                      ticket.expires_at,
                      ticket.attempt_count,
                      ticket.claim_token;

            UPDATE request_engine.identity_recovery_cases AS recovery_case
               SET delivery_status = 'sending',
                   revision = recovery_case.revision + 1,
                   updated_at = clock_timestamp()
             WHERE recovery_case.status = 'issued'
               AND recovery_case.delivery_status = 'pending'
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.identity_recovery_delivery_tickets AS ticket
                    WHERE ticket.case_id = recovery_case.id
                      AND ticket.status = 'sending'
                      AND ticket.lease_until > clock_timestamp()
               );
        END
        $function$;
        ALTER FUNCTION {_CLAIM_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_CLAIM_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_CLAIM_FUNCTION} TO request_engine_worker;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION request_platform.complete_identity_recovery_delivery_ticket(
            p_ticket_id uuid,
            p_claim_token uuid,
            p_outcome text,
            p_error_class text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_case_id uuid;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_outcome IS NULL
               OR p_outcome NOT IN ('delivered', 'unknown', 'failed')
               OR (p_error_class IS NOT NULL
                   AND length(btrim(p_error_class)) NOT BETWEEN 1 AND 80) THEN
                RAISE EXCEPTION 'Delivery completion input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE request_engine.identity_recovery_delivery_tickets
               SET status = p_outcome,
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = CASE
                       WHEN p_outcome = 'delivered' THEN NULL
                       ELSE btrim(p_error_class)
                   END,
                   delivered_at = CASE
                       WHEN p_outcome = 'delivered' THEN clock_timestamp()
                       ELSE delivered_at
                   END,
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending'
            RETURNING case_id INTO v_case_id;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET delivery_status = p_outcome,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_case_id
               AND status = 'issued'
            RETURNING revision - 1, revision INTO v_revision_before, v_revision_after;
            IF FOUND THEN
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_case_id,
                    CASE p_outcome
                        WHEN 'delivered' THEN 'deliver'
                        WHEN 'unknown' THEN 'delivery_unknown'
                        ELSE 'delivery_failed'
                    END,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_revision_before,
                    v_revision_after,
                    NULL,
                    'platform.identity.recovery_delivery',
                    NULL,
                    NULL
                );
            END IF;
            RETURN true;
        END
        $function$;
        ALTER FUNCTION {_COMPLETE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_COMPLETE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_COMPLETE_FUNCTION} TO request_engine_worker;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION request_platform.retry_identity_recovery_delivery_ticket(
            p_ticket_id uuid,
            p_claim_token uuid,
            p_delay_seconds integer,
            p_error_class text
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_case_id uuid;
            v_status text;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_delay_seconds IS NULL
               OR p_delay_seconds < 0 OR p_delay_seconds > 86400
               OR p_error_class IS NULL
               OR length(btrim(p_error_class)) NOT BETWEEN 1 AND 80 THEN
                RAISE EXCEPTION 'Delivery retry input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE request_engine.identity_recovery_delivery_tickets
               SET status = CASE
                       WHEN attempt_count >= max_attempts THEN 'failed'
                       ELSE 'pending'
                   END,
                   next_attempt_at = clock_timestamp() + make_interval(secs => p_delay_seconds),
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = btrim(p_error_class),
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending'
            RETURNING case_id, status INTO v_case_id, v_status;
            IF NOT FOUND THEN
                RETURN 'stale';
            END IF;

            IF v_status = 'pending' THEN
                UPDATE request_engine.identity_recovery_cases
                   SET delivery_status = 'pending',
                       revision = revision + 1,
                       updated_at = clock_timestamp()
                 WHERE id = v_case_id
                   AND status = 'issued';
                RETURN 'pending';
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET delivery_status = 'failed',
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_case_id
               AND status = 'issued'
            RETURNING revision - 1, revision INTO v_revision_before, v_revision_after;
            IF FOUND THEN
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_case_id,
                    'delivery_failed',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_revision_before,
                    v_revision_after,
                    NULL,
                    'platform.identity.recovery_delivery',
                    NULL,
                    NULL
                );
            END IF;
            RETURN 'dead';
        END
        $function$;
        ALTER FUNCTION {_RETRY_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_RETRY_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_RETRY_FUNCTION} TO request_engine_worker;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION request_platform.renew_identity_recovery_delivery_ticket_lease(
            p_ticket_id uuid,
            p_claim_token uuid,
            p_extension_seconds integer
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_extension_seconds IS NULL
               OR p_extension_seconds < 1 OR p_extension_seconds > 900 THEN
                RAISE EXCEPTION 'Delivery lease renewal input is invalid'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE request_engine.identity_recovery_delivery_tickets
               SET lease_until = GREATEST(lease_until, clock_timestamp())
                   + make_interval(secs => p_extension_seconds),
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending';
            RETURN FOUND;
        END
        $function$;
        ALTER FUNCTION {_RENEW_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_RENEW_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_RENEW_FUNCTION} TO request_engine_worker;
        """
    )

    # 11. Link consumption of the recovery intent to the governed case in the
    # same transaction. The body is re-emitted from 0040 with the case update
    # and its append-only fact inserted after the intent is consumed.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION request_auth.consume_native_recovery_intent(
            p_recovery_id uuid, p_token_digest bytea,
            p_new_credential_id uuid, p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $function$
        DECLARE
            v_native_identity_id uuid;
            v_identity_status text;
            v_case_id uuid;
            v_case_revision_before bigint;
            v_case_revision_after bigint;
        BEGIN
            -- Resolve a candidate without holding an intent lock. Identity is
            -- the credential serialization root, after the authority suspension gate.
            SELECT r.native_identity_id INTO v_native_identity_id
              FROM request_engine.native_recovery_intents r
             WHERE r.id = p_recovery_id AND r.token_digest = p_token_digest
               AND r.status = 'pending' AND r.expires_at > clock_timestamp();
            IF NOT FOUND THEN RETURN NULL; END IF;

            -- Authority is locked before identity; SHARE conflicts with status UPDATE.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN NULL; END IF;

            SELECT i.status INTO v_identity_status
              FROM request_engine.native_identities i
             WHERE i.id = v_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN RETURN NULL; END IF;

            -- The first read was advisory: expiry, revocation and a competing
            -- successful recovery must be revalidated after the identity lock.
            PERFORM 1 FROM request_engine.native_recovery_intents r
             WHERE r.id = p_recovery_id AND r.native_identity_id = v_native_identity_id
               AND r.token_digest = p_token_digest AND r.status = 'pending'
               AND r.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN RETURN NULL; END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked', revision = revision + 1,
                   rotated_at = clock_timestamp(), revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password' AND status = 'active';
            INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier)
                VALUES (p_new_credential_id, v_native_identity_id, p_new_verifier);
            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1, revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;
            UPDATE request_engine.native_sessions
               SET status = 'revoked', revoked_at = clock_timestamp(),
                   revocation_reason = 'credential_recovery'
             WHERE native_identity_id = v_native_identity_id AND status = 'active';
            UPDATE request_engine.native_recovery_intents
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = p_recovery_id;
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked', revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND id <> p_recovery_id AND status = 'pending';

            UPDATE request_engine.identity_recovery_cases
               SET status = 'consumed',
                   consumed_at = clock_timestamp(),
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE recovery_intent_id = p_recovery_id
               AND status = 'issued'
            RETURNING id, revision - 1, revision
                 INTO v_case_id, v_case_revision_before, v_case_revision_after;
            IF FOUND THEN
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_case_id,
                    'consume',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_case_revision_before,
                    v_case_revision_after,
                    NULL,
                    'platform.identity.recovery_consume',
                    NULL,
                    NULL
                );
            END IF;
            RETURN v_native_identity_id;
        END
        $function$;
        ALTER FUNCTION {_CONSUME_INTENT_FUNCTION} OWNER TO request_engine_schema_owner;
        """
    )

    # 12. Bootstrap trust set: the two new platform identity capabilities are
    # part of the root trust list and are propagated to existing platform
    # controllers that already hold platform.tenant_provisioner.provision.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION request_platform.establish_root(
            p_intent_id uuid,
            p_token_digest bytea,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_password_verifier text,
            p_principal_id uuid,
            p_binding_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_provenance text;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();
            -- Different intents must not race to create two initial Platform roots.
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476356);

            SELECT provenance_reference
              INTO v_provenance
              FROM request_engine.platform_bootstrap_intents
             WHERE id = p_intent_id
               AND token_digest = p_token_digest
               AND permitted_action = 'platform.root.establish'
               AND status = 'pending'
               AND expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1 FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists' USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native'
               OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (p_native_identity_id, p_identity_authority_id, p_login_handle);
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (p_credential_id, p_native_identity_id, p_password_verifier);
            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id,
                'platform',
                'human',
                'native-bootstrap:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id,
                p_principal_id,
                'platform',
                p_identity_authority_id,
                p_native_identity_id::text,
                'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   capability_key,
                   delegable,
                   'trust_bootstrap',
                   'platform-bootstrap:' || p_intent_id::text || ':' || v_provenance
              FROM (VALUES
                  ('platform.principal.provision', true),
                  ('platform.tenant_provisioner.provision', true),
                  ('organization.provision', true),
                  ('platform.identity.recover', false),
                  ('platform.identity.read', false),
                  ('platform.identity.recovery_approve', false),
                  ('platform.provisioner.read', false),
                  ('platform.provisioner.manage_lifecycle', false)
              ) AS initial_grant(capability_key, delegable);

            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_intent_id;
            RETURN p_principal_id;
        END
        $function$;
        ALTER FUNCTION {_ESTABLISH_ROOT_FUNCTION} OWNER TO request_bootstrap_definer;
        """
    )
    op.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        )
        SELECT DISTINCT controller.id,
               'platform',
               'platform',
               capability.capability_key,
               false,
               'trust_bootstrap',
               'platform-controller-policy-v1-recovery:' || controller.id::text
          FROM request_engine.principals AS controller
          JOIN request_engine.principal_authority_grants AS control_grant
            ON control_grant.principal_id = controller.id
           AND control_grant.principal_plane = 'platform'
           AND control_grant.authority_plane = 'platform'
           AND control_grant.capability_key = 'platform.tenant_provisioner.provision'
           AND control_grant.status = 'active'
          CROSS JOIN (
              VALUES ('platform.identity.read'),
                     ('platform.identity.recovery_approve')
          ) AS capability(capability_key)
         WHERE controller.principal_plane = 'platform'
           AND controller.active
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove governed identity recovery; roll forward")
