"""Provision a bounded Platform tenant-provisioner Principal.

Revision ID: 0013_platform_tenant_provisioner
Revises: 0012_platform_root_consume
Create Date: 2026-09-08

The command is intentionally specialized: callers cannot submit arbitrary
capability sets. A current Platform actor holding the provisioning command and
delegable organization.provision authority may create B with exactly one
non-delegable organization.provision grant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_platform_tenant_provisioner"
down_revision: str | Sequence[str] | None = "0012_platform_root_consume"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_ROLE = "request_engine_platform_control"
_DEFINER_ROLE = "request_platform_control_definer"
_FUNCTION = "request_platform.provision_tenant_provisioner(uuid, text, text)"


def _ensure_role(role: str, *, bypass_rls: bool) -> None:
    bypass = "BYPASSRLS" if bypass_rls else "NOBYPASSRLS"
    op.execute(
        f"""
        DO $$
        DECLARE
            v_mismatch boolean;
            v_membership boolean;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                EXECUTE 'CREATE ROLE {role} WITH NOSUPERUSER INHERIT NOCREATEROLE '
                    'NOCREATEDB NOLOGIN NOREPLICATION {bypass} CONNECTION LIMIT -1';
            ELSE
                SELECT NOT (
                    NOT rolsuper AND rolinherit AND NOT rolcreaterole AND NOT rolcreatedb
                    AND NOT rolcanlogin AND NOT rolreplication
                    AND rolbypassrls = {str(bypass_rls).lower()}
                    AND rolconnlimit = -1 AND rolvaliduntil IS NULL AND rolpassword IS NULL
                ) INTO v_mismatch
                  FROM pg_catalog.pg_authid
                 WHERE rolname = '{role}';
                SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_auth_members AS m
                    JOIN pg_catalog.pg_roles AS parent ON parent.oid = m.roleid
                    JOIN pg_catalog.pg_roles AS member ON member.oid = m.member
                    WHERE parent.rolname = '{role}' OR member.rolname = '{role}'
                ) INTO v_membership;
                IF v_mismatch OR v_membership THEN
                    RAISE EXCEPTION 'existing {role} does not match audited topology'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    _ensure_role(_RUNTIME_ROLE, bypass_rls=False)
    _ensure_role(_DEFINER_ROLE, bypass_rls=True)

    op.execute(f"GRANT USAGE ON SCHEMA request_platform TO {_RUNTIME_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA request_engine TO {_DEFINER_ROLE}")
    op.execute(
        "GRANT SELECT (id, organization_id, principal_plane, principal_kind, active, "
        "authority_revision), INSERT (id, principal_plane, principal_kind, external_subject) "
        f"ON request_engine.principals TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT SELECT (principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, status), INSERT (principal_id, principal_plane, authority_plane, "
        "capability_key, delegable, granted_by_principal_id, provenance_kind, "
        f"provenance_reference) ON request_engine.principal_authority_grants TO {_DEFINER_ROLE}"
    )
    op.execute(f"GRANT UPDATE (authority_revision) ON request_engine.principals TO {_DEFINER_ROLE}")
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_DEFINER_ROLE}")
    op.execute(
        """
        CREATE FUNCTION request_platform.provision_tenant_provisioner(
            p_new_principal_id uuid,
            p_external_subject text,
            p_provenance_reference text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_has_command boolean;
            v_can_delegate_org boolean;
        BEGIN
            BEGIN
                v_creator_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_expected_revision := current_setting(
                    'request_engine.authority_revision', true
                )::bigint;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is missing or malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL OR v_expected_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;
            IF length(btrim(p_external_subject)) = 0
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Provisioning subject and provenance must be nonblank'
                    USING ERRCODE = '22023';
            END IF;

            SELECT principal_kind, authority_revision
              INTO v_creator_kind, v_current_revision
              FROM request_engine.principals
             WHERE id = v_creator_id
               AND principal_plane = 'platform'
               AND organization_id IS NULL
               AND active
             FOR UPDATE;
            IF NOT FOUND OR v_creator_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal is not provision-capable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> v_expected_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale' USING ERRCODE = '40001';
            END IF;

            SELECT EXISTS (
                       SELECT 1 FROM request_engine.principal_authority_grants
                        WHERE principal_id = v_creator_id
                          AND principal_plane = 'platform'
                          AND authority_plane = 'platform'
                          AND capability_key = 'platform.tenant_provisioner.provision'
                          AND status = 'active'
                   ),
                   EXISTS (
                       SELECT 1 FROM request_engine.principal_authority_grants
                        WHERE principal_id = v_creator_id
                          AND principal_plane = 'platform'
                          AND authority_plane = 'platform'
                          AND capability_key = 'organization.provision'
                          AND delegable
                          AND status = 'active'
                   )
              INTO v_has_command, v_can_delegate_org;
            IF NOT v_has_command OR NOT v_can_delegate_org THEN
                RAISE EXCEPTION 'Current Platform Principal lacks bounded provisioning authority'
                    USING ERRCODE = '42501';
            END IF;

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_new_principal_id, 'platform', 'human', btrim(p_external_subject)
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_new_principal_id,
                'platform',
                'platform',
                'organization.provision',
                false,
                v_creator_id,
                'provisioning',
                btrim(p_provenance_reference)
            );
            RETURN p_new_principal_id;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_DEFINER_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO {_RUNTIME_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
    op.execute(f"REVOKE USAGE ON SCHEMA request_platform FROM {_RUNTIME_ROLE}")
    op.execute(
        "REVOKE SELECT (principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, status), INSERT (principal_id, principal_plane, authority_plane, "
        "capability_key, delegable, granted_by_principal_id, provenance_kind, "
        f"provenance_reference) ON request_engine.principal_authority_grants FROM {_DEFINER_ROLE}"
    )
    op.execute(
        f"REVOKE UPDATE (authority_revision) ON request_engine.principals FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (id, organization_id, principal_plane, principal_kind, active, "
        "authority_revision), INSERT (id, principal_plane, principal_kind, external_subject) "
        f"ON request_engine.principals FROM {_DEFINER_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA request_engine FROM {_DEFINER_ROLE}")
    # Cluster-global roles are retained for other Request Engine databases.
