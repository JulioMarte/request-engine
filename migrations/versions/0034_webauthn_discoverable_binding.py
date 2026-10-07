"""Bind discoverable assertions to the configured authority and issued user handle."""

from __future__ import annotations

import hashlib

from alembic import op
from sqlalchemy import text

revision: str = "0034_webauthn_discoverable_binding"
down_revision: str | None = "0033_adopt_fact_tenant_rls"
branch_labels: str | None = None
depends_on: str | None = None

_NATIVE_HANDLE_PREFIX = b"request-engine:native:"
_SETUP_HANDLE_PREFIX = b"request-engine:setup:"


def _definition(signature: str) -> str:
    value = op.get_bind().execute(
        text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
        {"signature": signature},
    ).scalar_one()
    return str(value)


def _replace_function_text(signature: str, old: str, new: str) -> None:
    definition = _definition(signature)
    if old not in definition:
        raise RuntimeError(f"Migration anchor missing in {signature}")
    op.get_bind().exec_driver_sql(definition.replace(old, new, 1))


def _backfill_user_handles() -> None:
    bind = op.get_bind()
    pending_rows = bind.execute(
        text(
            "SELECT id, setup_session_id FROM request_engine.setup_pending_webauthn_credential "
            "WHERE user_handle IS NULL"
        )
    ).all()
    for row in pending_rows:
        handle = hashlib.sha256(_SETUP_HANDLE_PREFIX + row.setup_session_id.bytes).digest()
        bind.execute(
            text(
                "UPDATE request_engine.setup_pending_webauthn_credential "
                "SET user_handle=:handle WHERE id=:credential_id"
            ),
            {"handle": handle, "credential_id": row.id},
        )

    credential_rows = bind.execute(
        text(
            "SELECT credential.id, credential.native_identity_id, setup.setup_session_id "
            "FROM request_engine.webauthn_credentials AS credential "
            "LEFT JOIN request_engine.setup_pending_webauthn_credential AS setup "
            "  ON setup.credential_id=credential.credential_id AND setup.status='promoted' "
            "WHERE credential.user_handle IS NULL"
        )
    ).all()
    for row in credential_rows:
        if row.setup_session_id is not None:
            source = _SETUP_HANDLE_PREFIX + row.setup_session_id.bytes
        else:
            source = _NATIVE_HANDLE_PREFIX + row.native_identity_id.bytes
        bind.execute(
            text(
                "UPDATE request_engine.webauthn_credentials SET user_handle=:handle "
                "WHERE id=:credential_id"
            ),
            {"handle": hashlib.sha256(source).digest(), "credential_id": row.id},
        )


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE request_engine.webauthn_challenges
            ADD COLUMN user_handle bytea;
        ALTER TABLE request_engine.webauthn_credentials
            ADD COLUMN user_handle bytea;
        ALTER TABLE request_engine.setup_pending_webauthn_credential
            ADD COLUMN user_handle bytea;
        """
    )
    _backfill_user_handles()
    op.execute(
        """
        ALTER TABLE request_engine.webauthn_challenges
            ADD CONSTRAINT webauthn_challenge_user_handle_length_ck
            CHECK (user_handle IS NULL OR octet_length(user_handle) BETWEEN 16 AND 64);
        ALTER TABLE request_engine.webauthn_credentials
            ADD CONSTRAINT webauthn_credential_user_handle_length_ck
            CHECK (user_handle IS NULL OR octet_length(user_handle) BETWEEN 16 AND 64);
        ALTER TABLE request_engine.setup_pending_webauthn_credential
            ADD CONSTRAINT setup_pending_webauthn_user_handle_length_ck
            CHECK (user_handle IS NULL OR octet_length(user_handle) BETWEEN 16 AND 64);

        -- Old registration challenges did not preserve the user handle emitted
        -- to the authenticator. They cannot be completed under the new protocol.
        UPDATE request_engine.webauthn_challenges
           SET status='expired'
         WHERE purpose='registration' AND status='pending' AND user_handle IS NULL;

        CREATE FUNCTION request_auth.create_webauthn_challenge_with_user_handle(
            p_challenge_id uuid,p_purpose text,p_native_identity_id uuid,p_session_id uuid,
            p_setup_session_id uuid,p_challenge_digest bytea,p_expires_at timestamptz,
            p_user_handle bytea)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine AS $$
        DECLARE v_scope_count integer;
        BEGIN
            v_scope_count := (p_native_identity_id IS NOT NULL)::int
                + (p_session_id IS NOT NULL)::int
                + (p_setup_session_id IS NOT NULL)::int;
            IF p_challenge_id IS NULL OR p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest)<>32
               OR p_purpose NOT IN ('registration','authentication','step_up',
                                    'authentication_discoverable')
               OR p_expires_at<=clock_timestamp()
               OR (p_purpose='authentication_discoverable' AND v_scope_count<>0)
               OR (p_purpose<>'authentication_discoverable' AND v_scope_count<>1)
               OR (p_purpose='registration' AND
                   (p_user_handle IS NULL OR octet_length(p_user_handle) NOT BETWEEN 16 AND 64))
               OR (p_purpose<>'registration' AND p_user_handle IS NOT NULL)
            THEN RETURN false; END IF;

            PERFORM pg_advisory_xact_lock(hashtextextended(
                coalesce(p_purpose,'')||'|'||coalesce(p_native_identity_id::text,'')||'|'
                ||coalesce(p_session_id::text,'')||'|'||coalesce(p_setup_session_id::text,''),0));
            IF p_purpose<>'authentication_discoverable' THEN
                UPDATE request_engine.webauthn_challenges SET status='expired'
                 WHERE status='pending' AND purpose=p_purpose
                   AND native_identity_id IS NOT DISTINCT FROM p_native_identity_id
                   AND session_id IS NOT DISTINCT FROM p_session_id
                   AND setup_session_id IS NOT DISTINCT FROM p_setup_session_id;
            END IF;
            INSERT INTO request_engine.webauthn_challenges(
                id,purpose,native_identity_id,session_id,setup_session_id,
                challenge_digest,expires_at,user_handle)
            VALUES(p_challenge_id,p_purpose,p_native_identity_id,p_session_id,
                p_setup_session_id,p_challenge_digest,p_expires_at,p_user_handle);
            RETURN true;
        END $$;
        ALTER FUNCTION request_auth.create_webauthn_challenge_with_user_handle(
            uuid,text,uuid,uuid,uuid,bytea,timestamptz,bytea)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.create_webauthn_challenge_with_user_handle(
            uuid,text,uuid,uuid,uuid,bytea,timestamptz,bytea) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.create_webauthn_challenge_with_user_handle(
            uuid,text,uuid,uuid,uuid,bytea,timestamptz,bytea) TO request_engine_app;
        REVOKE EXECUTE ON FUNCTION request_auth.create_webauthn_challenge(
            uuid,text,uuid,uuid,uuid,bytea,timestamptz) FROM PUBLIC,request_engine_app;

        CREATE FUNCTION request_auth.read_webauthn_credential_for_assertion(
            p_credential_id_bytes bytea)
        RETURNS TABLE(id uuid,native_identity_id uuid,credential_id bytea,public_key bytea,
            sign_count bigint,aaguid text,backup_eligible boolean,backup_state boolean,
            user_verified boolean,status text,user_handle bytea)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,request_engine AS $$
            SELECT c.id,c.native_identity_id,c.credential_id,c.public_key,c.sign_count,
                   c.aaguid,c.backup_eligible,c.backup_state,c.user_verified,c.status,c.user_handle
              FROM request_engine.webauthn_credentials c
             WHERE c.credential_id=p_credential_id_bytes
        $$;
        ALTER FUNCTION request_auth.read_webauthn_credential_for_assertion(bytea)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_webauthn_credential_for_assertion(bytea)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_webauthn_credential_for_assertion(bytea)
            TO request_engine_app;

        CREATE FUNCTION request_auth.fill_claimed_webauthn_user_handle()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine AS $$
        DECLARE v_handle bytea;
        BEGIN
            SELECT pending.user_handle INTO v_handle
              FROM request_engine.setup_pending_webauthn_credential pending
             WHERE pending.credential_id=NEW.credential_id
               AND pending.status IN ('pending','promoted')
             ORDER BY pending.created_at DESC LIMIT 1;
            IF FOUND THEN
                IF NEW.user_handle IS NOT NULL AND NEW.user_handle IS DISTINCT FROM v_handle THEN
                    RAISE EXCEPTION 'Claimed WebAuthn user handle provenance mismatch'
                        USING ERRCODE='23514';
                END IF;
                NEW.user_handle:=v_handle;
            END IF;
            RETURN NEW;
        END $$;
        ALTER FUNCTION request_auth.fill_claimed_webauthn_user_handle()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.fill_claimed_webauthn_user_handle() FROM PUBLIC;
        CREATE TRIGGER fill_claimed_webauthn_user_handle
            BEFORE INSERT ON request_engine.webauthn_credentials
            FOR EACH ROW EXECUTE FUNCTION request_auth.fill_claimed_webauthn_user_handle();
        """
    )

    _replace_function_text(
        "request_auth.finalize_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean)",
        "IF NOT FOUND OR v_challenge.native_identity_id IS NULL THEN\n                 RETURN false;\n             END IF;",
        "IF NOT FOUND OR v_challenge.native_identity_id IS NULL\n                OR v_challenge.user_handle IS NULL THEN\n                 RETURN false;\n             END IF;",
    )
    _replace_function_text(
        "request_auth.finalize_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean)",
        "p_credential_row_id, v_challenge.native_identity_id,\n                 p_credential_id_bytes, p_public_key, p_sign_count, p_aaguid,\n                 p_backup_eligible, p_backup_state, p_user_verified",
        "p_credential_row_id, v_challenge.native_identity_id,\n                 p_credential_id_bytes, p_public_key, p_sign_count, p_aaguid,\n                 p_backup_eligible, p_backup_state, p_user_verified, v_challenge.user_handle",
    )
    _replace_function_text(
        "request_auth.finalize_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean)",
        "aaguid, backup_eligible, backup_state, user_verified\n             ) VALUES (",
        "aaguid, backup_eligible, backup_state, user_verified, user_handle\n             ) VALUES (",
    )
    _replace_function_text(
        "request_auth.finalize_setup_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean,uuid)",
        "OR v_challenge.setup_session_id <> p_setup_session_id\n             THEN",
        "OR v_challenge.setup_session_id <> p_setup_session_id\n                OR v_challenge.user_handle IS NULL\n             THEN",
    )
    _replace_function_text(
        "request_auth.finalize_setup_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean,uuid)",
        "aaguid, backup_eligible, backup_state, user_verified\n             ) VALUES (",
        "aaguid, backup_eligible, backup_state, user_verified, user_handle\n             ) VALUES (",
    )
    _replace_function_text(
        "request_auth.finalize_setup_webauthn_registration(bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean,uuid)",
        "p_public_key, p_sign_count, p_aaguid, p_backup_eligible,\n                 p_backup_state, p_user_verified\n             )",
        "p_public_key, p_sign_count, p_aaguid, p_backup_eligible,\n                 p_backup_state, p_user_verified, v_challenge.user_handle\n             )",
    )

    op.execute(
        """
        CREATE FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
            p_challenge_digest bytea,p_credential_row_id uuid,p_sign_count bigint,
            p_backup_eligible boolean,p_backup_state boolean,p_user_verified boolean,
            p_session_id uuid,p_token_digest bytea,p_token_fingerprint text,
            p_expires_at timestamptz,p_expected_authority_id uuid,p_user_handle bytea)
        RETURNS TABLE(native_identity_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_identity uuid;
            v_epoch bigint;
            v_identity_status text;
            v_credential_identity uuid;
            v_credential_status text;
            v_credential_handle bytea;
        BEGIN
            IF p_challenge_digest IS NULL OR octet_length(p_challenge_digest)<>32
               OR p_credential_row_id IS NULL OR p_sign_count<0 OR p_session_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest)<>32
               OR p_token_fingerprint IS NULL OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL OR p_expected_authority_id IS NULL
               OR p_user_handle IS NULL OR octet_length(p_user_handle) NOT BETWEEN 16 AND 64
            THEN RETURN; END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges challenge
             WHERE challenge.challenge_digest=p_challenge_digest
               AND challenge.purpose='authentication_discoverable'
               AND challenge.status='pending'
               AND challenge.expires_at>clock_timestamp()
               AND challenge.native_identity_id IS NULL
               AND challenge.session_id IS NULL
               AND challenge.setup_session_id IS NULL
             FOR UPDATE;
            IF NOT FOUND THEN RETURN; END IF;

            SELECT credential.native_identity_id INTO v_identity
              FROM request_engine.webauthn_credentials credential
             WHERE credential.id=p_credential_row_id;
            IF NOT FOUND OR v_identity IS NULL THEN RETURN; END IF;

            PERFORM 1
              FROM request_engine.identity_authorities authority
              JOIN request_engine.native_identities identity
                ON identity.identity_authority_id=authority.id
             WHERE identity.id=v_identity AND authority.id=p_expected_authority_id
               AND authority.kind='native' AND authority.status='active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN; END IF;

            SELECT session_epoch,status INTO v_epoch,v_identity_status
              FROM request_engine.native_identities WHERE id=v_identity FOR UPDATE;
            IF NOT FOUND OR v_identity_status<>'active' THEN RETURN; END IF;

            SELECT credential.native_identity_id,credential.status,credential.user_handle
              INTO v_credential_identity,v_credential_status,v_credential_handle
              FROM request_engine.webauthn_credentials credential
             WHERE credential.id=p_credential_row_id FOR UPDATE;
            IF NOT FOUND OR v_credential_status<>'active'
               OR v_credential_identity<>v_identity
               OR v_credential_handle IS DISTINCT FROM p_user_handle
            THEN RETURN; END IF;

            -- Expiry governs durable session creation, not merely entry into the
            -- finalizer. The challenge row and every identity/credential lock are
            -- held now, so this is the final admission check before any write.
            IF v_challenge.expires_at<=clock_timestamp()
               OR p_expires_at<=clock_timestamp() THEN RETURN; END IF;

            UPDATE request_engine.webauthn_credentials
               SET sign_count=GREATEST(sign_count,p_sign_count),
                   last_used_at=clock_timestamp(),backup_state=p_backup_state,
                   user_verified=user_verified OR p_user_verified,
                   last_regression_at=CASE
                       WHEN NOT p_backup_eligible AND p_sign_count>0 AND sign_count>0
                            AND p_sign_count<sign_count
                       THEN clock_timestamp() ELSE last_regression_at END
             WHERE id=p_credential_row_id;

            INSERT INTO request_engine.native_sessions(
                id,native_identity_id,password_credential_id,webauthn_credential_id,
                token_digest,token_fingerprint,session_epoch,expires_at,
                authentication_methods,authentication_assurance,user_verified,recovery_derived)
            VALUES(p_session_id,v_identity,NULL,p_credential_row_id,p_token_digest,
                p_token_fingerprint,v_epoch,p_expires_at,ARRAY['webauthn']::text[],
                request_engine.derive_authentication_assurance(
                    ARRAY['webauthn']::text[],p_user_verified,false),p_user_verified,false);

            UPDATE request_engine.webauthn_challenges
               SET status='consumed',consumed_at=clock_timestamp() WHERE id=v_challenge.id;
            RETURN QUERY SELECT v_identity;
        END $$;
        ALTER FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
            bytea,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz,uuid,bytea)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
            bytea,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz,uuid,bytea)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
            bytea,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz,uuid,bytea)
            TO request_engine_app;
        REVOKE EXECUTE ON FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
            bytea,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz)
            FROM PUBLIC,request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("WebAuthn identity/authority binding is roll-forward only")
