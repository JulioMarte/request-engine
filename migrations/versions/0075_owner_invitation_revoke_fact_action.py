"""Align Platform Owner invitation revocation facts with the canonical action vocabulary.

Revision ID: 0075_owner_invitation_revoke_fact_action
Revises: 0074_platform_owner_actor_authority

0072 defined invitation fact actions as past-tense domain events
(`issued`, `enrolled`, `revoked`, `activated`). 0073 accidentally rewrote the
revocation function to persist `revoke`, which violates the table CHECK after
the authorization path succeeds. Keep the schema vocabulary authoritative and
repair the writer/replay lookup instead of weakening the constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075_owner_invitation_revoke_fact_action"
down_revision: str | Sequence[str] | None = "0074_platform_owner_actor_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.revoke_platform_owner_invitation(
            p_invitation_id uuid,
            p_reason_code text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_correlation_id uuid;
            v_invitation record;
            v_replay record;
            v_revision_before bigint;
        BEGIN
            SELECT actor_id, correlation_id
              INTO v_actor_id, v_correlation_id
              FROM request_platform.assert_platform_owner_actor(
                  'platform.owner.provision'
              );

            IF p_invitation_id IS NULL
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner invitation revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT fact.revision_after, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_owner_invitation_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'revoked'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another revocation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_replay.revision_after;
            END IF;

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.native_identity_id
              INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner invitation does not exist'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'consumed' THEN
                RAISE EXCEPTION 'Activated Platform Owner invitation cannot be revoked'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'revoked' THEN
                RETURN v_invitation.revision;
            END IF;

            v_revision_before := v_invitation.revision;
            UPDATE request_engine.platform_owner_invitations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = v_invitation.id
            RETURNING revision INTO v_invitation.revision;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                revision_before, revision_after, correlation_id, reason_code,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_invitation.id, 'revoked', v_actor_id, v_invitation.native_identity_id,
                v_revision_before, v_invitation.revision, v_correlation_id,
                btrim(p_reason_code), p_idempotency_key_digest, p_intent_digest
            );
            RETURN v_invitation.revision;
        END
        $function$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("0075 is a forward-only current-product repair")
