"""Consume one-time deployment trust into the first Platform Controller.

Revision ID: 0012_platform_root_consume
Revises: 0011_platform_root_intent
Create Date: 2026-09-08

The bootstrap function accepts only already-digested bootstrap evidence and an
already-derived password verifier. Raw bootstrap tokens and passwords never
cross the PostgreSQL function boundary.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_platform_root_consume"
down_revision: str | Sequence[str] | None = "0011_platform_root_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "request_bootstrap_definer"
_FUNCTION = "request_platform.establish_root(uuid, bytea, uuid, uuid, text, uuid, text, uuid, uuid)"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            v_role_mismatch boolean;
            v_has_membership boolean;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{_ROLE}') THEN
                EXECUTE 'CREATE ROLE {_ROLE} WITH '
                    'NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN '
                    'NOREPLICATION BYPASSRLS CONNECTION LIMIT -1';
            ELSE
                SELECT NOT (
                    NOT rolsuper AND rolinherit AND NOT rolcreaterole
                    AND NOT rolcreatedb AND NOT rolcanlogin AND NOT rolreplication
                    AND rolbypassrls AND rolconnlimit = -1
                    AND rolvaliduntil IS NULL AND rolpassword IS NULL
                )
                  INTO v_role_mismatch
                  FROM pg_catalog.pg_authid
                 WHERE rolname = '{_ROLE}';
                SELECT EXISTS (
                    SELECT 1
                      FROM pg_catalog.pg_auth_members AS membership
                      JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
                      JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
                     WHERE parent.rolname = '{_ROLE}' OR member.rolname = '{_ROLE}'
                ) INTO v_has_membership;
                IF v_role_mismatch OR v_has_membership THEN
                    RAISE EXCEPTION 'existing {_ROLE} does not match audited topology'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA request_engine TO {_ROLE}")
    op.execute(f"GRANT SELECT (id, kind, status) ON request_engine.identity_authorities TO {_ROLE}")
    op.execute(
        "GRANT SELECT (id, token_digest, permitted_action, provenance_reference, status, "
        "expires_at, revision), UPDATE (status, revision, consumed_at) "
        f"ON request_engine.platform_bootstrap_intents TO {_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, identity_authority_id, login_handle) "
        f"ON request_engine.native_identities TO {_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, native_identity_id, verifier) "
        f"ON request_engine.native_credentials TO {_ROLE}"
    )
    op.execute(
        "GRANT SELECT (id, organization_id, principal_plane, active, authority_revision), "
        "INSERT (id, principal_plane, principal_kind, external_subject), "
        f"UPDATE (authority_revision) ON request_engine.principals TO {_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, principal_id, principal_plane, identity_authority_id, "
        f"subject_id, status) ON request_engine.identity_bindings TO {_ROLE}"
    )
    op.execute(
        "GRANT INSERT (principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, provenance_kind, provenance_reference) "
        f"ON request_engine.principal_authority_grants TO {_ROLE}"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_ROLE}")
    op.execute(
        """
        CREATE FUNCTION request_platform.establish_root(
            p_intent_id uuid,
            p_token_digest bytea,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_password_verifier text,
            p_principal_id uuid,
            p_binding_id uuid
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_provenance text;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            -- Different intents must not race to create two initial Platform roots.
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476356);

            SELECT provenance_reference
              INTO v_provenance
              FROM request_engine.platform_bootstrap_intents
             WHERE id = p_intent_id
               AND token_digest = p_token_digest
               AND permitted_action = 'platform.root.establish'
               AND status = 'pending'
               AND expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1 FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists' USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native' OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (p_native_identity_id, p_identity_authority_id, p_login_handle);
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (p_credential_id, p_native_identity_id, p_password_verifier);
            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id,
                'platform',
                'human',
                'native-bootstrap:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id,
                p_principal_id,
                'platform',
                p_identity_authority_id,
                p_native_identity_id::text,
                'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   capability_key,
                   delegable,
                   'trust_bootstrap',
                   'platform-bootstrap:' || p_intent_id::text || ':' || v_provenance
              FROM (VALUES
                  ('platform.principal.provision', true),
                  ('platform.tenant_provisioner.provision', true),
                  ('organization.provision', true),
                  ('platform.identity.recover', false)
              ) AS initial_grant(capability_key, delegable);

            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_intent_id;
            RETURN p_principal_id;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
    op.execute(f"REVOKE USAGE ON SCHEMA request_platform FROM {_ROLE}")
    op.execute(
        "REVOKE INSERT (principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, provenance_kind, provenance_reference) "
        f"ON request_engine.principal_authority_grants FROM {_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, principal_id, principal_plane, identity_authority_id, "
        f"subject_id, status) ON request_engine.identity_bindings FROM {_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (id, organization_id, principal_plane, active, authority_revision), "
        "INSERT (id, principal_plane, principal_kind, external_subject), "
        f"UPDATE (authority_revision) ON request_engine.principals FROM {_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, native_identity_id, verifier) "
        f"ON request_engine.native_credentials FROM {_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, identity_authority_id, login_handle) "
        f"ON request_engine.native_identities FROM {_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (id, token_digest, permitted_action, provenance_reference, status, "
        "expires_at, revision), UPDATE (status, revision, consumed_at) "
        f"ON request_engine.platform_bootstrap_intents FROM {_ROLE}"
    )
    op.execute(
        f"REVOKE SELECT (id, kind, status) ON request_engine.identity_authorities FROM {_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA request_engine FROM {_ROLE}")
    # Cluster-global role is intentionally retained for another RE database.
