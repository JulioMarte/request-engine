"""Strengthen tenant references without inventing tenant membership for platform actors.

Tenancy owns this additive HARD isolation backstop. The accepted platform/tenant
Principal identity is immutable (0002); bindings are also scope-immutable (0006).
Composite FKs protect tenant subjects, parties and binding ownership. Original
single-ID FKs remain useful for nullable platform rows and referential existence.
Provenance may reference a platform Principal, but never a different tenant.

No business workflow/authority is granted here. INSERT/UPDATE structural checks
run in the caller's transaction; FK parent locks and immutable Principal scope
prevent check/use races. There is no network I/O or emitted business effect.
Preflight rejects inconsistent existing provenance rather than rewriting history.
DDL is transactional and validates existing rows; deploy in a maintenance window
for large tables (unique indexes and ALTER TABLE locks), with bounded lock wait.
Downgrade removes only these additive backstops, preserving all data and old FKs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_tenant_reference_integrity"
down_revision: str | Sequence[str] | None = "0028_oidc_authority_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Explicit relational edges, not a policy registry. The binding FK also proves
# that a same-tenant binding belongs to the specified controller/staff Principal.
_TENANT_FKS = (
    ("identity_bindings", "binding_principal_tenant_fk", "principal_id", "principals", "id"),
    ("principal_authority_grants", "grant_principal_tenant_fk", "principal_id", "principals", "id"),
    (
        "organization_root_provisioning_facts",
        "root_party_tenant_fk",
        "organization_party_id",
        "parties",
        "id",
    ),
    (
        "organization_root_provisioning_facts",
        "root_principal_tenant_fk",
        "controller_principal_id",
        "principals",
        "id",
    ),
    (
        "organization_root_provisioning_facts",
        "root_binding_tenant_fk",
        "controller_principal_id, controller_binding_id",
        "identity_bindings",
        "principal_id, id",
    ),
    ("staff_memberships", "staff_principal_tenant_fk", "principal_id", "principals", "id"),
    (
        "staff_memberships",
        "staff_binding_tenant_fk",
        "principal_id, identity_binding_id",
        "identity_bindings",
        "principal_id, id",
    ),
    ("staff_memberships", "staff_anchor_tenant_fk", "authority_anchor_party_id", "parties", "id"),
)
_PROVENANCE_TABLES = (
    "organization_provisioning_facts",
    "organization_root_provisioning_facts",
    "staff_memberships",
    "principal_authority_grants",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "LOCK TABLE request_engine.organization_provisioning_facts, "
        "request_engine.organization_root_provisioning_facts, "
        "request_engine.staff_memberships, request_engine.principal_authority_grants "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute(
        "ALTER TABLE request_engine.identity_bindings "
        "ADD CONSTRAINT identity_bindings_tenant_principal_id_uq "
        "UNIQUE (organization_id, principal_id, id)"
    )
    for table, name, columns, target, target_columns in _TENANT_FKS:
        op.execute(
            f"ALTER TABLE request_engine.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (organization_id, {columns}) "
            f"REFERENCES request_engine.{target} (organization_id, {target_columns})"
        )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_authority_reference_tenant()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_ids uuid[];
            v_actor_id uuid;
            v_actor_org uuid;
            v_platform_only boolean := false;
        BEGIN
            CASE TG_TABLE_NAME
                WHEN 'organization_provisioning_facts',
                     'organization_root_provisioning_facts' THEN
                    v_actor_ids := ARRAY[NEW.provisioned_by_principal_id];
                    v_platform_only := true;
                WHEN 'staff_memberships' THEN
                    v_actor_ids := ARRAY[NEW.established_by_principal_id];
                    v_platform_only := NEW.provenance_kind = 'root_provisioning';
                WHEN 'principal_authority_grants' THEN
                    v_actor_ids := ARRAY[
                        NEW.granted_by_principal_id, NEW.revoked_by_principal_id
                    ];
                ELSE
                    RAISE EXCEPTION 'Unsupported authority reference relation'
                        USING ERRCODE = '23514';
            END CASE;
            FOREACH v_actor_id IN ARRAY v_actor_ids LOOP
                IF v_actor_id IS NULL THEN CONTINUE; END IF;
                SELECT organization_id INTO v_actor_org
                  FROM request_engine.principals WHERE id = v_actor_id;
                IF NOT FOUND
                   OR (v_platform_only AND v_actor_org IS NOT NULL)
                   OR (NOT v_platform_only AND v_actor_org IS NOT NULL
                       AND v_actor_org IS DISTINCT FROM NEW.organization_id)
                THEN
                    RAISE EXCEPTION 'Authority provenance cannot cross tenant boundaries'
                        USING ERRCODE = '23514';
                END IF;
                IF TG_TABLE_NAME = 'staff_memberships'
                   AND NOT v_platform_only AND v_actor_org IS NULL THEN
                    RAISE EXCEPTION 'Staff invitation requires tenant-local provenance'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_authority_reference_tenant()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_engine.guard_authority_reference_tenant() FROM PUBLIC;

        -- Validate historical rows without firing lifecycle updates or changing
        -- append-preserving facts. Parent scope cannot subsequently be retargeted.
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM (
                    SELECT organization_id, provisioned_by_principal_id AS actor_id,
                           true AS platform_only, false AS tenant_only
                      FROM request_engine.organization_provisioning_facts
                    UNION ALL
                    SELECT organization_id, provisioned_by_principal_id, true, false
                      FROM request_engine.organization_root_provisioning_facts
                    UNION ALL
                    SELECT organization_id, established_by_principal_id,
                           provenance_kind = 'root_provisioning',
                           provenance_kind = 'staff_invitation'
                      FROM request_engine.staff_memberships
                    UNION ALL
                    SELECT organization_id, actor_id, false, false
                      FROM request_engine.principal_authority_grants
                      CROSS JOIN LATERAL unnest(ARRAY[
                          granted_by_principal_id, revoked_by_principal_id
                      ]) AS actors(actor_id)
                ) AS refs
                LEFT JOIN request_engine.principals p ON p.id = refs.actor_id
                WHERE refs.actor_id IS NOT NULL AND (
                    p.id IS NULL
                    OR (refs.platform_only AND p.organization_id IS NOT NULL)
                    OR (refs.tenant_only AND p.organization_id IS NULL)
                    OR (NOT refs.platform_only AND p.organization_id IS NOT NULL
                        AND p.organization_id IS DISTINCT FROM refs.organization_id)
                )
            ) THEN
                RAISE EXCEPTION 'Existing authority provenance violates tenant scope'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        """
    )
    for table in _PROVENANCE_TABLES:
        op.execute(
            f"CREATE TRIGGER authority_reference_tenant_guard "
            f"BEFORE INSERT OR UPDATE ON request_engine.{table} "
            "FOR EACH ROW EXECUTE FUNCTION request_engine.guard_authority_reference_tenant()"
        )


def downgrade() -> None:
    for table in reversed(_PROVENANCE_TABLES):
        op.execute(f"DROP TRIGGER authority_reference_tenant_guard ON request_engine.{table}")
    op.execute("DROP FUNCTION request_engine.guard_authority_reference_tenant()")
    for table, name, *_ in reversed(_TENANT_FKS):
        op.execute(f"ALTER TABLE request_engine.{table} DROP CONSTRAINT {name}")
    op.execute(
        "ALTER TABLE request_engine.identity_bindings "
        "DROP CONSTRAINT identity_bindings_tenant_principal_id_uq"
    )
