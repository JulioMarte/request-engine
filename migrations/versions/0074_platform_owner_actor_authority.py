"""Align Platform Owner authority proof and invitation replay privileges.

Revision ID: 0074_owner_actor_auth
Revises: 0073_platform_owner_compat

0073 moved invitation activation/revocation onto the owner-specific actor
assertion and narrowed invitation reads to explicit columns. The revocation
writer also performs an idempotency replay lookup in the append-only invitation
facts table, but the control definer had INSERT-only access to that table. Under
its SECURITY DEFINER role the replay SELECT therefore failed with
insufficient_privilege and surfaced at HTTP as ``platform_owner_forbidden``.

This revision grants only the fact columns needed by that replay lookup. It also
keeps the owner actor assertion aligned with the canonical capability decision:
an active platform HUMAN at the current authority revision with an active exact
capability grant. No table-wide SELECT or broader application-role privilege is
introduced.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_owner_actor_auth"
down_revision: str | Sequence[str] | None = "0073_platform_owner_compat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        -- revoke_platform_owner_invitation performs an idempotency replay lookup
        -- before mutating the invitation. Keep that read column-scoped: the
        -- definer does not need table-wide SELECT on the append-only fact ledger.
        GRANT SELECT (
            actor_principal_id,
            action,
            idempotency_key_digest,
            intent_digest,
            revision_after
        )
        ON request_engine.platform_owner_invitation_facts
        TO request_platform_control_definer;

        CREATE OR REPLACE FUNCTION request_platform.assert_platform_owner_actor(
            p_capability text
        )
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
                'platform.owner.provision',
                'platform.owner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Unknown Platform Owner capability'
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
                RAISE EXCEPTION 'Current Platform Principal cannot administer owners'
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
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks Platform Owner authority'
                    USING ERRCODE = '42501';
            END IF;

            RETURN QUERY SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $function$;

        ALTER FUNCTION request_platform.assert_platform_owner_actor(text)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_platform_owner_actor(text)
            FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Platform Owner authority history is append-preserving; roll forward")
