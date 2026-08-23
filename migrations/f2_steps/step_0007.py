"""Complete F2 taxonomy lookup and retirement authority.

Revision ID: 0007_f2_taxonomy_acl
Revises: 0006_f2_handoff
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_f2_taxonomy_acl"
down_revision: str | Sequence[str] | None = "0006_f2_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE FUNCTION request_engine.lookup_service_classification(p_id uuid)
RETURNS TABLE (id uuid, classification_key text, status text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT sc.id, sc.classification_key, sc.status
      FROM request_engine.service_classifications sc
     WHERE sc.id = p_id
$function$;
REVOKE ALL ON FUNCTION request_engine.lookup_service_classification(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.lookup_service_classification(uuid)
TO request_engine_app;

CREATE FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.offering_service_classifications m
         WHERE m.service_classification_id = p_classification_id
           AND m.status = 'active'
    )
$function$;
REVOKE ALL ON FUNCTION request_engine.has_active_discovery_mapping(uuid) FROM PUBLIC;

RESET ROLE;
ALTER FUNCTION request_engine.has_active_discovery_mapping(uuid)
    OWNER TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_engine.has_active_discovery_mapping(uuid)
TO request_engine_schema_owner;

SET ROLE request_engine_schema_owner;
SET search_path = request_admin, request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_admin.retire_service_classification(
    p_service_classification_id uuid,
    p_expected_revision bigint,
    p_authority_ref text,
    p_reason text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_revision bigint;
    v_status text;
BEGIN
    IF btrim(COALESCE(p_authority_ref, '')) = '' OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'authority_ref and reason are required' USING ERRCODE = '22023';
    END IF;
    SELECT revision, status INTO v_revision, v_status
      FROM request_engine.service_classifications
     WHERE id = p_service_classification_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceClassification not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status <> 'active' OR v_revision <> p_expected_revision THEN
        RAISE EXCEPTION 'ServiceClassification revision/status conflict' USING ERRCODE = '40001';
    END IF;
    IF request_engine.has_active_discovery_mapping(p_service_classification_id) THEN
        RAISE EXCEPTION 'active Offering mappings still reference ServiceClassification'
            USING ERRCODE = '55000';
    END IF;
    UPDATE request_engine.service_classifications
       SET status = 'retired', revision = revision + 1
     WHERE id = p_service_classification_id
     RETURNING revision INTO v_revision;
    INSERT INTO request_engine.service_classification_authority_events (
        service_classification_id, action, authority_ref, reason
    ) VALUES (p_service_classification_id, 'retired', p_authority_ref, p_reason);
    RETURN v_revision;
END
$function$;

REVOKE ALL ON FUNCTION
    request_engine.lookup_service_classification(uuid),
    request_engine.has_active_discovery_mapping(uuid)
FROM PUBLIC;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0007 preserves F2 taxonomy least-privilege corrections")
