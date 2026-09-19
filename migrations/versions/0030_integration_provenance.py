"""Preserve integration governance facts and add bounded credential replacement.

Revises 0029_tenant_reference_integrity. Existing 0027 entry points retain their
signatures; their implementations become owner-only and the public boundaries
append immutable facts atomically. No bearer secret or digest enters provenance.
Existing integrations receive an explicitly unattributed legacy snapshot: missing
historical creator evidence cannot honestly be reconstructed by a migration.

Lock order: authenticated HUMAN/staff/control grant, integration Principal,
workload identity, credentials. Python continues to own transaction framing,
idempotency, secret generation and transport/application validation.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030_integration_provenance"
down_revision: str | Sequence[str] | None = "0029_tenant_reference_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE request_engine.integration_governance_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL,
            integration_principal_id uuid NOT NULL,
            actor_principal_id uuid,
            actor_authority_revision bigint,
            operation text NOT NULL CHECK (operation IN (
                'provision', 'authority_replace', 'status_transition',
                'credential_rotate', 'legacy_snapshot'
            )),
            provenance_reference text NOT NULL
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            policy_version text NOT NULL DEFAULT 'integration-governance/1',
            authority_revision bigint NOT NULL CHECK (authority_revision > 0),
            snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT integration_facts_target_fk
                FOREIGN KEY (organization_id, integration_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            CONSTRAINT integration_facts_actor_fk
                FOREIGN KEY (organization_id, actor_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            CONSTRAINT integration_facts_attribution_check CHECK (
                (operation = 'legacy_snapshot' AND actor_principal_id IS NULL
                 AND actor_authority_revision IS NULL)
                OR (operation <> 'legacy_snapshot' AND actor_principal_id IS NOT NULL
                    AND actor_authority_revision IS NOT NULL AND actor_authority_revision > 0)
            )
        );
        CREATE INDEX integration_facts_history_idx
            ON request_engine.integration_governance_facts
            (organization_id, integration_principal_id, occurred_at, id);
        ALTER TABLE request_engine.integration_governance_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.integration_governance_facts
            FROM PUBLIC, request_engine_app;
        INSERT INTO request_engine.integration_governance_facts (
            organization_id, integration_principal_id, operation,
            provenance_reference, authority_revision, snapshot
        ) SELECT organization_id, id, 'legacy_snapshot',
                 '0030: historical creator not recorded by 0027', authority_revision,
                 jsonb_build_object('active', active, 'historical_creator_known', false)
            FROM request_engine.principals
           WHERE principal_kind = 'integration' AND principal_plane = 'tenant';
        ALTER TABLE request_engine.integration_governance_facts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.integration_governance_facts FORCE ROW LEVEL SECURITY;
        CREATE POLICY integration_facts_tenant_isolation
            ON request_engine.integration_governance_facts
            USING (organization_id = request_engine.current_organization_id())
            WITH CHECK (organization_id = request_engine.current_organization_id());

        CREATE FUNCTION request_engine.guard_integration_fact() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO 'pg_catalog', 'pg_temp' AS $$
        BEGIN
            RAISE EXCEPTION 'Integration provenance is immutable and append-preserving'
                USING ERRCODE = '55000';
        END $$;
        ALTER FUNCTION request_engine.guard_integration_fact()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_integration_fact() FROM PUBLIC;
        CREATE TRIGGER integration_facts_immutable
            BEFORE UPDATE OR DELETE ON request_engine.integration_governance_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_integration_fact();

        CREATE FUNCTION request_engine.append_integration_fact(
            p_principal_id uuid, p_actor_id uuid, p_operation text,
            p_reference text, p_capability text
        ) RETURNS void LANGUAGE sql
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
            INSERT INTO request_engine.integration_governance_facts (
                organization_id, integration_principal_id, actor_principal_id,
                actor_authority_revision, operation, provenance_reference,
                authority_revision, snapshot
            )
            SELECT pr.organization_id, pr.id, actor.id, actor.authority_revision,
                   p_operation, btrim(p_reference), pr.authority_revision,
                   jsonb_build_object(
                       'authority_source', p_capability,
                       'active', pr.active,
                       'grants', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'delegable', g.delegable, 'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = pr.id AND g.status = 'active'
                       ), '[]'::jsonb),
                       'delegable_ceiling', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = actor.id AND g.status = 'active'
                             AND g.delegable AND g.authority_plane = 'operational'
                       ), '[]'::jsonb),
                       'bindings', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', b.id, 'authority_id', b.identity_authority_id,
                               'subject_id', b.subject_id, 'status', b.status,
                               'revision', b.revision
                           ) ORDER BY b.id)
                           FROM request_engine.identity_bindings b
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id
                       ), '[]'::jsonb),
                       'credentials', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', c.id, 'status', c.status, 'expires_at', c.expires_at
                           ) ORDER BY c.id)
                           FROM request_engine.identity_bindings b
                           JOIN request_engine.workload_credentials c
                             ON c.workload_identity_id::text = b.subject_id
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id AND c.status = 'active'
                       ), '[]'::jsonb)
                   )
              FROM request_engine.principals pr
              JOIN request_engine.principals actor
                ON actor.id = p_actor_id AND actor.organization_id = pr.organization_id
             WHERE pr.id = p_principal_id
               AND pr.organization_id = request_engine.current_organization_id()
        $$;
        ALTER FUNCTION request_engine.append_integration_fact(uuid, uuid, text, text, text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.append_integration_fact(
            uuid, uuid, text, text, text
        ) FROM PUBLIC, request_engine_app;

        CREATE FUNCTION request_cmd.assert_integration_manager(p_capability text)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        BEGIN
            IF p_capability IS NULL OR p_capability NOT IN (
                'integration.provision', 'integration.manage_authority', 'integration.suspend'
            ) THEN
                RAISE EXCEPTION 'Unsupported integration control capability'
                    USING ERRCODE = '22023';
            END IF;
            RETURN request_engine.assert_staff_manager(p_capability);
        END $$;
        ALTER FUNCTION request_cmd.assert_integration_manager(text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.assert_integration_manager(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.assert_integration_manager(text)
            TO request_engine_app;
    """)
    _protect_existing_operations()
    _credential_rotation()
    _inspection()


def _protect_existing_operations() -> None:
    # These compatibility boundaries preserve applied SQL contracts, make audit
    # mandatory even for SQL callers, and do not duplicate their business workflow.
    operations = (
        (
            "provision_integration",
            "uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, text",
            "p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, "
            "p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, "
            "p_token_fingerprint text, p_credential_expires_at timestamptz, "
            "p_provenance_reference text",
            "p_principal_id, p_binding_id, p_workload_identity_id, p_credential_id, "
            "p_identity_authority_id, p_token_digest, p_token_fingerprint, "
            "p_credential_expires_at, p_provenance_reference",
            "'integration.provision'",
            "provision",
            """
                IF EXISTS (SELECT 1 FROM request_engine.principals WHERE id = p_principal_id)
                THEN
                    RAISE EXCEPTION 'Provisioning identifier already exists'
                        USING ERRCODE = '23505';
                END IF;
            """,
        ),
        (
            "replace_integration_authority",
            "uuid, bigint, text[], text",
            "p_principal_id uuid, p_expected_authority_revision bigint, "
            "p_desired_capabilities text[], p_provenance_reference text",
            "p_principal_id, p_expected_authority_revision, "
            "p_desired_capabilities, p_provenance_reference",
            "'integration.manage_authority'",
            "authority_replace",
            """
                IF p_expected_authority_revision IS NULL OR p_expected_authority_revision < 1
                   OR p_desired_capabilities IS NULL
                   OR array_position(p_desired_capabilities, NULL) IS NOT NULL
                   OR cardinality(p_desired_capabilities) > 128 THEN
                    RAISE EXCEPTION 'Invalid integration authority input'
                        USING ERRCODE = '22023';
                END IF;
            """,
        ),
        (
            "set_integration_status",
            "uuid, bigint, text, text",
            "p_principal_id uuid, p_expected_revision bigint, "
            "p_target_status text, p_provenance_reference text",
            "p_principal_id, p_expected_revision, p_target_status, p_provenance_reference",
            "CASE WHEN p_target_status = 'active' THEN 'integration.provision' "
            "ELSE 'integration.suspend' END",
            "status_transition",
            """
                IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                    RAISE EXCEPTION 'Invalid integration revision' USING ERRCODE = '22023';
                END IF;
            """,
        ),
    )
    for name, signature, parameters, arguments, capability, operation, validation in operations:
        op.execute(f"""
            ALTER FUNCTION request_engine.{name}({signature}) RENAME TO {name}_state;
            REVOKE ALL ON FUNCTION request_engine.{name}_state({signature})
                FROM PUBLIC, request_engine_app;
            CREATE FUNCTION request_engine.{name}({parameters}) RETURNS bigint
            LANGUAGE plpgsql SECURITY DEFINER
            SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := {capability};
            BEGIN
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                {validation}
                IF '{operation}' <> 'provision' THEN
                    SELECT authority_revision INTO v_before
                      FROM request_engine.principals
                     WHERE id = p_principal_id
                       AND organization_id = request_engine.current_organization_id()
                       AND principal_kind = 'integration' AND principal_plane = 'tenant'
                     FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Integration Principal not found' USING ERRCODE = 'P0002';
                    END IF;
                END IF;
                v_revision := request_engine.{name}_state({arguments});
                IF '{operation}' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, '{operation}', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $$;
            ALTER FUNCTION request_engine.{name}({signature})
                OWNER TO request_engine_schema_owner;
            REVOKE ALL ON FUNCTION request_engine.{name}({signature}) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION request_engine.{name}({signature}) TO request_engine_app;
        """)


def _credential_rotation() -> None:
    op.execute("""
        CREATE FUNCTION request_cmd.rotate_integration_credential(
            p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid,
            p_digest bytea, p_fingerprint text, p_expires_at timestamptz, p_reference text
        ) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        DECLARE
            v_actor uuid;
            v_revision bigint;
            v_identity uuid;
        BEGIN
            v_actor := request_engine.assert_staff_manager('integration.provision');
            SELECT authority_revision INTO v_revision FROM request_engine.principals
             WHERE id = p_principal_id AND principal_kind = 'integration'
               AND organization_id = request_engine.current_organization_id()
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration not found' USING ERRCODE = 'P0002';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1
               OR p_expires_at IS NULL OR p_expires_at <= clock_timestamp()
               OR p_credential_id IS NULL OR p_digest IS NULL OR octet_length(p_digest) <> 32
               OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_reference IS NULL OR length(btrim(p_reference)) NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Invalid credential replacement input' USING ERRCODE = '22023';
            END IF;
            IF v_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Integration revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT wi.id INTO v_identity
              FROM request_engine.workload_identities wi
              JOIN request_engine.identity_bindings b
                ON b.subject_id = wi.id::text AND b.identity_authority_id = wi.identity_authority_id
              JOIN request_engine.identity_authorities ia ON ia.id = wi.identity_authority_id
             WHERE b.principal_id = p_principal_id
               AND b.organization_id = request_engine.current_organization_id()
               AND b.status IN ('pending', 'active', 'suspended')
               AND wi.status = 'active' AND wi.workload_kind = 'integration'
               AND ia.status = 'active' AND ia.kind = 'workload'
             FOR UPDATE OF wi FOR SHARE OF b, ia;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Revoked integration or inactive identity authority'
                    USING ERRCODE = '55000';
            END IF;
            UPDATE request_engine.workload_credentials
               SET status = 'revoked', revision = revision + 1, revoked_at = clock_timestamp()
             WHERE workload_identity_id = v_identity AND status = 'active';
            INSERT INTO request_engine.workload_credentials (
                id, workload_identity_id, token_digest, token_fingerprint, expires_at
            ) VALUES (p_credential_id, v_identity, p_digest, p_fingerprint, p_expires_at);
            UPDATE request_engine.principals SET authority_revision = authority_revision + 1
             WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
            PERFORM request_engine.append_integration_fact(
                p_principal_id, v_actor, 'credential_rotate', p_reference, 'integration.provision'
            );
            RETURN v_revision;
        END $$;
        ALTER FUNCTION request_cmd.rotate_integration_credential(
            uuid, bigint, uuid, bytea, text, timestamptz, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.rotate_integration_credential(
            uuid, bigint, uuid, bytea, text, timestamptz, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.rotate_integration_credential(
            uuid, bigint, uuid, bytea, text, timestamptz, text
        ) TO request_engine_app;
    """)


def _inspection() -> None:
    op.execute("""
        CREATE FUNCTION request_read.integrations(
            p_principal_id uuid DEFAULT NULL, p_after uuid DEFAULT NULL, p_limit integer DEFAULT 50
        ) RETURNS TABLE (
            principal_id uuid, authority_revision bigint, status text,
            binding_id uuid, workload_identity_id uuid, identity_authority_id uuid,
            capabilities text[], credentials jsonb, provenance_complete boolean
        ) LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        BEGIN
            PERFORM request_engine.assert_staff_manager('integration.read');
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'Integration page size must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
                SELECT pr.id, pr.authority_revision, COALESCE(b.status, 'revoked'),
                       b.id, wi.id, b.identity_authority_id,
                       ARRAY(SELECT g.capability_key
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id AND g.principal_id = pr.id
                             AND g.status = 'active' ORDER BY g.capability_key),
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'credential_id', c.id, 'status', c.status,
                           'expires_at', c.expires_at, 'created_at', c.created_at
                       ) ORDER BY c.created_at, c.id)
                           FROM request_engine.workload_credentials c
                           WHERE c.workload_identity_id = wi.id
                             AND c.status = 'active'), '[]'::jsonb),
                       EXISTS (SELECT 1 FROM request_engine.integration_governance_facts f
                           WHERE f.organization_id = pr.organization_id
                             AND f.integration_principal_id = pr.id AND f.operation = 'provision')
                  FROM request_engine.principals pr
                  LEFT JOIN LATERAL (
                      SELECT ib.* FROM request_engine.identity_bindings ib
                       WHERE ib.organization_id = pr.organization_id AND ib.principal_id = pr.id
                       ORDER BY (ib.status <> 'revoked') DESC, ib.id LIMIT 1
                  ) b ON true
                  LEFT JOIN request_engine.workload_identities wi
                    ON wi.id::text = b.subject_id
                   AND wi.identity_authority_id = b.identity_authority_id
                 WHERE pr.organization_id = request_engine.current_organization_id()
                   AND pr.principal_kind = 'integration' AND pr.principal_plane = 'tenant'
                   AND (p_principal_id IS NULL OR pr.id = p_principal_id)
                   AND (p_after IS NULL OR pr.id > p_after)
                 ORDER BY pr.id LIMIT p_limit;
        END $$;
        ALTER FUNCTION request_read.integrations(uuid, uuid, integer)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_read.integrations(uuid, uuid, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_read.integrations(uuid, uuid, integer)
            TO request_engine_app;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Integration governance provenance is durable history; use a forward migration."
    )
