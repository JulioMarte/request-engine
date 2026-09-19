"""Digest-only recovery code sets with single-use consumption.

Revision ID: 0064_recovery_codes
Revises: 0063_password_argon2id

Implements plan §5.7:

- ``recovery_code_sets`` are scoped to exactly one native identity (runtime) or
  one setup session (first-run), versioned and revocable;
- ``recovery_codes`` store only a 32-byte digest, globally unique, single-use via
  ``used_at``;
- creating a set revokes the prior active set for the same scope, so rotation
  invalidates remaining codes;
- ``consume_recovery_code`` locks the matching unused code, marks it used and
  returns its owner in one transaction; concurrent replays yield one winner;
- ``promote_recovery_code_set`` re-points a setup-session-owned set to the
  permanent native identity in the finalize transaction (P4);
- a private append-only fact table records set creation/rotation, promotion and
  code consumption with identifiers/provenance only, never raw codes.

Raw codes are generated in Python and displayed once; they never reach durable
storage.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064_recovery_codes"
down_revision: str | Sequence[str] | None = "0063_password_argon2id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTIONS = (
    "create_recovery_code_set(uuid, uuid, uuid, bytea[])",
    "consume_recovery_code(bytea)",
    "promote_recovery_code_set(uuid, uuid)",
    "revoke_recovery_code_set(uuid, text)",
    "read_recovery_code_set_summary(uuid)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE request_engine.recovery_code_sets (
            id uuid PRIMARY KEY,
            native_identity_id uuid REFERENCES request_engine.native_identities(id),
            setup_session_id uuid REFERENCES request_engine.setup_sessions(id),
            version integer NOT NULL DEFAULT 1,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            revoked_at timestamptz,
            CONSTRAINT recovery_code_sets_scope_check CHECK (
                (native_identity_id IS NOT NULL) <> (setup_session_id IS NOT NULL)
            ),
            CONSTRAINT recovery_code_sets_status_check CHECK (status IN ('active', 'revoked')),
            CONSTRAINT recovery_code_sets_version_check CHECK (version > 0),
            CONSTRAINT recovery_code_sets_revision_check CHECK (revision > 0),
            CONSTRAINT recovery_code_sets_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status = 'active' AND revoked_at IS NULL)
            )
        );
        CREATE UNIQUE INDEX recovery_code_sets_active_identity_uq
            ON request_engine.recovery_code_sets (native_identity_id)
            WHERE status = 'active' AND native_identity_id IS NOT NULL;
        CREATE UNIQUE INDEX recovery_code_sets_active_setup_uq
            ON request_engine.recovery_code_sets (setup_session_id)
            WHERE status = 'active' AND setup_session_id IS NOT NULL;
        ALTER TABLE request_engine.recovery_code_sets OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.recovery_code_sets FROM PUBLIC;

        CREATE TABLE request_engine.recovery_codes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            set_id uuid NOT NULL REFERENCES request_engine.recovery_code_sets(id),
            code_digest bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            used_at timestamptz,
            CONSTRAINT recovery_codes_digest_check CHECK (octet_length(code_digest) = 32),
            UNIQUE (code_digest)
        );
        CREATE INDEX recovery_codes_set_idx
            ON request_engine.recovery_codes (set_id);
        ALTER TABLE request_engine.recovery_codes OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.recovery_codes FROM PUBLIC;

        CREATE TABLE request_engine.platform_recovery_code_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_kind text NOT NULL,
            set_id uuid NOT NULL,
            native_identity_id uuid,
            setup_session_id uuid,
            code_id uuid,
            actor_principal_id uuid,
            actor_authentication_method text,
            capability_key text,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_recovery_code_facts_kind_check CHECK (
                event_kind IN ('set_created', 'set_revoked', 'set_promoted', 'code_consumed')
            )
        );
        ALTER TABLE request_engine.platform_recovery_code_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_recovery_code_facts FROM PUBLIC;
        CREATE TRIGGER platform_recovery_code_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.platform_recovery_code_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.create_recovery_code_set(
            p_set_id uuid,
            p_native_identity_id uuid,
            p_setup_session_id uuid,
            p_code_digests bytea[]
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_scope_count integer;
            v_identity_status text;
            v_setup_status text;
            v_version integer;
        BEGIN
            v_scope_count := (p_native_identity_id IS NOT NULL)::int
                + (p_setup_session_id IS NOT NULL)::int;
            IF p_set_id IS NULL
               OR v_scope_count <> 1
               OR p_code_digests IS NULL
               OR cardinality(p_code_digests) NOT BETWEEN 1 AND 50
               OR EXISTS (
                   SELECT 1 FROM unnest(p_code_digests) AS digest
                    WHERE digest IS NULL OR octet_length(digest) <> 32
               )
            THEN
                RETURN false;
            END IF;

            IF p_native_identity_id IS NOT NULL THEN
                PERFORM 1
                  FROM request_engine.identity_authorities AS authority
                  JOIN request_engine.native_identities AS native_identity
                    ON native_identity.identity_authority_id = authority.id
                 WHERE native_identity.id = p_native_identity_id
                   AND authority.kind = 'native' AND authority.status = 'active'
                 FOR SHARE OF authority;
                IF NOT FOUND THEN RETURN false; END IF;

                SELECT identity.status INTO v_identity_status
                  FROM request_engine.native_identities AS identity
                 WHERE identity.id = p_native_identity_id
                 FOR UPDATE;
                IF NOT FOUND OR v_identity_status <> 'active' THEN
                    RETURN false;
                END IF;

                SELECT coalesce(max(code_set.version), 0) + 1 INTO v_version
                  FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.native_identity_id = p_native_identity_id;

                UPDATE request_engine.recovery_code_sets
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE native_identity_id = p_native_identity_id
                   AND status = 'active';
            ELSE
                SELECT session.status INTO v_setup_status
                  FROM request_engine.setup_sessions AS session
                 WHERE session.id = p_setup_session_id
                 FOR UPDATE;
                IF NOT FOUND OR v_setup_status <> 'pending' THEN
                    RETURN false;
                END IF;

                SELECT coalesce(max(code_set.version), 0) + 1 INTO v_version
                  FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.setup_session_id = p_setup_session_id;

                UPDATE request_engine.recovery_code_sets
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE setup_session_id = p_setup_session_id
                   AND status = 'active';
            END IF;

            INSERT INTO request_engine.recovery_code_sets (
                id, native_identity_id, setup_session_id, version
            ) VALUES (
                p_set_id, p_native_identity_id, p_setup_session_id, v_version
            );

            INSERT INTO request_engine.recovery_codes (set_id, code_digest)
            SELECT p_set_id, digest FROM unnest(p_code_digests) AS digest;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_created', p_set_id, p_native_identity_id, p_setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.consume_recovery_code(
            p_code_digest bytea
        )
        RETURNS TABLE (
            native_identity_id uuid,
            set_id uuid,
            code_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_code_id uuid;
            v_set_id uuid;
            v_identity_id uuid;
            v_identity_status text;
        BEGIN
            IF p_code_digest IS NULL OR octet_length(p_code_digest) <> 32 THEN
                RETURN;
            END IF;

            SELECT code.id, code.set_id, code_set.native_identity_id
              INTO v_code_id, v_set_id, v_identity_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code.used_at IS NULL
               AND code_set.status = 'active'
               AND code_set.native_identity_id IS NOT NULL
             FOR UPDATE OF code, code_set;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_identity_id;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            UPDATE request_engine.recovery_codes
               SET used_at = clock_timestamp()
             WHERE id = v_code_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, code_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'code_consumed', v_set_id, v_identity_id, v_code_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.consume',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_identity_id, v_set_id, v_code_id;
        END
        $$;

        CREATE FUNCTION request_auth.promote_recovery_code_set(
            p_set_id uuid,
            p_native_identity_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_set request_engine.recovery_code_sets%ROWTYPE;
            v_identity_status text;
        BEGIN
            IF p_set_id IS NULL OR p_native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT code_set.* INTO v_set
              FROM request_engine.recovery_code_sets AS code_set
             WHERE code_set.id = p_set_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_set.status <> 'active'
               OR v_set.setup_session_id IS NULL
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.recovery_code_sets
               SET setup_session_id = NULL,
                   native_identity_id = p_native_identity_id
             WHERE id = p_set_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_promoted', p_set_id, p_native_identity_id, v_set.setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.revoke_recovery_code_set(
            p_set_id uuid,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_set request_engine.recovery_code_sets%ROWTYPE;
        BEGIN
            IF p_set_id IS NULL
               OR p_reason IS NULL
               OR length(btrim(p_reason)) NOT BETWEEN 1 AND 200
            THEN
                RETURN false;
            END IF;

            SELECT code_set.* INTO v_set
              FROM request_engine.recovery_code_sets AS code_set
             WHERE code_set.id = p_set_id
             FOR UPDATE;
            IF NOT FOUND OR v_set.status <> 'active' THEN
                RETURN false;
            END IF;

            UPDATE request_engine.recovery_code_sets
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_set_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_revoked', p_set_id, v_set.native_identity_id, v_set.setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.read_recovery_code_set_summary(
            p_native_identity_id uuid
        )
        RETURNS TABLE (
            set_id uuid,
            version integer,
            status text,
            created_at timestamptz,
            total_codes integer,
            remaining_codes integer
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT code_set.id,
                   code_set.version,
                   code_set.status,
                   code_set.created_at,
                   count(code.id)::integer,
                   count(code.id) FILTER (WHERE code.used_at IS NULL)::integer
              FROM request_engine.recovery_code_sets AS code_set
              LEFT JOIN request_engine.recovery_codes AS code
                ON code.set_id = code_set.id
             WHERE code_set.native_identity_id = p_native_identity_id
             GROUP BY code_set.id, code_set.version, code_set.status, code_set.created_at
             ORDER BY code_set.version DESC
        $$;
        """
    )

    for signature in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO request_engine_schema_owner")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Recovery code state is append-preserving; roll forward")
