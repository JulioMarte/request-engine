"""Bind controller-policy consent and apply to current native recovery posture."""

from alembic import op
from sqlalchemy import text

revision: str = "0035_adoption_recovery"
down_revision: str | None = "0034_webauthn_binding"
branch_labels: str | None = None
depends_on: str | None = None


def _function_definition(signature: str) -> str:
    result = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    return str(result)


def _replace_function_text(signature: str, old: str, new: str) -> None:
    definition = _function_definition(signature)
    if old not in definition:
        raise RuntimeError(f"Migration anchor missing in {signature}")
    op.get_bind().exec_driver_sql(definition.replace(old, new, 1).replace("%", "%%"))


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE request_engine.controller_policy_adoption_requests
            ADD COLUMN controller_native_identity_id uuid
                REFERENCES request_engine.native_identities(id),
            ADD COLUMN controller_recovery_epoch bigint;
        ALTER TABLE request_engine.controller_policy_adoption_facts
            ADD COLUMN controller_native_identity_id uuid
                REFERENCES request_engine.native_identities(id),
            ADD COLUMN controller_recovery_epoch bigint;

        -- A legacy pending request contains no proof of the native account's
        -- recovery posture at consent time. Expire it rather than invent a snapshot.
        UPDATE request_engine.controller_policy_adoption_requests
           SET status='expired',closed_at=clock_timestamp(),revision=revision+1
         WHERE status='pending';

        ALTER TABLE request_engine.controller_policy_adoption_requests
            ADD CONSTRAINT controller_policy_adoption_request_recovery_snapshot_ck
            CHECK ((controller_native_identity_id IS NULL) =
                       (controller_recovery_epoch IS NULL)
                   AND (status<>'pending' OR controller_native_identity_id IS NOT NULL)
                   AND (controller_recovery_epoch IS NULL OR controller_recovery_epoch>=0));
        ALTER TABLE request_engine.controller_policy_adoption_facts
            ADD CONSTRAINT controller_policy_adoption_fact_recovery_snapshot_ck
            CHECK ((controller_native_identity_id IS NULL) =
                       (controller_recovery_epoch IS NULL)
                   AND (controller_recovery_epoch IS NULL OR controller_recovery_epoch>=0));

        CREATE FUNCTION request_auth.lock_native_identity_recovery_postures(
            p_native_identity_ids uuid[])
        RETURNS TABLE(native_identity_id uuid,identity_authority_id uuid,
            identity_status text,recovery_state text,recovery_epoch bigint)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine AS $$
        DECLARE v_requested_count integer;
                v_identity_count integer;
        BEGIN
            IF p_native_identity_ids IS NULL OR cardinality(p_native_identity_ids)<1
               OR cardinality(p_native_identity_ids)>2
               OR array_position(p_native_identity_ids,NULL) IS NOT NULL
            THEN RAISE EXCEPTION 'Invalid native identity lock set' USING ERRCODE='22023'; END IF;
            SELECT count(DISTINCT id)::integer INTO v_requested_count
              FROM unnest(p_native_identity_ids) AS requested(id);

            -- Canonical account lock order: active native authority UUID, then
            -- native identity UUID, then recovery-state UUID. Recovery writers use
            -- authority -> identity -> posture too; completion uses authority -> posture.
            PERFORM authority.id
              FROM request_engine.identity_authorities authority
              JOIN request_engine.native_identities identity
                ON identity.identity_authority_id=authority.id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY authority.id FOR SHARE OF authority;

            PERFORM identity.id
              FROM request_engine.native_identities identity
              JOIN request_engine.identity_authorities authority
                ON authority.id=identity.identity_authority_id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY identity.id FOR UPDATE OF identity;
            GET DIAGNOSTICS v_identity_count=ROW_COUNT;
            IF v_identity_count<>v_requested_count THEN RETURN; END IF;

            PERFORM recovery.native_identity_id
              FROM request_engine.native_identity_recovery_state recovery
             WHERE recovery.native_identity_id=ANY(p_native_identity_ids)
             ORDER BY recovery.native_identity_id FOR SHARE OF recovery;

            RETURN QUERY
            SELECT identity.id,authority.id,identity.status,
                   coalesce(recovery.state,'normal'),coalesce(recovery.recovery_epoch,0)
              FROM request_engine.native_identities identity
              JOIN request_engine.identity_authorities authority
                ON authority.id=identity.identity_authority_id
              LEFT JOIN request_engine.native_identity_recovery_state recovery
                ON recovery.native_identity_id=identity.id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY identity.id;
        END $$;
        ALTER FUNCTION request_auth.lock_native_identity_recovery_postures(uuid[])
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.lock_native_identity_recovery_postures(uuid[])
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.lock_native_identity_recovery_postures(uuid[])
            TO request_platform_control_definer;

        GRANT SELECT(controller_native_identity_id,controller_recovery_epoch)
            ON request_engine.controller_policy_adoption_requests
            TO request_platform_control_definer;
        GRANT INSERT(controller_native_identity_id,controller_recovery_epoch)
            ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer;
        GRANT SELECT(controller_native_identity_id,controller_recovery_epoch)
            ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer;
        """
    )

    request_signature = (
        "request_cmd.request_controller_policy_adoption(uuid,bigint,text,text,text,uuid)"
    )
    _replace_function_text(
        request_signature,
        "v_expiry timestamptz;",
        "v_expiry timestamptz;\n"
        "            v_identity_authority_id uuid;\n"
        "            v_identity_subject text;\n"
        "            v_native_identity_id uuid;\n"
        "            v_locked_authority_id uuid;\n"
        "            v_identity_status text;\n"
        "            v_recovery_state text;\n"
        "            v_recovery_epoch bigint;",
    )
    _replace_function_text(
        request_signature,
        "END IF;\n"
        "            IF p_expected_authority_revision IS NULL OR p_expected_authority_revision<1",
        "END IF;\n"
        "            SELECT binding.identity_authority_id,binding.subject_id\n"
        "              INTO v_identity_authority_id,v_identity_subject\n"
        "              FROM request_engine.identity_bindings binding\n"
        "             WHERE binding.id=p_binding_id AND binding.principal_id=v_actor\n"
        "               AND binding.organization_id=v_org AND binding.status='active';\n"
        "            IF v_identity_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-"
        "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN\n"
        "                RAISE EXCEPTION 'Active bound native controller is required'\n"
        "                    USING ERRCODE='42501';\n"
        "            END IF;\n"
        "            v_native_identity_id:=v_identity_subject::uuid;\n"
        "            SELECT posture.identity_authority_id,posture.identity_status,\n"
        "                   posture.recovery_state,posture.recovery_epoch\n"
        "              INTO v_locked_authority_id,v_identity_status,\n"
        "                   v_recovery_state,v_recovery_epoch\n"
        "              FROM request_auth.lock_native_identity_recovery_postures(\n"
        "                  ARRAY[v_native_identity_id]) posture\n"
        "             WHERE posture.native_identity_id=v_native_identity_id\n"
        "               AND posture.identity_status='active';\n"
        "            IF NOT FOUND OR v_locked_authority_id IS DISTINCT FROM "
        "v_identity_authority_id\n"
        "               OR v_identity_status<>'active' OR v_recovery_state<>'normal' THEN\n"
        "                RAISE EXCEPTION 'Recovery-restricted controller cannot consent'\n"
        "                    USING ERRCODE='42501';\n"
        "            END IF;\n"
        "            IF p_expected_authority_revision IS NULL OR p_expected_authority_revision<1",
    )
    _replace_function_text(
        request_signature,
        "v_existing.revision,v_existing.status,v_existing.expires_at;",
        "v_existing.revision,\n"
        "                    CASE WHEN v_existing.status='pending'\n"
        "                              AND v_existing.expires_at<=clock_timestamp()\n"
        "                         THEN 'expired' ELSE v_existing.status END,\n"
        "                    v_existing.expires_at;",
    )
    _replace_function_text(
        request_signature,
        "correlation_id,expires_at)",
        "correlation_id,expires_at,controller_native_identity_id,controller_recovery_epoch)",
    )
    _replace_function_text(
        request_signature,
        "p_intent_digest,p_correlation_id,v_expiry);",
        "p_intent_digest,p_correlation_id,v_expiry,v_native_identity_id,v_recovery_epoch);",
    )

    apply_signature = "request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)"
    _replace_function_text(
        apply_signature,
        "v_request record;\n            v_replay record;",
        "v_request record;\n"
        "            v_replay record;\n"
        "            v_root_native_identity_id uuid;\n"
        "            v_actor_native_identity_id uuid;\n"
        "            v_locked_authority_id uuid;\n"
        "            v_identity_status text;\n"
        "            v_actor_recovery_state text;\n"
        "            v_root_recovery_state text;\n"
        "            v_actor_recovery_epoch bigint;\n"
        "            v_root_recovery_epoch bigint;\n"
        "            v_posture_count integer;",
    )
    _replace_function_text(
        apply_signature,
        "r.reason,r.status,r.revision,r.created_at,r.expires_at",
        "r.reason,r.status,r.revision,r.created_at,r.expires_at,\n"
        "                    r.controller_native_identity_id,r.controller_recovery_epoch",
    )
    _replace_function_text(
        apply_signature,
        "RETURN QUERY SELECT v_replay.id,v_replay.request_id,v_replay.organization_id,",
        "v_actor_binding:=NULLIF(current_setting(\n"
        "    'request_engine.identity_binding_id',true),'')::uuid;\n"
        "SELECT b.identity_authority_id,b.subject_id\n"
        "  INTO v_actor_authority,v_actor_subject\n"
        "  FROM request_engine.identity_bindings b\n"
        " WHERE b.id=v_actor_binding AND b.principal_id=v_actor\n"
        "   AND b.principal_plane='platform' AND b.organization_id IS NULL\n"
        "   AND b.status='active' FOR SHARE;\n"
        "IF NOT FOUND THEN\n"
        "    RAISE EXCEPTION 'Bound active Platform identity is required'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "IF v_actor_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-"
        "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN\n"
        "    RAISE EXCEPTION 'Active native Platform identity is required'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "v_actor_native_identity_id:=v_actor_subject::uuid;\n"
        "SELECT posture.identity_authority_id,posture.identity_status,posture.recovery_state\n"
        "  INTO v_locked_authority_id,v_identity_status,v_actor_recovery_state\n"
        "  FROM request_auth.lock_native_identity_recovery_postures(\n"
        "      ARRAY[v_actor_native_identity_id]) posture\n"
        " WHERE posture.native_identity_id=v_actor_native_identity_id\n"
        "   AND posture.identity_status='active';\n"
        "IF NOT FOUND OR v_locked_authority_id IS DISTINCT FROM v_actor_authority\n"
        "   OR v_identity_status<>'active' OR v_actor_recovery_state<>'normal' THEN\n"
        "    RAISE EXCEPTION 'Recovery-restricted approver cannot replay adoption'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "RETURN QUERY SELECT v_replay.id,v_replay.request_id,v_replay.organization_id,",
    )
    _replace_function_text(
        apply_signature,
        "IF NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b",
        "IF v_root_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-"
        "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'\n"
        "   OR v_actor_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-"
        "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN\n"
        "    RAISE EXCEPTION 'Bound native identity reference is invalid'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "v_root_native_identity_id:=v_root_subject::uuid;\n"
        "v_actor_native_identity_id:=v_actor_subject::uuid;\n"
        "IF v_request.controller_native_identity_id IS DISTINCT FROM\n"
        "   v_root_native_identity_id THEN\n"
        "    RAISE EXCEPTION 'Controller native consent provenance changed'\n"
        "        USING ERRCODE='P0010';\n"
        "END IF;\n"
        "SELECT count(*)::integer INTO v_posture_count\n"
        "  FROM request_auth.lock_native_identity_recovery_postures(\n"
        "      ARRAY[v_root_native_identity_id,v_actor_native_identity_id]);\n"
        "IF v_posture_count<>2 THEN\n"
        "    RAISE EXCEPTION 'Active native consent and approver identities are required'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "SELECT posture.identity_authority_id,posture.identity_status,\n"
        "       posture.recovery_state,posture.recovery_epoch\n"
        "  INTO v_locked_authority_id,v_identity_status,\n"
        "       v_root_recovery_state,v_root_recovery_epoch\n"
        "  FROM request_auth.lock_native_identity_recovery_postures(\n"
        "      ARRAY[v_root_native_identity_id,v_actor_native_identity_id]) posture\n"
        " WHERE posture.native_identity_id=v_root_native_identity_id\n"
        "   AND posture.identity_status='active';\n"
        "IF NOT FOUND OR v_locked_authority_id IS DISTINCT FROM v_root_authority\n"
        "   OR v_identity_status<>'active' OR v_root_recovery_state<>'normal'\n"
        "   OR v_root_recovery_epoch IS DISTINCT FROM v_request.controller_recovery_epoch THEN\n"
        "    RAISE EXCEPTION 'Controller recovery invalidated consent' USING ERRCODE='P0010';\n"
        "END IF;\n"
        "SELECT posture.identity_authority_id,posture.identity_status,\n"
        "       posture.recovery_state,posture.recovery_epoch\n"
        "  INTO v_locked_authority_id,v_identity_status,\n"
        "       v_actor_recovery_state,v_actor_recovery_epoch\n"
        "  FROM request_auth.lock_native_identity_recovery_postures(\n"
        "      ARRAY[v_root_native_identity_id,v_actor_native_identity_id]) posture\n"
        " WHERE posture.native_identity_id=v_actor_native_identity_id\n"
        "   AND posture.identity_status='active';\n"
        "IF NOT FOUND OR v_locked_authority_id IS DISTINCT FROM v_actor_authority\n"
        "   OR v_identity_status<>'active' OR v_actor_recovery_state<>'normal' THEN\n"
        "    RAISE EXCEPTION 'Recovery-restricted approver cannot apply adoption'\n"
        "        USING ERRCODE='42501';\n"
        "END IF;\n"
        "IF NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b",
    )
    _replace_function_text(
        apply_signature,
        "platform_authority_revision,correlation_id)",
        "platform_authority_revision,correlation_id,controller_native_identity_id,"
        "controller_recovery_epoch)",
    )
    _replace_function_text(
        apply_signature,
        "NULLIF(current_setting('request_engine.correlation_id',true),'')::uuid)",
        "NULLIF(current_setting('request_engine.correlation_id',true),'')::uuid,"
        "v_root_native_identity_id,v_request.controller_recovery_epoch)",
    )


def downgrade() -> None:
    raise RuntimeError("Adoption recovery consent provenance is roll-forward only")
