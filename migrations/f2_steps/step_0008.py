"""Preserve F2 idempotent replay and fence current OfferingVersion.

Revision ID: 0008_f2_handoff_fence
Revises: 0007_f2_taxonomy_acl
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_f2_handoff_fence"
down_revision: str | Sequence[str] | None = "0007_f2_taxonomy_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
ALTER TABLE request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_consumed_reservation_fk
    FOREIGN KEY (organization_id, consumed_reservation_id)
    REFERENCES request_engine.reservations (organization_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text)
RETURNS TABLE (handoff_id uuid, organization_id uuid, selection jsonb)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT h.id, h.organization_id, h.selection
      FROM request_engine.discovery_booking_handoffs h
     WHERE h.token_hash = p_token_hash
       AND h.organization_id = request_engine.current_organization_id()
       AND (h.consumed_reservation_id IS NOT NULL OR h.expires_at > now())
$function$;
ALTER FUNCTION request_engine.read_discovery_booking_handoff(text)
    OWNER TO request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.read_discovery_booking_handoff(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.read_discovery_booking_handoff(text)
TO request_engine_app;

CREATE FUNCTION request_engine.guard_discovery_handoff_latest_version()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_handoff_id uuid;
    v_offering_id uuid;
    v_latest_id uuid;
    v_latest_bookable boolean;
BEGIN
    BEGIN
        v_handoff_id := NULLIF(
            current_setting('request_engine.discovery_handoff_id', true), ''
        )::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid discovery handoff context' USING ERRCODE = '22023';
    END;
    IF v_handoff_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT dp.offering_id
      INTO v_offering_id
      FROM request_engine.discovery_booking_handoffs h
      JOIN request_engine.discovery_publications dp
        ON dp.organization_id = h.organization_id
       AND dp.id = h.publication_id
     WHERE h.id = v_handoff_id
       AND h.organization_id = NEW.organization_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    PERFORM 1
      FROM request_engine.offerings o
     WHERE o.organization_id = NEW.organization_id
       AND o.id = v_offering_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT ov.id, ov.bookable
      INTO v_latest_id, v_latest_bookable
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = NEW.organization_id
       AND ov.offering_id = v_offering_id
     ORDER BY ov.version DESC
     LIMIT 1;
    IF NOT FOUND OR v_latest_id <> NEW.offering_version_id OR NOT v_latest_bookable THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END
$function$;
ALTER FUNCTION request_engine.guard_discovery_handoff_latest_version()
    OWNER TO request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.guard_discovery_handoff_latest_version() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.guard_discovery_handoff_latest_version()
TO request_engine_schema_owner;

SET ROLE request_engine_schema_owner;
CREATE TRIGGER reservations_guard_discovery_latest_version
BEFORE INSERT ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_discovery_handoff_latest_version();
RESET ROLE;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0008 preserves F2 replay and current-version fencing")
