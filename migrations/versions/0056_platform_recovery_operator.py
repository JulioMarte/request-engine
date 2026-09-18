"""Provision a bounded Native platform recovery operator.

Revision ID: 0056_platform_recovery_operator
Revises: 0055_authority_inspect_policy

Adds one deliberately narrow platform ceremony. A HUMAN platform controller
holding the existing delegable platform.principal.provision capability may bind
a credentialed Native identity to a platform Principal whose fixed profile
contains only platform.identity.read and platform.identity.recovery_approve.

The ceremony cannot create another root, tenant provisioner, recovery requester
or generic capability grant. Replays are accepted only when every immutable
identity/provenance field and both bounded grants match.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0056_platform_recovery_operator"
down_revision: str | Sequence[str] | None = "0055_authority_inspect_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_FUNCTION = (
    "request_platform.provision_native_recovery_operator(uuid, uuid, uuid, uuid, text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "GRANT SELECT (id, principal_plane, principal_kind, active, authority_revision), "
        "INSERT (id, principal_plane, principal_kind, external_subject) "
        "ON request_engine.principals TO request_platform_control_definer"
    )
    op.execute(
        "GRANT SELECT (id, principal_id, principal_plane, identity_authority_id, "
        "subject_id, status), "
        "INSERT (id, principal_id, principal_plane, identity_authority_id, subject_id, status) "
        "ON request_engine.identity_bindings TO request_platform_control_definer"
    )
    op.execute(
        "GRANT SELECT (principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, status, granted_by_principal_id, provenance_kind, provenance_reference), "
        "INSERT (principal_id, principal_plane, authority_plane, capability_key, delegable, "
        "granted_by_principal_id, provenance_kind, provenance_reference) "
        "ON request_engine.principal_authority_grants TO request_platform_control_definer"
    )
    op.execute(
        "GRANT SELECT (id, kind, status) ON request_engine.identity_authorities "
        "TO request_platform_control_definer"
    )
    op.execute("GRANT USAGE, CREATE ON SCHEMA request_platform TO request_platform_control_definer")
    op.execute(
        r"""
CREATE FUNCTION request_platform.provision_native_recovery_operator(
    p_principal_id uuid,
    p_binding_id uuid,
    p_identity_authority_id uuid,
    p_native_identity_id uuid,
    p_provenance_reference text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
DECLARE
    v_creator_id uuid;
    v_creator_revision bigint;
    v_current_revision bigint;
    v_creator_kind text;
    v_creator_active boolean;
    v_authority_kind text;
    v_authority_status text;
BEGIN
    PERFORM request_engine.acquire_identity_topology_share();

    IF p_principal_id IS NULL OR p_binding_id IS NULL
       OR p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
       OR p_provenance_reference IS NULL
       OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
    THEN
        RAISE EXCEPTION 'Recovery operator identity and provenance are required'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_creator_id := NULLIF(current_setting(
            'request_engine.authenticated_principal_id', true
        ), '')::uuid;
        v_creator_revision := NULLIF(current_setting(
            'request_engine.authority_revision', true
        ), '')::bigint;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'Platform actor provenance is malformed'
            USING ERRCODE = '28000';
    END;

    IF v_creator_id IS NULL OR v_creator_revision IS NULL THEN
        RAISE EXCEPTION 'Platform actor provenance is required'
            USING ERRCODE = '28000';
    END IF;

    SELECT principal_kind, active, authority_revision
      INTO v_creator_kind, v_creator_active, v_current_revision
      FROM request_engine.principals
     WHERE id = v_creator_id
       AND principal_plane = 'platform'
     FOR UPDATE;

    IF NOT FOUND OR NOT v_creator_active OR v_creator_kind <> 'human' THEN
        RAISE EXCEPTION 'Recovery operator provisioning requires an active HUMAN controller'
            USING ERRCODE = '42501';
    END IF;
    IF v_current_revision <> v_creator_revision THEN
        RAISE EXCEPTION 'Platform authority revision is stale'
            USING ERRCODE = '40001';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.principal_authority_grants AS grant_row
         WHERE grant_row.principal_id = v_creator_id
           AND grant_row.principal_plane = 'platform'
           AND grant_row.authority_plane = 'platform'
           AND grant_row.capability_key = 'platform.principal.provision'
           AND grant_row.status = 'active'
           AND grant_row.delegable
    ) THEN
        RAISE EXCEPTION 'Platform actor cannot provision bounded Principals'
            USING ERRCODE = '42501';
    END IF;

    SELECT kind, status
      INTO v_authority_kind, v_authority_status
      FROM request_engine.identity_authorities
     WHERE id = p_identity_authority_id
     FOR SHARE;
    IF NOT FOUND OR v_authority_kind <> 'native' OR v_authority_status <> 'active' THEN
        RAISE EXCEPTION 'Recovery operator requires an active Native identity authority'
            USING ERRCODE = '23514';
    END IF;
    IF NOT request_auth.lock_credentialed_native_identity(
        p_identity_authority_id, p_native_identity_id
    ) THEN
        RAISE EXCEPTION 'Active credentialed Native identity is required'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1 FROM request_engine.principals WHERE id = p_principal_id
    ) OR EXISTS (
        SELECT 1 FROM request_engine.identity_bindings WHERE id = p_binding_id
    ) THEN
        IF EXISTS (
            SELECT 1
              FROM request_engine.principals AS principal
              JOIN request_engine.identity_bindings AS binding
                ON binding.principal_id = principal.id
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.external_subject =
                   'native-recovery-operator:' || p_native_identity_id::text
               AND binding.id = p_binding_id
               AND binding.principal_plane = 'platform'
               AND binding.identity_authority_id = p_identity_authority_id
               AND binding.subject_id = p_native_identity_id::text
               AND binding.status = 'active'
               AND (
                   SELECT count(DISTINCT grant_row.capability_key)
                     FROM request_engine.principal_authority_grants AS grant_row
                    WHERE grant_row.principal_id = p_principal_id
                      AND grant_row.principal_plane = 'platform'
                      AND grant_row.authority_plane = 'platform'
                      AND grant_row.status = 'active'
                      AND NOT grant_row.delegable
                      AND grant_row.granted_by_principal_id = v_creator_id
                      AND grant_row.provenance_kind = 'provisioning'
                      AND grant_row.provenance_reference = btrim(p_provenance_reference)
                      AND grant_row.capability_key IN (
                          'platform.identity.read',
                          'platform.identity.recovery_approve'
                      )
               ) = 2
               AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS unexpected
                    WHERE unexpected.principal_id = p_principal_id
                      AND unexpected.status = 'active'
                      AND unexpected.capability_key NOT IN (
                          'platform.identity.read',
                          'platform.identity.recovery_approve'
                      )
               )
        ) THEN
            RETURN p_principal_id;
        END IF;
        RAISE EXCEPTION 'Recovery operator provisioning replay conflicts'
            USING ERRCODE = '23505';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM request_engine.identity_bindings
         WHERE identity_authority_id = p_identity_authority_id
           AND subject_id = p_native_identity_id::text
           AND principal_plane = 'platform'
    ) THEN
        RAISE EXCEPTION 'Native identity already has platform binding history'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO request_engine.principals (
        id, principal_plane, principal_kind, external_subject
    ) VALUES (
        p_principal_id,
        'platform',
        'human',
        'native-recovery-operator:' || p_native_identity_id::text
    );

    INSERT INTO request_engine.identity_bindings (
        id, principal_id, principal_plane, identity_authority_id, subject_id, status
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
        delegable, granted_by_principal_id, provenance_kind, provenance_reference
    )
    SELECT p_principal_id,
           'platform',
           'platform',
           capability_key,
           false,
           v_creator_id,
           'provisioning',
           btrim(p_provenance_reference)
      FROM (VALUES
          ('platform.identity.read'),
          ('platform.identity.recovery_approve')
      ) AS bounded_grant(capability_key);

    RETURN p_principal_id;
END
$function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_CONTROL_DEFINER}")
    op.execute("REVOKE CREATE ON SCHEMA request_platform FROM request_platform_control_definer")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO request_platform_control")


def downgrade() -> None:
    raise RuntimeError("Recovery operator provenance is append-preserving; roll forward")
