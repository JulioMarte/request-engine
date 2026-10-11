"""Safe, currently authorized Platform Owner and invitation read projections."""

from alembic import op

revision: str = "0014_platform_owner_reads"
down_revision: str | None = "0013_temporary_proof_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION request_platform.assert_owner_read_actor() RETURNS void
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, request_engine, pg_temp AS $$
    DECLARE actor_id uuid; actor_revision bigint;
    BEGIN
        BEGIN
            actor_id := NULLIF(current_setting(
                'request_engine.authenticated_principal_id', true), '')::uuid;
            actor_revision := NULLIF(current_setting(
                'request_engine.authority_revision', true), '')::bigint;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'Malformed platform read actor' USING ERRCODE='28000';
        END;
        IF NOT EXISTS (
            SELECT 1 FROM request_engine.principals p
            JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
            WHERE p.id=actor_id AND p.principal_plane='platform'
              AND p.principal_kind='human' AND p.active
              AND p.authority_revision=actor_revision
              AND g.principal_plane='platform' AND g.authority_plane='platform'
              AND g.status='active' AND g.capability_key='platform.owner.read'
        ) THEN
            RAISE EXCEPTION 'Current owner read authority required' USING ERRCODE='42501';
        END IF;
    END $$;
    ALTER FUNCTION request_platform.assert_owner_read_actor()
        OWNER TO request_platform_control_definer;
    REVOKE ALL ON FUNCTION request_platform.assert_owner_read_actor() FROM PUBLIC;

    CREATE FUNCTION request_platform.read_platform_owners(
        p_principal_id uuid, p_after uuid, p_limit integer
    ) RETURNS TABLE(principal_id uuid, active boolean, authority_revision bigint,
                    binding_id uuid, binding_status text, capabilities text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, request_engine, pg_temp AS $$
    BEGIN
        PERFORM request_platform.assert_owner_read_actor();
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
            RAISE EXCEPTION 'Page limit must be between 1 and 100' USING ERRCODE='22023';
        END IF;
        RETURN QUERY
        SELECT p.id, p.active, p.authority_revision, b.id, b.status,
            ARRAY(SELECT g.capability_key FROM request_engine.principal_authority_grants g
                  WHERE g.principal_id=p.id AND g.principal_plane='platform'
                    AND g.authority_plane='platform' AND g.status='active'
                  ORDER BY g.capability_key)
        FROM request_engine.principals p
        LEFT JOIN LATERAL (
            SELECT binding.id, binding.status FROM request_engine.identity_bindings binding
            WHERE binding.principal_id=p.id AND binding.principal_plane='platform'
            ORDER BY (binding.status='active') DESC, (binding.status='suspended') DESC,
                     binding.id LIMIT 1
        ) b ON true
        WHERE p.principal_plane='platform' AND p.principal_kind='human'
          AND (p_principal_id IS NULL OR p.id=p_principal_id)
          AND (p_after IS NULL OR p.id>p_after)
          AND EXISTS (
            SELECT 1 FROM request_engine.principal_authority_grants historical
            WHERE historical.principal_id=p.id AND historical.principal_plane='platform'
              AND historical.authority_plane='platform'
              AND historical.capability_key='platform.owner.manage_lifecycle'
          )
        ORDER BY p.id LIMIT CASE WHEN p_principal_id IS NULL THEN p_limit+1 ELSE 1 END;
    END $$;
    ALTER FUNCTION request_platform.read_platform_owners(uuid,uuid,integer)
        OWNER TO request_platform_control_definer;
    REVOKE ALL ON FUNCTION request_platform.read_platform_owners(uuid,uuid,integer) FROM PUBLIC;

    CREATE FUNCTION request_platform.read_platform_owner_invitations(
        p_invitation_id uuid, p_after uuid, p_limit integer
    ) RETURNS TABLE(invitation_id uuid, status text, revision bigint, native_identity_id uuid,
                    created_at timestamptz, expires_at timestamptz, enrolled_at timestamptz,
                    consumed_at timestamptz, revoked_at timestamptz, expired boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, request_engine, pg_temp AS $$
    BEGIN
        PERFORM request_platform.assert_owner_read_actor();
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
            RAISE EXCEPTION 'Page limit must be between 1 and 100' USING ERRCODE='22023';
        END IF;
        RETURN QUERY SELECT i.id, i.status, i.revision, i.native_identity_id,
            i.created_at, i.expires_at, i.enrolled_at, i.consumed_at, i.revoked_at,
            i.expires_at<=statement_timestamp()
        FROM request_engine.platform_owner_invitations i
        WHERE (p_invitation_id IS NULL OR i.id=p_invitation_id)
          AND (p_after IS NULL OR i.id>p_after)
        ORDER BY i.id LIMIT CASE WHEN p_invitation_id IS NULL THEN p_limit+1 ELSE 1 END;
    END $$;
    ALTER FUNCTION request_platform.read_platform_owner_invitations(uuid,uuid,integer)
        OWNER TO request_platform_control_definer;
    REVOKE ALL ON FUNCTION request_platform.read_platform_owner_invitations(uuid,uuid,integer)
        FROM PUBLIC;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION request_platform.read_platform_owner_invitations(uuid,uuid,integer)")
    op.execute("DROP FUNCTION request_platform.read_platform_owners(uuid,uuid,integer)")
    op.execute("DROP FUNCTION request_platform.assert_owner_read_actor()")
