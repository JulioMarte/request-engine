"""Persist the Platform Instance and bounded SetupSession lifecycle.

Revision ID: 0057_platform_instance_setup
Revises: 0056_platform_recovery_operator

Implements the durable data model of ADR 0014 / the instance-claim plan:

- one structurally-singleton ``platform_instance`` row whose lifecycle is
  independent of users and is never inferred from ``COUNT(users) = 0``;
- bounded, digest-only ``setup_sessions`` scoped to the control plane;
- built-in native/workload identity-authority facts bound to the Instance so a
  clean install no longer depends on an operator copying CLI-printed UUIDs.

The migration adopts an already bootstrapped database as CLAIMED and fails closed
when historical root provenance is ambiguous. It creates no Principal, binding,
grant or owner; finalization is a later phase.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057_platform_instance_setup"
down_revision: str | Sequence[str] | None = "0056_platform_recovery_operator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"

_INSTANCE_FUNCTION = "request_platform.read_platform_instance()"
_CREATE_FUNCTION = "request_platform.create_setup_session(uuid, bytea, text, text, integer)"
_READ_FUNCTION = "request_platform.read_setup_session(bytea)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        """
        CREATE TABLE request_engine.platform_instance (
            singleton_key smallint PRIMARY KEY DEFAULT 1,
            id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
            state text NOT NULL DEFAULT 'unclaimed',
            revision bigint NOT NULL DEFAULT 1,
            built_in_native_authority_id uuid NOT NULL,
            built_in_workload_authority_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            claimed_at timestamptz,
            initial_owner_principal_id uuid,
            claim_provenance text,
            CONSTRAINT platform_instance_singleton_check CHECK (singleton_key = 1),
            CONSTRAINT platform_instance_state_check
                CHECK (state IN ('unclaimed', 'claimed')),
            CONSTRAINT platform_instance_revision_check CHECK (revision > 0),
            CONSTRAINT platform_instance_claim_shape_check CHECK (
                (
                    state = 'unclaimed'
                    AND claimed_at IS NULL
                    AND initial_owner_principal_id IS NULL
                    AND claim_provenance IS NULL
                )
                OR (
                    state = 'claimed'
                    AND claimed_at IS NOT NULL
                    AND initial_owner_principal_id IS NOT NULL
                    AND claim_provenance IS NOT NULL
                    AND length(btrim(claim_provenance)) > 0
                )
            )
        );
        ALTER TABLE request_engine.platform_instance OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_instance FROM PUBLIC;

        CREATE TABLE request_engine.setup_sessions (
            id uuid PRIMARY KEY,
            instance_id uuid NOT NULL
                REFERENCES request_engine.platform_instance(id),
            token_digest bytea NOT NULL,
            token_fingerprint text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            mode text NOT NULL,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT setup_sessions_digest_check CHECK (octet_length(token_digest) = 32),
            CONSTRAINT setup_sessions_fingerprint_check CHECK (
                token_fingerprint ~ '^[0-9a-f]{16}$'
            ),
            CONSTRAINT setup_sessions_status_check CHECK (
                status IN ('pending', 'consumed', 'expired', 'revoked')
            ),
            CONSTRAINT setup_sessions_mode_check CHECK (
                mode IN ('interactive', 'protected', 'automated')
            ),
            CONSTRAINT setup_sessions_revision_check CHECK (revision > 0),
            CONSTRAINT setup_sessions_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT setup_sessions_terminal_check CHECK (
                (status = 'pending' AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'consumed' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL AND consumed_at IS NULL)
                OR (status = 'expired' AND consumed_at IS NULL AND revoked_at IS NULL)
            )
        );
        CREATE UNIQUE INDEX setup_sessions_token_digest_uq
            ON request_engine.setup_sessions (token_digest);
        CREATE INDEX setup_sessions_active_idx
            ON request_engine.setup_sessions (expires_at)
            WHERE status = 'pending';
        ALTER TABLE request_engine.setup_sessions OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.setup_sessions FROM PUBLIC;
        """
    )

    op.execute(
        """
        CREATE FUNCTION request_engine.guard_platform_instance()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Platform instance is not deletable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.singleton_key, NEW.id, NEW.created_at,
                       NEW.built_in_native_authority_id, NEW.built_in_workload_authority_id)
                   IS DISTINCT FROM
                   ROW(OLD.singleton_key, OLD.id, OLD.created_at,
                       OLD.built_in_native_authority_id, OLD.built_in_workload_authority_id)
                THEN
                    RAISE EXCEPTION 'Platform instance identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.state = 'claimed' AND NEW.state <> 'claimed' THEN
                    RAISE EXCEPTION 'Platform instance claim is one-way'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.state = OLD.state THEN
                    IF NEW.revision <> OLD.revision
                       OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
                       OR NEW.initial_owner_principal_id
                          IS DISTINCT FROM OLD.initial_owner_principal_id
                       OR NEW.claim_provenance IS DISTINCT FROM OLD.claim_provenance
                    THEN
                        RAISE EXCEPTION
                            'Only an unclaimed-to-claimed transition may change Instance state'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NOT (OLD.state = 'unclaimed' AND NEW.state = 'claimed') THEN
                    RAISE EXCEPTION 'Invalid platform instance state transition'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Platform instance claim must increment revision once'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_instance()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_instance() FROM PUBLIC;
        CREATE TRIGGER platform_instance_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.platform_instance
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_instance();

        CREATE FUNCTION request_engine.guard_setup_session()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'pending' THEN
                    RAISE EXCEPTION 'Pending setup sessions cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.id, NEW.instance_id, NEW.token_digest, NEW.token_fingerprint,
                       NEW.mode, NEW.created_at, NEW.expires_at)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.instance_id, OLD.token_digest, OLD.token_fingerprint,
                       OLD.mode, OLD.created_at, OLD.expires_at)
                THEN
                    RAISE EXCEPTION 'Setup session identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status <> 'pending' THEN
                    RAISE EXCEPTION 'Setup session terminal state is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status NOT IN ('consumed', 'expired', 'revoked') THEN
                    RAISE EXCEPTION 'Invalid setup session state transition'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Setup session revision must increment exactly once'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_setup_session()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_setup_session() FROM PUBLIC;
        CREATE TRIGGER setup_sessions_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.setup_sessions
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_setup_session();
        """
    )

    # Built-in authority adoption/creation and legacy-root adoption. A truly fresh
    # database becomes UNCLAIMED; a database already carrying exactly one
    # unambiguous historical CLI trust-bootstrap root becomes CLAIMED. Anything
    # ambiguous fails the migration closed instead of selecting a root.
    op.execute(
        """
        DO $adopt$
        DECLARE
            v_native uuid;
            v_workload uuid;
            v_platform_count integer;
            v_root_count integer;
            v_root uuid;
        BEGIN
            SELECT id INTO v_native
              FROM request_engine.identity_authorities
             WHERE kind = 'native' AND issuer_or_environment = 'request-engine-native';
            IF NOT FOUND THEN
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_authorities WHERE kind = 'native'
                ) THEN
                    RAISE EXCEPTION
                        'Ambiguous Native identity authority provenance'
                        USING ERRCODE = '55000';
                END IF;
                INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
                VALUES ('native', 'request-engine-native')
                RETURNING id INTO v_native;
            END IF;

            SELECT id INTO v_workload
              FROM request_engine.identity_authorities
             WHERE kind = 'workload' AND issuer_or_environment = 'request-engine-workload';
            IF NOT FOUND THEN
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_authorities WHERE kind = 'workload'
                ) THEN
                    RAISE EXCEPTION
                        'Ambiguous workload identity authority provenance'
                        USING ERRCODE = '55000';
                END IF;
                INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
                VALUES ('workload', 'request-engine-workload')
                RETURNING id INTO v_workload;
            END IF;

            SELECT count(*) INTO v_platform_count
              FROM request_engine.principals
             WHERE principal_plane = 'platform';

            IF v_platform_count = 0 THEN
                INSERT INTO request_engine.platform_instance (
                    singleton_key, id, state,
                    built_in_native_authority_id, built_in_workload_authority_id
                ) VALUES (
                    1, gen_random_uuid(), 'unclaimed', v_native, v_workload
                );
            ELSE
                SELECT count(*) INTO v_root_count
                  FROM request_engine.principals AS principal
                 WHERE principal.principal_plane = 'platform'
                   AND principal.external_subject LIKE 'native-bootstrap:%'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = principal.id
                          AND grant_row.status = 'active'
                          AND grant_row.provenance_kind = 'trust_bootstrap'
                   );
                IF v_root_count <> 1 THEN
                    RAISE EXCEPTION
                        'Ambiguous historical platform root provenance; refusing to adopt'
                        USING ERRCODE = '55000';
                END IF;
                SELECT principal.id INTO v_root
                  FROM request_engine.principals AS principal
                 WHERE principal.principal_plane = 'platform'
                   AND principal.external_subject LIKE 'native-bootstrap:%'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = principal.id
                          AND grant_row.status = 'active'
                          AND grant_row.provenance_kind = 'trust_bootstrap'
                   )
                 LIMIT 1;
                INSERT INTO request_engine.platform_instance (
                    singleton_key, id, state,
                    built_in_native_authority_id, built_in_workload_authority_id,
                    claimed_at, initial_owner_principal_id, claim_provenance
                ) VALUES (
                    1, gen_random_uuid(), 'claimed', v_native, v_workload,
                    clock_timestamp(), v_root, 'legacy_cli_adoption'
                );
            END IF;
        END
        $adopt$;
        """
    )

    op.execute(
        "GRANT SELECT (singleton_key, id, state, revision, "
        "built_in_native_authority_id, built_in_workload_authority_id, "
        "created_at, claimed_at, initial_owner_principal_id, claim_provenance) "
        "ON request_engine.platform_instance TO request_platform_control_definer"
    )
    op.execute(
        "GRANT SELECT (id, instance_id, token_digest, token_fingerprint, status, mode, "
        "revision, created_at, expires_at, consumed_at, revoked_at), "
        "INSERT (id, instance_id, token_digest, token_fingerprint, mode, expires_at) "
        "ON request_engine.setup_sessions TO request_platform_control_definer"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_DEFINER}")

    op.execute(
        r"""
CREATE FUNCTION request_platform.read_platform_instance()
RETURNS TABLE (
    id uuid,
    state text,
    revision bigint,
    built_in_native_authority_id uuid,
    built_in_workload_authority_id uuid,
    claimed_at timestamptz,
    initial_owner_principal_id uuid,
    claim_provenance text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
    SELECT instance.id,
           instance.state,
           instance.revision,
           instance.built_in_native_authority_id,
           instance.built_in_workload_authority_id,
           instance.claimed_at,
           instance.initial_owner_principal_id,
           instance.claim_provenance
      FROM request_engine.platform_instance AS instance
     WHERE instance.singleton_key = 1;
$function$;
        """
    )

    op.execute(
        r"""
CREATE FUNCTION request_platform.create_setup_session(
    p_session_id uuid,
    p_token_digest bytea,
    p_token_fingerprint text,
    p_mode text,
    p_ttl_seconds integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
DECLARE
    v_instance_id uuid;
    v_state text;
    v_active integer;
BEGIN
    -- Serializes concurrent creation (bounded active cap) and, together with the
    -- finalize command taking the same lock, setup creation against a claim.
    PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476358);

    SELECT instance.id, instance.state
      INTO v_instance_id, v_state
      FROM request_engine.platform_instance AS instance
     WHERE instance.singleton_key = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Platform instance is not initialized' USING ERRCODE = '55000';
    END IF;
    IF v_state <> 'unclaimed' THEN
        RAISE EXCEPTION 'Setup is closed' USING ERRCODE = '55000';
    END IF;

    IF p_session_id IS NULL
       OR p_token_digest IS NULL
       OR octet_length(p_token_digest) <> 32
       OR p_token_fingerprint IS NULL
       OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
       OR p_mode IS NULL
       OR p_mode NOT IN ('interactive', 'protected', 'automated')
       OR p_ttl_seconds IS NULL
       OR p_ttl_seconds < 60
       OR p_ttl_seconds > 3600
    THEN
        RAISE EXCEPTION 'Setup session material is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT count(*) INTO v_active
      FROM request_engine.setup_sessions
     WHERE status = 'pending'
       AND expires_at > clock_timestamp();
    IF v_active >= 5 THEN
        RAISE EXCEPTION 'Too many active setup sessions' USING ERRCODE = '54000';
    END IF;

    INSERT INTO request_engine.setup_sessions (
        id, instance_id, token_digest, token_fingerprint, mode, expires_at
    ) VALUES (
        p_session_id,
        v_instance_id,
        p_token_digest,
        p_token_fingerprint,
        p_mode,
        clock_timestamp() + pg_catalog.make_interval(secs => p_ttl_seconds)
    );
    RETURN p_session_id;
END
$function$;
        """
    )

    op.execute(
        r"""
CREATE FUNCTION request_platform.read_setup_session(p_token_digest bytea)
RETURNS TABLE (
    id uuid,
    status text,
    mode text,
    expires_at timestamptz,
    consumed_at timestamptz,
    instance_state text,
    is_usable boolean
)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
    SELECT session.id,
           session.status,
           session.mode,
           session.expires_at,
           session.consumed_at,
           instance.state,
           (
               session.status = 'pending'
               AND session.expires_at > clock_timestamp()
               AND instance.state = 'unclaimed'
           )
      FROM request_engine.setup_sessions AS session
      JOIN request_engine.platform_instance AS instance
        ON instance.singleton_key = 1
     WHERE session.token_digest = p_token_digest;
$function$;
        """
    )

    for function, signature in (
        ("read_platform_instance", ""),
        ("create_setup_session", "uuid, bytea, text, text, integer"),
        ("read_setup_session", "bytea"),
    ):
        op.execute(f"ALTER FUNCTION request_platform.{function}({signature}) OWNER TO {_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION request_platform.{function}({signature}) FROM PUBLIC")
        op.execute(
            f"GRANT EXECUTE ON FUNCTION request_platform.{function}({signature}) TO {_RUNTIME}"
        )
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Platform Instance state is append-preserving; roll forward")
