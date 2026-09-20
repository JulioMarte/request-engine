"""Recover abandoned governed identity-recovery delivery leases.

Revision ID: 0079_recovery_delivery_reclaim
Revises: 0078_native_recovery_delivery

The governed identity-recovery delivery worker originally claimed only pending
tickets and allowed heartbeat renewal after lease expiry. A worker crash could
therefore strand a ticket in sending forever, and a late worker could resurrect
stale ownership. Reclaim expired leases under a fresh fencing token, terminalize
expired/exhausted abandoned tickets, and reject late renewal.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0079_recovery_delivery_reclaim"
down_revision: str | Sequence[str] | None = "0078_native_recovery_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.claim_identity_recovery_delivery_tickets(
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
        DECLARE
            v_terminal record;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Delivery ticket claim limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            IF p_lease_seconds IS NULL OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
                RAISE EXCEPTION 'Delivery ticket lease must be between 1 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;

            -- Close abandoned work that can no longer be executed. An active
            -- final attempt is left alone until its lease expires; an expired
            -- proof is terminal immediately because a delivered proof would no
            -- longer be consumable.
            FOR v_terminal IN
                SELECT ticket.id,
                       ticket.case_id,
                       CASE
                           WHEN ticket.expires_at <= clock_timestamp()
                           THEN 'proof_expired'
                           ELSE 'attempts_exhausted'
                       END AS error_class
                  FROM request_engine.identity_recovery_delivery_tickets AS ticket
                  JOIN request_engine.identity_recovery_cases AS recovery_case
                    ON recovery_case.id = ticket.case_id
                 WHERE recovery_case.status = 'issued'
                   AND ticket.status IN ('pending', 'sending')
                   AND (
                       ticket.expires_at <= clock_timestamp()
                       OR (
                           ticket.attempt_count >= ticket.max_attempts
                           AND (
                               ticket.status = 'pending'
                               OR ticket.lease_until <= clock_timestamp()
                           )
                       )
                   )
                 ORDER BY ticket.id
                 FOR UPDATE OF ticket SKIP LOCKED
            LOOP
                UPDATE request_engine.identity_recovery_delivery_tickets AS ticket
                   SET status = 'failed',
                       claim_token = NULL,
                       lease_until = NULL,
                       last_error_class = v_terminal.error_class,
                       updated_at = clock_timestamp()
                 WHERE ticket.id = v_terminal.id;

                UPDATE request_engine.identity_recovery_cases AS recovery_case
                   SET delivery_status = 'failed',
                       revision = recovery_case.revision + 1,
                       updated_at = clock_timestamp()
                 WHERE recovery_case.id = v_terminal.case_id
                   AND recovery_case.status = 'issued'
                   AND recovery_case.delivery_status IN ('pending', 'sending')
                RETURNING recovery_case.revision - 1, recovery_case.revision
                     INTO v_revision_before, v_revision_after;

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
                        v_terminal.case_id,
                        'delivery_failed',
                        NULL,
                        NULL,
                        v_terminal.error_class,
                        NULL,
                        v_revision_before,
                        v_revision_after,
                        NULL,
                        'platform.identity.recovery_delivery',
                        NULL,
                        NULL
                    );
                END IF;
            END LOOP;

            RETURN QUERY
            WITH candidate AS (
                SELECT ticket.id,
                       CASE
                           WHEN ticket.status = 'pending' THEN ticket.next_attempt_at
                           ELSE ticket.lease_until
                       END AS due_at
                  FROM request_engine.identity_recovery_delivery_tickets AS ticket
                  JOIN request_engine.identity_recovery_cases AS recovery_case
                    ON recovery_case.id = ticket.case_id
                 WHERE (
                           (
                               ticket.status = 'pending'
                               AND ticket.next_attempt_at <= clock_timestamp()
                           )
                           OR (
                               ticket.status = 'sending'
                               AND ticket.lease_until <= clock_timestamp()
                           )
                       )
                   AND ticket.expires_at > clock_timestamp()
                   AND ticket.attempt_count < ticket.max_attempts
                   AND recovery_case.status = 'issued'
                 ORDER BY due_at, ticket.id
                 LIMIT p_limit
                 FOR UPDATE OF ticket SKIP LOCKED
            )
            UPDATE request_engine.identity_recovery_delivery_tickets AS ticket
               SET status = 'sending',
                   claim_token = uuidv7(),
                   lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
                   attempt_count = ticket.attempt_count + 1,
                   last_error_class = CASE
                       WHEN ticket.status = 'sending' THEN 'lease_expired'
                       ELSE ticket.last_error_class
                   END,
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

        ALTER FUNCTION request_platform.claim_identity_recovery_delivery_tickets(
            integer, integer
        ) OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION
            request_platform.claim_identity_recovery_delivery_tickets(integer, integer)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_platform.claim_identity_recovery_delivery_tickets(integer, integer)
            TO request_engine_worker;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION
        request_platform.renew_identity_recovery_delivery_ticket_lease(
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
               SET lease_until = lease_until
                   + make_interval(secs => p_extension_seconds),
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending'
               AND lease_until > clock_timestamp();

            RETURN FOUND;
        END
        $function$;

        ALTER FUNCTION
            request_platform.renew_identity_recovery_delivery_ticket_lease(
                uuid, uuid, integer
            ) OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION
            request_platform.renew_identity_recovery_delivery_ticket_lease(
                uuid, uuid, integer
            ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_platform.renew_identity_recovery_delivery_ticket_lease(
                uuid, uuid, integer
            ) TO request_engine_worker;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Governed recovery delivery fencing is roll-forward only")
