"""Add bounded Principal-to-Agent task delegations.

Revision ID: 0025_delegation_grants
Revises: 0024_agent_governance
Create Date: 2026-09-08

A DelegationGrant is temporary, bounded authority that a delegator lends from
its own current delegable operational authority to an AGENT Principal. It is
never a standing grant and never a copy of the delegator's authority. Effective
delegated authority is resolved by intersection at execution time:
agent current authority ∩ delegation grant ∩ delegator current delegable
authority. Revocation and expiry fail closed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_delegation_grants"
down_revision: str | Sequence[str] | None = "0024_agent_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.delegations (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL
                REFERENCES request_engine.organizations(id),
            delegator_principal_id uuid NOT NULL,
            delegate_principal_id uuid NOT NULL,
            purpose text NOT NULL,
            allowed_capabilities text[] NOT NULL,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            revoked_at timestamptz,
            revoked_by_principal_id uuid,
            CONSTRAINT delegations_purpose_check
                CHECK (length(btrim(purpose)) BETWEEN 1 AND 500),
            CONSTRAINT delegations_provenance_reference_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT delegations_status_check
                CHECK (status IN ('active', 'revoked')),
            CONSTRAINT delegations_revision_check CHECK (revision > 0),
            CONSTRAINT delegations_window_check CHECK (expires_at > not_before),
            CONSTRAINT delegations_self_check
                CHECK (delegator_principal_id <> delegate_principal_id),
            CONSTRAINT delegations_capabilities_check
                CHECK (cardinality(allowed_capabilities) > 0),
            CONSTRAINT delegations_revocation_check CHECK (
                (status = 'revoked'
                    AND revoked_at IS NOT NULL
                    AND revoked_by_principal_id IS NOT NULL)
                OR (status = 'active'
                    AND revoked_at IS NULL
                    AND revoked_by_principal_id IS NULL)
            ),
            FOREIGN KEY (organization_id, delegator_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            FOREIGN KEY (organization_id, delegate_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            FOREIGN KEY (organization_id, revoked_by_principal_id)
                REFERENCES request_engine.principals(organization_id, id)
        );
        CREATE INDEX delegations_delegate_active_idx
            ON request_engine.delegations (delegate_principal_id, status, expires_at);
        ALTER TABLE request_engine.delegations
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.delegations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.delegations FORCE ROW LEVEL SECURITY;
        CREATE POLICY delegations_tenant_isolation
            ON request_engine.delegations
            USING (
                organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.delegations FROM PUBLIC;
        GRANT SELECT ON request_engine.delegations TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_delegation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_delegate_kind text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Delegations are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.organization_id,
                    NEW.delegator_principal_id,
                    NEW.delegate_principal_id,
                    NEW.purpose,
                    NEW.allowed_capabilities,
                    NEW.not_before,
                    NEW.expires_at,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.organization_id,
                    OLD.delegator_principal_id,
                    OLD.delegate_principal_id,
                    OLD.purpose,
                    OLD.allowed_capabilities,
                    OLD.not_before,
                    OLD.expires_at,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Delegation identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status = 'active' AND NEW.status = 'revoked' THEN
                    IF NEW.revision <> OLD.revision + 1 THEN
                        RAISE EXCEPTION 'Invalid delegation revocation'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Invalid delegation state transition'
                    USING ERRCODE = '55000';
            END IF;

            SELECT principal_kind
              INTO v_delegate_kind
              FROM request_engine.principals
             WHERE organization_id = NEW.organization_id
               AND id = NEW.delegate_principal_id;
            IF NOT FOUND OR v_delegate_kind <> 'agent' THEN
                RAISE EXCEPTION 'Delegation delegate must be a tenant AGENT Principal'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_delegation()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_delegation() FROM PUBLIC;
        CREATE TRIGGER delegations_guard
            BEFORE INSERT OR UPDATE OR DELETE
            ON request_engine.delegations
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_delegation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.create_delegation(
            p_id uuid,
            p_delegator_principal_id uuid,
            p_delegate_principal_id uuid,
            p_purpose text,
            p_allowed_capabilities text[],
            p_not_before timestamptz,
            p_expires_at timestamptz,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_capability text;
            v_plane text;
        BEGIN
            v_actor_id := current_setting(
                'request_engine.authenticated_principal_id', true
            )::uuid;
            IF v_actor_id IS NULL
               OR v_actor_id <> p_delegator_principal_id
               OR p_delegator_principal_id = p_delegate_principal_id
               OR length(btrim(p_purpose)) = 0
               OR length(btrim(p_provenance_reference)) = 0
               OR p_not_before IS NULL
               OR p_expires_at IS NULL
               OR p_expires_at <= p_not_before
               OR cardinality(COALESCE(p_allowed_capabilities, ARRAY[]::text[])) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(p_allowed_capabilities) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(p_allowed_capabilities) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(p_allowed_capabilities) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Invalid delegation input' USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap FROM unnest(p_allowed_capabilities) AS cap
            LOOP
                SELECT authority_plane
                  INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane <> 'operational' THEN
                    RAISE EXCEPTION
                        'Delegation exceeds the delegator operational ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            INSERT INTO request_engine.delegations (
                id,
                organization_id,
                delegator_principal_id,
                delegate_principal_id,
                purpose,
                allowed_capabilities,
                not_before,
                expires_at,
                provenance_reference
            ) VALUES (
                p_id,
                v_org_id,
                p_delegator_principal_id,
                p_delegate_principal_id,
                btrim(p_purpose),
                p_allowed_capabilities,
                p_not_before,
                p_expires_at,
                btrim(p_provenance_reference)
            );
            RETURN 1;
        END
        $$;
        ALTER FUNCTION request_engine.create_delegation(
            uuid, uuid, uuid, text, text[], timestamptz, timestamptz, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.create_delegation(
            uuid, uuid, uuid, text, text[], timestamptz, timestamptz, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.create_delegation(
            uuid, uuid, uuid, text, text[], timestamptz, timestamptz, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.revoke_delegation(
            p_id uuid,
            p_expected_revision bigint,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_delegator uuid;
            v_status text;
            v_delegate uuid;
            v_revision bigint;
        BEGIN
            v_actor_id := current_setting(
                'request_engine.authenticated_principal_id', true
            )::uuid;
            SELECT delegator_principal_id, status, delegate_principal_id, revision
              INTO v_delegator, v_status, v_delegate, v_revision
              FROM request_engine.delegations
             WHERE id = p_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Delegation not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_actor_id IS NULL
               OR v_actor_id NOT IN (v_delegator, v_delegate)
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Only the delegator or delegate may revoke'
                    USING ERRCODE = '42501';
            END IF;
            IF v_status <> 'active' THEN
                RAISE EXCEPTION 'Delegation is already revoked'
                    USING ERRCODE = '55000';
            END IF;
            IF v_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Delegation revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            UPDATE request_engine.delegations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE id = p_id;
            RETURN p_expected_revision + 1;
        END
        $$;
        ALTER FUNCTION request_engine.revoke_delegation(uuid, bigint, text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.revoke_delegation(uuid, bigint, text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.revoke_delegation(uuid, bigint, text)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_engine.revoke_delegation(uuid, bigint, text)")
    op.execute(
        "DROP FUNCTION request_engine.create_delegation("
        "uuid, uuid, uuid, text, text[], timestamptz, timestamptz, text)"
    )
    op.execute("DROP TRIGGER delegations_guard ON request_engine.delegations")
    op.execute("DROP FUNCTION request_engine.guard_delegation()")
    op.execute("DROP TABLE request_engine.delegations CASCADE")
