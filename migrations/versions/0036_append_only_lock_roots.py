"""Move append-only synchronization to mutable aggregate roots.

Revision ID: 0036_append_only_lock_roots
Revises: 0035_schema_cohesion_hardening
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036_append_only_lock_roots"
down_revision: str | Sequence[str] | None = "0035_schema_cohesion_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.lock_offering_version_booking_terms_root()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        DECLARE
            v_org uuid;
            v_offering_version uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                v_org := OLD.organization_id;
                v_offering_version := OLD.offering_version_id;
            ELSE
                v_org := NEW.organization_id;
                v_offering_version := NEW.offering_version_id;
            END IF;

            PERFORM 1
              FROM request_engine.offering_versions ov
              JOIN request_engine.offerings o
                ON o.organization_id = ov.organization_id
               AND o.id = ov.offering_id
             WHERE ov.organization_id = v_org
               AND ov.id = v_offering_version
             FOR UPDATE OF o;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'OfferingVersion % not found while changing base booking terms',
                    v_offering_version USING ERRCODE = '23503';
            END IF;

            RETURN COALESCE(NEW, OLD);
        END
        $function$;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("append-only lock-root hardening is not reversible")
