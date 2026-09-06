"""Remove pre-launch legacy Resource location and availability schema.

Revision ID: 0048_remove_legacy_location
Revises: 0047_remove_waitlist_index
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_remove_legacy_location"
down_revision: str | Sequence[str] | None = "0047_remove_waitlist_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE_COMMITMENT_GUARD = r"""
CREATE OR REPLACE FUNCTION request_engine.guard_resource_commitment_sensitive_change()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_live_claims bigint;
BEGIN
    IF NEW.capacity_model = OLD.capacity_model
       AND NEW.capacity_units = OLD.capacity_units
       AND NEW.active = OLD.active THEN
        RETURN NEW;
    END IF;

    SELECT count(*)
      INTO v_live_claims
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = OLD.organization_id
       AND c.resource_id = OLD.id
       AND c.status = 'active'
       AND (
           (
               c.reservation_id IS NOT NULL
               AND r.status = 'confirmed'
               AND upper(c.during) > clock_timestamp()
           ) OR
           (
               c.reservation_id IS NULL
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
           )
       );

    IF v_live_claims > 0 THEN
        RAISE EXCEPTION 'Resource % has live capacity commitments; capacity/active change requires explicit commitment handling', OLD.id
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;
"""


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute("DROP TABLE request_engine.availability_schedules")
    op.execute(_RESOURCE_COMMITMENT_GUARD)
    op.execute("ALTER TABLE request_engine.resources DROP COLUMN location_id")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("pre-launch legacy Resource location removal is not reversible")
