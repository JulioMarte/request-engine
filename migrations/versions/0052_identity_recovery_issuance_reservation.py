"""Reserve the recovery issuance generation per attempt before external I/O.

Revision ID: 0052_issuance_reservation
Revises: 0051_oidc_identity_link
Create Date: 2026-09-16

Implements the generation-reservation remedy required by
``docs/architecture/auth-production-completion-plan.md`` section C2: the
generation is reserved with a create-if-absent row before the raw proof is
staged, so two concurrent issuances of the same case cannot both compute the
same generation. Previously ``prepare_identity_recovery_issue`` returned the
next generation without persisting it, so a second caller that lost the
authoritative transaction could discard the retained secret the winner's
delivery ticket references.

The reservation is per attempt (case, generation), not a single field on the
case, because a single field cannot validate two concurrent reservations: the
second ``prepare`` would overwrite the first. ``prepare`` allocates
``max(reserved) + 1`` (or the case's committed generation + 1 when no
reservation is live) and returns that reserved generation. The authoritative
``issue`` transaction only proceeds when the exact
``(case, generation, idempotency_key_digest)`` reservation exists, and deletes
it once the case is durably issued.

Appends 0002+ history only; 0001-0051 are untouched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052_issuance_reservation"
down_revision: str | Sequence[str] | None = "0051_oidc_identity_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"

_PREPARE_FUNCTION = "request_platform.prepare_identity_recovery_issue(uuid, bigint, text, text)"
_ISSUE_FUNCTION = (
    "request_platform.issue_identity_recovery_case"
    "(uuid, bigint, integer, uuid, bytea, text, timestamptz, uuid, text, text, text, text)"
)

_RESERVATION_TABLE = "request_engine.identity_recovery_issuance_reservations"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # 1. Per-attempt generation reservation. Only the control definer writes it
    # through reviewed functions; runtime roles have no direct table access.
    op.execute(
        """
        CREATE TABLE request_engine.identity_recovery_issuance_reservations (
            case_id uuid NOT NULL
                REFERENCES request_engine.identity_recovery_cases(id),
            generation integer NOT NULL,
            idempotency_key_digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT identity_recovery_issuance_reservations_pkey
                PRIMARY KEY (case_id, generation),
            CONSTRAINT identity_recovery_issuance_reservations_key_uq
                UNIQUE (case_id, idempotency_key_digest),
            CONSTRAINT identity_recovery_issuance_reservations_generation_check
                CHECK (generation >= 1),
            CONSTRAINT identity_recovery_issuance_reservations_digest_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$')
        );
        ALTER TABLE request_engine.identity_recovery_issuance_reservations
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.identity_recovery_issuance_reservations
            FROM PUBLIC, request_engine_app, request_engine_worker;
        """
    )

    # 2. Reviewed column authority for the control definer. DELETE is a
    # table-level privilege in PostgreSQL; the definer deletes only the exact
    # reservation it validated and no other table grant is added.
    op.execute(
        f"GRANT SELECT (case_id, generation, idempotency_key_digest), "
        f"INSERT (case_id, generation, idempotency_key_digest) "
        f"ON {_RESERVATION_TABLE} TO {_CONTROL_DEFINER}"
    )
    op.execute(f"GRANT DELETE ON {_RESERVATION_TABLE} TO {_CONTROL_DEFINER}")

    # 3. Prepare reserves the generation before the caller stages the proof.
    # The replay path still returns the committed case view; a non-replay
    # return substitutes the reserved generation for the committed one.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION request_platform.prepare_identity_recovery_issue(
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
            v_reserved integer;
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
                    recovery_case.revoked_at
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

            -- Reuse the reservation for this idempotency key; otherwise reserve
            -- the next generation above every live reservation and the last
            -- committed issuance. The FOR UPDATE case lock serializes allocation.
            SELECT reservation.generation INTO v_reserved
              FROM request_engine.identity_recovery_issuance_reservations AS reservation
             WHERE reservation.case_id = p_case_id
               AND reservation.idempotency_key_digest = p_idempotency_key_digest;
            IF NOT FOUND THEN
                SELECT COALESCE(max(reservation.generation), v_case.issuance_generation) + 1
                  INTO v_reserved
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id;
                INSERT INTO request_engine.identity_recovery_issuance_reservations
                    (case_id, generation, idempotency_key_digest)
                VALUES (p_case_id, v_reserved, p_idempotency_key_digest);
            END IF;

            RETURN QUERY SELECT
                false,
                recovery_case.id,
                recovery_case.target_native_identity_id,
                recovery_case.status,
                recovery_case.delivery_status,
                recovery_case.revision,
                v_reserved,
                recovery_case.approval_expires_at,
                recovery_case.proof_expires_at,
                recovery_case.created_at,
                recovery_case.approved_at,
                recovery_case.issued_at,
                recovery_case.consumed_at,
                recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_PREPARE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_PREPARE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_PREPARE_FUNCTION} TO request_platform_control;
        """
    )

    # 4. Issue only proceeds for the exact reserved generation and key, and
    # releases the reservation once the case is durably issued.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION request_platform.issue_identity_recovery_case(
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
                    recovery_case.revoked_at
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
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id
                   AND reservation.generation = p_generation
                   AND reservation.idempotency_key_digest = p_idempotency_key_digest
            ) THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is not reserved'
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
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id
                   AND reservation.generation = p_generation
                   AND reservation.idempotency_key_digest = p_idempotency_key_digest
            ) THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is not reserved'
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
            DELETE FROM request_engine.identity_recovery_issuance_reservations AS reservation
             WHERE reservation.case_id = p_case_id
               AND reservation.generation = p_generation;
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
                recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $function$;
        ALTER FUNCTION {_ISSUE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_ISSUE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_ISSUE_FUNCTION} TO request_platform_control;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove recovery issuance reservation; roll forward")
