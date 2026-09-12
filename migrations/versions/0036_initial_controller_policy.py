"""Persist an explicitly selected, immutable initial controller authority policy."""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "0036_initial_controller_policy"
down_revision: str | Sequence[str] | None = "0035_native_platform_provisioner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL = (
    "agent.policy.read",
    "agent.manage_policy",
    "integration.provision",
    "integration.read",
    "integration.manage_authority",
    "integration.suspend",
    "delegation.create",
    "delegation.revoke",
)
_OPERATIONAL = (
    "organization.bootstrap",
    "catalog.manage",
    "booking.manage_supply",
    "discovery.manage",
    "onboarding.read",
    "business.get_info",
    "catalog.search_offerings",
    "catalog.get_offering_details",
    "parties.register",
    "parties.lookup",
    "appointments.find_slots",
    "appointments.book",
    "appointments.read",
    "appointments.cancel",
    "appointments.reschedule",
    "appointments.subject_override",
    "appointments.day_board",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE request_engine.initial_controller_policies (
            policy_key text PRIMARY KEY,
            revision integer NOT NULL CHECK (revision > 0),
            grants jsonb NOT NULL CHECK (
                jsonb_typeof(grants) = 'array' AND jsonb_array_length(grants) > 0
            )
        );
        ALTER TABLE request_engine.initial_controller_policies OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.initial_controller_policies
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE TRIGGER initial_controller_policy_immutable
            BEFORE UPDATE OR DELETE ON request_engine.initial_controller_policies
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
    """)
    manifest = json.dumps(
        [
            {"capability_key": key, "authority_plane": plane, "delegable": True}
            for plane, keys in (("tenant_control", _CONTROL), ("operational", _OPERATIONAL))
            for key in keys
        ]
    )
    # Frozen migration data, never imported from the mutable runtime registry.
    op.execute(
        "INSERT INTO request_engine.initial_controller_policies (policy_key, revision, grants) "
        f"VALUES ('tenant-controller-v1', 1, '{manifest}'::jsonb)"
    )
    op.execute("""
        ALTER TABLE request_engine.organization_root_provisioning_facts
            ADD COLUMN initial_controller_policy_key text
                REFERENCES request_engine.initial_controller_policies(policy_key);
        -- Existing roots stay NULL. Establish the default only for future inserts.
        ALTER TABLE request_engine.organization_root_provisioning_facts
            ALTER COLUMN initial_controller_policy_key SET DEFAULT
                NULLIF(current_setting('request_engine.initial_controller_policy', true), '');
        GRANT SELECT (policy_key) ON request_engine.initial_controller_policies
            TO request_platform_control_definer;
        GRANT USAGE, CREATE ON SCHEMA request_platform TO request_platform_control_definer;
        CREATE FUNCTION request_platform.select_initial_controller_policy(p_policy_key text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        BEGIN
            IF p_policy_key IS NULL OR NOT EXISTS (
                SELECT 1 FROM request_engine.initial_controller_policies p
                 WHERE p.policy_key = p_policy_key
            ) THEN
                RAISE EXCEPTION 'Unknown initial controller policy' USING ERRCODE = '22023';
            END IF;
            PERFORM set_config('request_engine.initial_controller_policy', p_policy_key, true);
        END $$;
        ALTER FUNCTION request_platform.select_initial_controller_policy(text)
            OWNER TO request_platform_control_definer;
        REVOKE CREATE ON SCHEMA request_platform FROM request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.select_initial_controller_policy(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.select_initial_controller_policy(text)
            TO request_platform_control;
    """)
    op.execute("""
        CREATE FUNCTION request_engine.seed_initial_controller_policy()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        DECLARE
            v_grants jsonb;
        BEGIN
            IF NEW.initial_controller_policy_key IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT grants INTO STRICT v_grants
              FROM request_engine.initial_controller_policies
             WHERE policy_key = NEW.initial_controller_policy_key;
            IF EXISTS (
                SELECT 1 FROM jsonb_to_recordset(v_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE g.capability_key IS NULL OR btrim(g.capability_key) = ''
                    OR g.capability_key LIKE '%*%' OR g.authority_plane IS NULL
                    OR g.authority_plane NOT IN ('tenant_control', 'operational')
                    OR g.delegable IS NULL
            ) THEN
                RAISE EXCEPTION 'Invalid initial controller policy' USING ERRCODE = '23514';
            END IF;
            PERFORM set_config('request_engine.organization_id', NEW.organization_id::text, true);
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT NEW.organization_id, NEW.controller_principal_id, 'tenant', g.authority_plane,
                   g.capability_key, g.delegable, NEW.provisioned_by_principal_id, 'provisioning',
                   'policy:' || NEW.initial_controller_policy_key
                       || ';root:' || NEW.provenance_reference
              FROM jsonb_to_recordset(v_grants)
                AS g(capability_key text, authority_plane text, delegable boolean);
            RETURN NEW;
        END $$;
        ALTER FUNCTION request_engine.seed_initial_controller_policy()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.seed_initial_controller_policy() FROM PUBLIC;
        CREATE TRIGGER organization_root_seed_initial_policy
            AFTER INSERT ON request_engine.organization_root_provisioning_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.seed_initial_controller_policy();
    """)


def downgrade() -> None:
    raise RuntimeError("Initial controller policy provenance is append-only; roll forward")
