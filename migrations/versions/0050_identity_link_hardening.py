"""Identity-link hardening: intent-derived authority, one live intent, activity.

Re-emits the controller-continuity assertions so a missing controller surfaces as
``55000`` (a mapped conflict) instead of ``23514`` (a mapped input error), adds a
partial unique index that permits at most one live pending link intent per
actor+authority, expires stale pending intents before the create-time existence
check, and exposes a tenant-scoped reader for the persisted intent so the confirm
boundary can derive the target authority from trusted state instead of a
body-supplied hint.

Also adds ``request_auth.touch_native_session`` so a validated session can record
bounded activity without exposing native session tables to the app role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050_identity_link_hardening"
down_revision: str | Sequence[str] | None = "0049_identity_link_self"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.assert_organization_has_controller(
            p_organization_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       p_organization_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;
        ALTER FUNCTION request_engine.assert_organization_has_controller(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_organization_has_controller(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.assert_organization_has_controller(uuid)
            TO request_platform_control_definer;

        CREATE OR REPLACE FUNCTION request_platform.assert_platform_has_controller()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT principal.id
              INTO v_candidate
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
               AND request_platform.principal_is_effective_platform_controller(
                       principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective controller'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;
        ALTER FUNCTION request_platform.assert_platform_has_controller()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_platform_has_controller()
            FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX identity_link_intents_live_uq
            ON request_engine.identity_link_intents
            (organization_id, actor_principal_id, target_authority_id)
            WHERE status = 'pending';
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.create_identity_link_intent(
            p_intent_id uuid,
            p_actor_binding_id uuid,
            p_target_authority_id uuid,
            p_nonce_digest text,
            p_ttl_seconds integer,
            p_provenance_reference text
        ) RETURNS TABLE (
            intent_id uuid,
            expires_at timestamp with time zone,
            target_authority_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_expires_at timestamptz;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL
               OR p_actor_binding_id IS NULL
               OR p_target_authority_id IS NULL THEN
                RAISE EXCEPTION 'Identity link intent identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_ttl_seconds IS NULL OR p_ttl_seconds < 60 OR p_ttl_seconds > 900 THEN
                RAISE EXCEPTION 'Identity link intent TTL must be between 60 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;
            IF p_nonce_digest IS NULL OR p_nonce_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity link intent nonce digest is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link intent provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings
             WHERE id = p_actor_binding_id
               AND organization_id = v_org_id
               AND principal_id = v_actor_id
               AND principal_plane = 'tenant'
               AND status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active actor identity binding not found'
                    USING ERRCODE = 'P0002';
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_target_authority_id
               AND status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Target identity authority is not active'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.identity_link_intents AS intent
               SET status = 'expired'
             WHERE intent.organization_id = v_org_id
               AND intent.actor_principal_id = v_actor_id
               AND intent.status = 'pending'
               AND intent.expires_at <= clock_timestamp();

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_link_intents AS intent
                 WHERE intent.actor_principal_id = v_actor_id
                   AND intent.target_authority_id = p_target_authority_id
                   AND intent.status = 'pending'
                   AND intent.expires_at > clock_timestamp()
            ) THEN
                RAISE EXCEPTION 'A live Identity link intent already exists for this authority'
                    USING ERRCODE = '23505';
            END IF;

            v_expires_at := clock_timestamp()
                + make_interval(secs => p_ttl_seconds);
            INSERT INTO request_engine.identity_link_intents (
                id, organization_id, actor_principal_id, actor_binding_id,
                target_authority_id, actor_binding_revision, nonce_digest,
                status, expires_at, provenance_reference
            ) VALUES (
                p_intent_id, v_org_id, v_actor_id, p_actor_binding_id,
                p_target_authority_id, v_binding.revision, p_nonce_digest,
                'pending', v_expires_at, btrim(p_provenance_reference)
            );

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, nonce_digest,
                provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'intent_created',
                p_intent_id, p_target_authority_id, p_nonce_digest,
                btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_intent_id, v_expires_at, p_target_authority_id;
        END
        $$;
        ALTER FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_engine.read_identity_link_intent(p_intent_id uuid)
        RETURNS TABLE (
            intent_id uuid,
            actor_principal_id uuid,
            target_authority_id uuid,
            target_authority_kind text,
            actor_binding_revision bigint,
            status text,
            expires_at timestamp with time zone
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT i.id,
                   i.actor_principal_id,
                   i.target_authority_id,
                   a.kind,
                   i.actor_binding_revision,
                   i.status,
                   i.expires_at
              FROM request_engine.identity_link_intents AS i
              JOIN request_engine.identity_authorities AS a
                ON a.id = i.target_authority_id
             WHERE i.id = p_intent_id
               AND i.organization_id = request_engine.current_organization_id()
        $$;
        ALTER FUNCTION request_engine.read_identity_link_intent(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.read_identity_link_intent(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.read_identity_link_intent(uuid)
            TO request_engine_app;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_auth.touch_native_session(
            p_session_id uuid,
            p_min_interval_seconds integer
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_updated boolean;
        BEGIN
            IF p_session_id IS NULL THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_sessions
               SET last_seen_at = clock_timestamp()
             WHERE id = p_session_id
               AND status = 'active'
               AND (last_seen_at IS NULL
                    OR last_seen_at < clock_timestamp()
                       - make_interval(secs => GREATEST(p_min_interval_seconds, 0)))
             RETURNING true INTO v_updated;
            RETURN COALESCE(v_updated, false);
        END
        $$;
        ALTER FUNCTION request_auth.touch_native_session(uuid, integer)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.touch_native_session(uuid, integer)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.touch_native_session(uuid, integer)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove identity-link hardening; roll forward")
