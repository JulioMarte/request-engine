"""Add first-class Agent tool/risk policy ceilings and safety budget windows.

Revision ID: 0026_agent_policy
Revises: 0025_delegation_grants
Create Date: 2026-09-08

An AgentPolicy is a separate least-privilege ceiling that constrains which
canonical capabilities an AGENT Principal may execute at all (tool policy),
the maximum operation risk class it may execute (risk ceiling), and how many
mutations it may attempt per fixed one-minute window (safety budget). The
policy is Request Engine-owned runtime policy, never derived from prompts or
model metadata. Absence of a policy denies every operation for the agent.

Enforcement is read fresh on every protected agent request, so policy changes
take effect immediately without relying on authority revision staleness. The
budget window table is the only runtime-writable surface and uses a conditional
upsert so concurrent requests cannot exceed the configured limit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_agent_policy"
down_revision: str | Sequence[str] | None = "0025_delegation_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.agent_policies (
            organization_id uuid NOT NULL,
            agent_principal_id uuid NOT NULL,
            allowed_capabilities text[] NOT NULL DEFAULT '{}',
            denied_capabilities text[] NOT NULL DEFAULT '{}',
            risk_ceiling text NOT NULL,
            max_mutations_per_minute integer NOT NULL,
            policy_revision bigint NOT NULL DEFAULT 1,
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT agent_policies_risk_ceiling_check CHECK (risk_ceiling IN (
                'read',
                'low_impact_write',
                'reversible_write',
                'external_commitment',
                'sensitive_data',
                'financial',
                'destructive'
            )),
            CONSTRAINT agent_policies_budget_check
                CHECK (max_mutations_per_minute > 0),
            CONSTRAINT agent_policies_revision_check CHECK (policy_revision > 0),
            CONSTRAINT agent_policies_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            PRIMARY KEY (organization_id, agent_principal_id),
            FOREIGN KEY (organization_id, agent_principal_id)
                REFERENCES request_engine.principals(organization_id, id)
        );
        ALTER TABLE request_engine.agent_policies
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.agent_policies ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.agent_policies FORCE ROW LEVEL SECURITY;
        CREATE POLICY agent_policies_tenant_isolation
            ON request_engine.agent_policies
            USING (
                organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.agent_policies FROM PUBLIC;
        GRANT SELECT ON request_engine.agent_policies TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE TABLE request_engine.agent_budget_windows (
            organization_id uuid NOT NULL,
            agent_principal_id uuid NOT NULL,
            window_started_at timestamptz NOT NULL,
            mutation_count integer NOT NULL DEFAULT 0,
            PRIMARY KEY (organization_id, agent_principal_id, window_started_at),
            CONSTRAINT agent_budget_windows_count_check CHECK (mutation_count >= 0),
            FOREIGN KEY (organization_id, agent_principal_id)
                REFERENCES request_engine.agent_policies(organization_id, agent_principal_id)
        );
        CREATE INDEX agent_budget_windows_agent_idx
            ON request_engine.agent_budget_windows (agent_principal_id, window_started_at);
        ALTER TABLE request_engine.agent_budget_windows
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.agent_budget_windows ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.agent_budget_windows FORCE ROW LEVEL SECURITY;
        CREATE POLICY agent_budget_windows_tenant_isolation
            ON request_engine.agent_budget_windows
            USING (
                organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.agent_budget_windows FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON request_engine.agent_budget_windows
            TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.upsert_agent_policy(
            p_agent_principal_id uuid,
            p_allowed_capabilities text[],
            p_denied_capabilities text[],
            p_risk_ceiling text,
            p_max_mutations_per_minute integer,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_profile_status text;
            v_revision bigint;
            v_capability text;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'agent.manage_policy'
            );
            FOREACH v_capability IN ARRAY p_allowed_capabilities
            LOOP
                IF v_capability IS NULL
                   OR length(btrim(v_capability)) = 0
                   OR length(v_capability) > 200
                THEN
                    RAISE EXCEPTION 'Invalid agent policy capability key'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
            FOREACH v_capability IN ARRAY p_denied_capabilities
            LOOP
                IF v_capability IS NULL
                   OR length(btrim(v_capability)) = 0
                   OR length(v_capability) > 200
                THEN
                    RAISE EXCEPTION 'Invalid agent policy capability key'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
            IF p_agent_principal_id = v_actor_id
               OR p_risk_ceiling NOT IN (
                    'read',
                    'low_impact_write',
                    'reversible_write',
                    'external_commitment',
                    'sensitive_data',
                    'financial',
                    'destructive'
               )
               OR p_max_mutations_per_minute IS NULL
               OR p_max_mutations_per_minute <= 0
               OR p_allowed_capabilities && p_denied_capabilities
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Invalid agent policy input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT status
              INTO v_profile_status
              FROM request_engine.agent_profiles
             WHERE principal_id = p_agent_principal_id
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile_status NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'Suspended or revoked agents cannot receive policy'
                    USING ERRCODE = '55000';
            END IF;

            INSERT INTO request_engine.agent_policies (
                organization_id,
                agent_principal_id,
                allowed_capabilities,
                denied_capabilities,
                risk_ceiling,
                max_mutations_per_minute,
                provenance_reference
            ) VALUES (
                v_org_id,
                p_agent_principal_id,
                p_allowed_capabilities,
                p_denied_capabilities,
                p_risk_ceiling,
                p_max_mutations_per_minute,
                p_provenance_reference
            )
            ON CONFLICT (organization_id, agent_principal_id)
            DO UPDATE SET
                allowed_capabilities = EXCLUDED.allowed_capabilities,
                denied_capabilities = EXCLUDED.denied_capabilities,
                risk_ceiling = EXCLUDED.risk_ceiling,
                max_mutations_per_minute = EXCLUDED.max_mutations_per_minute,
                provenance_reference = EXCLUDED.provenance_reference,
                policy_revision = request_engine.agent_policies.policy_revision + 1,
                updated_at = clock_timestamp()
            RETURNING policy_revision INTO v_revision;
            RETURN v_revision;
        END
        $$;
        ALTER FUNCTION request_engine.upsert_agent_policy(
            uuid, text[], text[], text, integer, text
        )
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.upsert_agent_policy(
            uuid, text[], text[], text, integer, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.upsert_agent_policy(
            uuid, text[], text[], text, integer, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS request_engine.upsert_agent_policy(
            uuid, text[], text[], text, integer, text
        );
        DROP TABLE IF EXISTS request_engine.agent_budget_windows;
        DROP TABLE IF EXISTS request_engine.agent_policies;
        """
    )
