"""Establish platform/tenant Principal planes and authority revisioning.

Revision ID: 0002_principal_trust_root
Revises: 0001_initial
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_principal_trust_root"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE request_engine.principals "
        "ADD COLUMN principal_plane text NOT NULL DEFAULT 'tenant'"
    )
    op.execute(
        "ALTER TABLE request_engine.principals "
        "ADD COLUMN authority_revision bigint NOT NULL DEFAULT 1"
    )
    op.execute("ALTER TABLE request_engine.principals ALTER COLUMN organization_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE request_engine.principals "
        "ADD CONSTRAINT principals_principal_plane_check "
        "CHECK (principal_plane IN ('tenant', 'platform'))"
    )
    op.execute(
        "ALTER TABLE request_engine.principals "
        "ADD CONSTRAINT principals_plane_organization_check CHECK ("
        "(principal_plane = 'tenant' AND organization_id IS NOT NULL) OR "
        "(principal_plane = 'platform' AND organization_id IS NULL))"
    )
    op.execute(
        "ALTER TABLE request_engine.principals "
        "ADD CONSTRAINT principals_authority_revision_check "
        "CHECK (authority_revision > 0)"
    )
    op.execute(
        "CREATE UNIQUE INDEX principals_platform_subject_uq "
        "ON request_engine.principals (principal_kind, external_subject) "
        "WHERE principal_plane = 'platform'"
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_principal_security_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_security_fact_changed boolean;
        BEGIN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.principal_plane IS DISTINCT FROM OLD.principal_plane
            THEN
                RAISE EXCEPTION 'Principal authority plane and tenant cannot be retargeted'
                    USING ERRCODE = '55000';
            END IF;

            v_security_fact_changed :=
                NEW.active IS DISTINCT FROM OLD.active
                OR NEW.principal_kind IS DISTINCT FROM OLD.principal_kind
                OR NEW.external_subject IS DISTINCT FROM OLD.external_subject;

            IF NEW.authority_revision = OLD.authority_revision THEN
                IF v_security_fact_changed THEN
                    NEW.authority_revision := OLD.authority_revision + 1;
                END IF;
            ELSIF NEW.authority_revision <> OLD.authority_revision + 1 THEN
                RAISE EXCEPTION 'Principal authority_revision must advance exactly one step'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION request_engine.guard_principal_security_identity() "
        "OWNER TO request_engine_schema_owner"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION request_engine.guard_principal_security_identity() FROM PUBLIC"
    )
    op.execute(
        "CREATE TRIGGER principals_guard_security_identity "
        "BEFORE UPDATE ON request_engine.principals FOR EACH ROW "
        "EXECUTE FUNCTION request_engine.guard_principal_security_identity()"
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.bump_principal_authority_from_representation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                UPDATE request_engine.principals
                   SET authority_revision = authority_revision + 1
                 WHERE organization_id = OLD.organization_id
                   AND id = OLD.principal_id;
                RETURN OLD;
            END IF;

            IF TG_OP = 'UPDATE'
               AND (
                   NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
               )
            THEN
                UPDATE request_engine.principals
                   SET authority_revision = authority_revision + 1
                 WHERE organization_id = OLD.organization_id
                   AND id = OLD.principal_id;
            END IF;

            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE organization_id = NEW.organization_id
               AND id = NEW.principal_id;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION request_engine.bump_principal_authority_from_representation() "
        "OWNER TO request_engine_schema_owner"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "request_engine.bump_principal_authority_from_representation() FROM PUBLIC"
    )
    op.execute(
        "CREATE TRIGGER representations_bump_principal_authority "
        "AFTER INSERT OR UPDATE OR DELETE ON request_engine.representations FOR EACH ROW "
        "EXECUTE FUNCTION request_engine.bump_principal_authority_from_representation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER representations_bump_principal_authority ON request_engine.representations"
    )
    op.execute("DROP FUNCTION request_engine.bump_principal_authority_from_representation()")
    op.execute("DROP TRIGGER principals_guard_security_identity ON request_engine.principals")
    op.execute("DROP FUNCTION request_engine.guard_principal_security_identity()")
    op.execute("DROP INDEX request_engine.principals_platform_subject_uq")
    op.execute("ALTER TABLE request_engine.principals ALTER COLUMN organization_id SET NOT NULL")
    op.execute(
        "ALTER TABLE request_engine.principals DROP CONSTRAINT principals_authority_revision_check"
    )
    op.execute(
        "ALTER TABLE request_engine.principals DROP CONSTRAINT principals_plane_organization_check"
    )
    op.execute(
        "ALTER TABLE request_engine.principals DROP CONSTRAINT principals_principal_plane_check"
    )
    op.execute("ALTER TABLE request_engine.principals DROP COLUMN authority_revision")
    op.execute("ALTER TABLE request_engine.principals DROP COLUMN principal_plane")
