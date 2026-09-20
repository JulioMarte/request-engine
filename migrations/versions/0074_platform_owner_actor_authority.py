"""Align Platform Owner database authority proof with canonical capability grants.

Revision ID: 0074_platform_owner_actor_authority
Revises: 0073_platform_owner_compat

The HTTP/application boundary already resolves a PlatformActorContext from active
canonical grants and checks the requested capability. 0073 added a second SQL
assertion for invitation/lifecycle writers, but that assertion additionally
required the grant row's denormalized plane columns to equal ``platform``. The
older invitation-create writer does not add that extra predicate. This made two
operations protected by the same ``platform.owner.provision`` capability disagree:
an owner could create an invitation and then receive 403 while revoking it.

The database assertion still independently proves that the authenticated
principal is an active platform HUMAN, that its authority revision is current,
and that it owns an active exact capability grant. Capability keys are canonical
and the principal itself is constrained to the platform plane, so the redundant
grant-plane predicates are not an authorization boundary and must not make the
SQL writer disagree with the canonical resolver.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_platform_owner_actor_authority"
down_revision: str | Sequence[str] | None = "0073_platform_owner_compat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
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

            -- Keep the SQL proof identical to the canonical capability decision:
            -- active platform HUMAN + current revision + active exact capability.
            -- The capability key itself is canonical; grant-plane metadata is not
            -- an additional authorization dimension for this platform-only actor.
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
