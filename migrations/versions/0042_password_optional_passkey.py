"""Password-capable administrative authentication without fabricated assurance."""

from alembic import op
from sqlalchemy import text

revision: str = "0042_password_optional_passkey"
down_revision: str | None = "0041_native_identity_labels"
branch_labels: str | None = None
depends_on: str | None = None


def _replace(signature: str, old: str, new: str) -> None:
    _replace_all(signature, ((old, new),))


def _replace_all(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new in replacements:
        if definition.count(old) != 1:
            raise RuntimeError(f"Missing unique authentication migration anchor: {signature}")
        definition = definition.replace(old, new, 1)
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def upgrade() -> None:
    # Retain the instance/topology locks, pending password, recovery codes,
    # atomic promotion, immutable receipt and permanently closed setup.
    _replace(
        "request_platform.finalize_instance_claim(uuid,text,text,text,text,uuid)",
        """            IF v_verified_count < 1 THEN
                RAISE EXCEPTION 'Setup requires a verified WebAuthn authenticator'
                    USING ERRCODE = '55000';
            END IF;""",
        "            -- A verified passkey is optional; present credentials still promote.",
    )
    _replace(
        "request_platform.native_identity_ready_for_platform_owner(uuid,uuid)",
        """                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = identity.id
                          AND credential.status = 'active'
                          AND credential.user_verified
                   )""",
        """                   AND NOT EXISTS (
                       SELECT 1
                         FROM request_auth.read_native_recovery_readiness(identity.id) recovery
                        WHERE recovery.recovery_state <> 'normal'
                   )""",
    )
    # Read posture through the existing auth projection, without granting the
    # platform-control definer direct access to the recovery-state table.
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_auth.read_native_recovery_readiness(uuid) "
        "TO request_platform_control_definer"
    )
    # Initial credential provenance and recovery-derived status stay immutable.
    # A freshly verified password replaces current proof, never refreshes an old
    # phishing-resistant assertion. Every other upgrade keeps the old guards.
    _replace_all(
        "request_engine.guard_native_session()",
        (
            (
                "            IF NOT "
                "(OLD.authentication_methods <@ NEW.authentication_methods) THEN",
                """            IF NOT (
                NEW.authentication_methods = ARRAY['password']::text[]
                AND NEW.authentication_assurance = 'single_factor'
                AND NOT NEW.user_verified AND NOT NEW.recovery_derived
                AND NEW.last_authenticated_at > OLD.last_authenticated_at
            ) THEN
            IF NOT (OLD.authentication_methods <@ NEW.authentication_methods) THEN""",
            ),
            (
                "            IF NEW.status = OLD.status",
                "            END IF;\n            IF NEW.status = OLD.status",
            ),
        ),
    )
    op.execute(_READERS)
    op.execute("DROP FUNCTION request_auth.reauthenticate_native_session(uuid,uuid)")
    op.execute(_REAUTHENTICATE)
    op.execute(_COMPLETE_RECOVERY)
    for name in (
        "read_native_session_password_credential(uuid)",
        "read_native_recovery_session_password_credential(uuid)",
        "complete_native_recovery_with_password(uuid,uuid,bigint,text)",
        "reauthenticate_native_session(uuid,uuid,text)",
    ):
        op.execute(f"ALTER FUNCTION request_auth.{name} OWNER TO request_engine_schema_owner")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{name} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{name} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Authentication policy evolves forward; roll forward instead")


_READERS = """
CREATE FUNCTION request_auth.read_native_session_password_credential(p_session_id uuid)
RETURNS TABLE(credential_id uuid,native_identity_id uuid,verifier text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path TO pg_catalog,request_engine AS $$
    SELECT credential.id,identity.id,credential.verifier
    FROM request_engine.native_sessions session
    JOIN request_engine.native_identities identity ON identity.id=session.native_identity_id
    JOIN request_engine.identity_authorities authority
      ON authority.id=identity.identity_authority_id
    JOIN request_engine.native_credentials credential ON credential.native_identity_id=identity.id
    LEFT JOIN request_engine.native_identity_recovery_state recovery
      ON recovery.native_identity_id=identity.id
    WHERE session.id=p_session_id AND session.status='active'
      AND session.expires_at>statement_timestamp() AND NOT session.recovery_derived
      AND identity.status='active' AND identity.session_epoch=session.session_epoch
      AND authority.kind='native' AND authority.status='active'
      AND credential.kind='password' AND credential.status='active'
      AND coalesce(recovery.state,'normal')='normal'
      AND (EXISTS(SELECT 1 FROM request_engine.native_credentials initial
           WHERE initial.id=session.password_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active')
        OR EXISTS(SELECT 1 FROM request_engine.webauthn_credentials initial
           WHERE initial.id=session.webauthn_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active'))
$$;
CREATE FUNCTION request_auth.read_native_recovery_session_password_credential(p_session_id uuid)
RETURNS TABLE(credential_id uuid,native_identity_id uuid,verifier text,recovery_epoch bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path TO pg_catalog,request_engine AS $$
    SELECT credential.id,identity.id,credential.verifier,recovery.recovery_epoch
    FROM request_engine.native_sessions session
    JOIN request_engine.native_identities identity ON identity.id=session.native_identity_id
    JOIN request_engine.identity_authorities authority
      ON authority.id=identity.identity_authority_id
    JOIN request_engine.native_credentials credential ON credential.native_identity_id=identity.id
    JOIN request_engine.native_identity_recovery_state recovery
      ON recovery.native_identity_id=identity.id
    WHERE session.id=p_session_id AND session.status='active'
      AND session.expires_at>statement_timestamp()
      AND identity.status='active' AND identity.session_epoch=session.session_epoch
      AND authority.kind='native' AND authority.status='active'
      AND credential.kind='password' AND credential.status='active'
      AND recovery.state='recovery_restricted'
      AND (EXISTS(SELECT 1 FROM request_engine.native_credentials initial
           WHERE initial.id=session.password_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active')
        OR EXISTS(SELECT 1 FROM request_engine.webauthn_credentials initial
           WHERE initial.id=session.webauthn_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active'))
$$;
"""

_REAUTHENTICATE = """
CREATE OR REPLACE FUNCTION request_auth.reauthenticate_native_session(
    p_session_id uuid,p_credential_id uuid,p_expected_verifier text
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO pg_catalog,request_engine AS $$
DECLARE
    v_identity uuid;
    v_epoch bigint;
    v_session request_engine.native_sessions%ROWTYPE;
    v_recovery text;
    v_authenticated timestamptz;
BEGIN
    SELECT * INTO v_session FROM request_engine.native_sessions WHERE id=p_session_id;
    v_identity := v_session.native_identity_id;
    IF NOT FOUND OR p_credential_id IS NULL OR p_expected_verifier IS NULL
      THEN RETURN NULL; END IF;
    PERFORM 1 FROM request_engine.identity_authorities authority
      JOIN request_engine.native_identities identity ON identity.identity_authority_id=authority.id
      WHERE identity.id=v_identity AND authority.kind='native' AND authority.status='active'
      FOR SHARE OF authority;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT session_epoch INTO v_epoch FROM request_engine.native_identities
      WHERE id=v_identity AND status='active' FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    PERFORM 1 FROM request_engine.native_credentials
      WHERE id=p_credential_id AND native_identity_id=v_identity
        AND kind='password' AND status='active' AND verifier=p_expected_verifier FOR SHARE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF v_session.password_credential_id IS NOT NULL THEN
        PERFORM 1 FROM request_engine.native_credentials
          WHERE id=v_session.password_credential_id AND native_identity_id=v_identity
            AND kind='password' AND status='active' FOR SHARE;
    ELSE
        PERFORM 1 FROM request_engine.webauthn_credentials
          WHERE id=v_session.webauthn_credential_id AND native_identity_id=v_identity
            AND status='active' FOR SHARE;
    END IF;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT state INTO v_recovery FROM request_engine.native_identity_recovery_state
      WHERE native_identity_id=v_identity FOR SHARE;
    IF FOUND AND v_recovery<>'normal' THEN RETURN NULL; END IF;
    SELECT * INTO v_session FROM request_engine.native_sessions
      WHERE id=p_session_id AND native_identity_id=v_identity FOR UPDATE;
    IF NOT FOUND OR v_session.status<>'active' OR v_session.recovery_derived
       OR v_session.session_epoch<>v_epoch OR v_session.expires_at<=clock_timestamp()
    THEN RETURN NULL; END IF;
    UPDATE request_engine.native_sessions
      SET last_authenticated_at=clock_timestamp(),last_seen_at=clock_timestamp(),
          authentication_methods=ARRAY['password']::text[],
          authentication_assurance='single_factor',user_verified=false
      WHERE id=p_session_id RETURNING last_authenticated_at INTO v_authenticated;
    RETURN v_authenticated;
END $$;
"""

_COMPLETE_RECOVERY = """
CREATE FUNCTION request_auth.complete_native_recovery_with_password(
    p_session_id uuid,p_credential_id uuid,p_expected_recovery_epoch bigint,
    p_expected_verifier text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO pg_catalog,request_engine AS $$
DECLARE
    v_identity uuid;
    v_epoch bigint;
    v_session request_engine.native_sessions%ROWTYPE;
    v_recovery request_engine.native_identity_recovery_state%ROWTYPE;
BEGIN
    SELECT * INTO v_session FROM request_engine.native_sessions WHERE id=p_session_id;
    v_identity := v_session.native_identity_id;
    IF NOT FOUND OR p_credential_id IS NULL OR p_expected_recovery_epoch IS NULL
       OR p_expected_verifier IS NULL
      THEN RETURN false; END IF;
    PERFORM 1 FROM request_engine.identity_authorities authority
      JOIN request_engine.native_identities identity ON identity.identity_authority_id=authority.id
      WHERE identity.id=v_identity AND authority.kind='native' AND authority.status='active'
      FOR SHARE OF authority;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT session_epoch INTO v_epoch FROM request_engine.native_identities
      WHERE id=v_identity AND status='active' FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM 1 FROM request_engine.native_credentials
      WHERE id=p_credential_id AND native_identity_id=v_identity
        AND kind='password' AND status='active' AND verifier=p_expected_verifier FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF v_session.password_credential_id IS NOT NULL THEN
        PERFORM 1 FROM request_engine.native_credentials
          WHERE id=v_session.password_credential_id AND native_identity_id=v_identity
            AND kind='password' AND status='active' FOR SHARE;
    ELSE
        PERFORM 1 FROM request_engine.webauthn_credentials
          WHERE id=v_session.webauthn_credential_id AND native_identity_id=v_identity
            AND status='active' FOR SHARE;
    END IF;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO v_recovery FROM request_engine.native_identity_recovery_state
      WHERE native_identity_id=v_identity FOR UPDATE;
    IF NOT FOUND OR v_recovery.state<>'recovery_restricted'
       OR v_recovery.recovery_epoch<>p_expected_recovery_epoch THEN RETURN false; END IF;
    SELECT * INTO v_session FROM request_engine.native_sessions
      WHERE id=p_session_id AND native_identity_id=v_identity FOR UPDATE;
    IF NOT FOUND OR v_session.status<>'active'
       OR v_session.session_epoch<>v_epoch OR v_session.expires_at<=clock_timestamp()
       THEN RETURN false; END IF;
    UPDATE request_engine.native_identity_recovery_state
      SET state='normal',revision=revision+1,completed_at=clock_timestamp()
      WHERE native_identity_id=v_identity;
    INSERT INTO request_engine.native_identity_recovery_facts(
        native_identity_id,event_kind,recovery_epoch,recovery_method,correlation_id
    ) VALUES(v_identity,'recovery_completed',v_recovery.recovery_epoch,
        v_recovery.last_recovery_method,
        NULLIF(current_setting('request_engine.correlation_id',true),'')::uuid);
    -- Do not rewrite the recovery-derived session. A fresh login is required.
    RETURN true;
END $$;
"""
