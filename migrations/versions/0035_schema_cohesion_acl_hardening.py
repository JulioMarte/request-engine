"""Tighten runtime ACLs and remove schema-cohesion defects.

Revision ID: 0035_schema_cohesion_hardening
Revises: 0034_org_channel_policies
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035_schema_cohesion_hardening"
down_revision: str | Sequence[str] | None = "0034_org_channel_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_IMMUTABLE_APP_TABLES = (
    "attendance_responses",
    "audit_records",
    "offering_resource_requirements",
    "offering_version_booking_policies",
    "offering_version_booking_terms",
    "offering_versions",
    "operational_recovery_escalations",
    "operational_recovery_proposals",
    "queue_entry_operator_selections",
    "reminder_acknowledgements",
    "request_definition_versions",
    "reservation_commercial_commitment_context_terms",
    "reservation_commercial_commitments",
)

_SECURITY_DEFINERS = (
    ("request_engine.bind_consumed_identity_candidate_v1", "uuid, uuid, text[], uuid"),
    (
        "request_engine.consume_identity_exchange_candidate_v1",
        "uuid, text, text, text, uuid",
    ),
    ("request_engine.create_identity_exchange_candidate_v1", "text, text, text, uuid"),
    ("request_engine.identity_exchange_existing_party_v1", "uuid, uuid"),
    (
        "request_engine.publish_portable_party_v1",
        "uuid, text, text, text, text[], uuid",
    ),
    ("request_read.recovery_source_revision", "uuid, uuid"),
)

_DISCOVERY_DEFINERS = (
    ("request_engine.guard_discovery_handoff_latest_version", ""),
    ("request_engine.guard_discovery_handoff_reservation", ""),
    ("request_engine.has_active_discovery_mapping", "uuid"),
    (
        "request_engine.issue_discovery_booking_handoff",
        "text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz",
    ),
    ("request_engine.read_discovery_booking_handoff", "text"),
    (
        "request_engine.search_discovery_candidates_v2",
        "text, double precision, double precision, integer, timestamptz, timestamptz, integer",
    ),
)

_DISCOVERY_LOCK_RELATIONS = (
    "offerings",
    "offering_service_classifications",
    "discovery_publications",
)


def _function_ref(name: str, arguments: str) -> str:
    return f"{name}({arguments})"


def upgrade() -> None:
    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'request_engine_discovery_definer'
            ) THEN
                CREATE ROLE request_engine_discovery_definer
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
            END IF;
        END
        $role$;
        ALTER ROLE request_engine_discovery_definer
            WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
        """
    )

    op.execute("SET ROLE request_engine_schema_owner")
    for table in _IMMUTABLE_APP_TABLES:
        op.execute(f"REVOKE UPDATE ON request_engine.{table} FROM request_engine_app")
    op.execute("DROP INDEX request_engine.service_sessions_queue_idx")
    op.execute(
        """
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
    for name, arguments in _SECURITY_DEFINERS:
        function_ref = _function_ref(name, arguments)
        op.execute(
            f"ALTER FUNCTION {function_ref} SET search_path = pg_catalog, request_engine, pg_temp"
        )

    op.execute(
        "REVOKE ALL ON SCHEMA request_engine, request_read, request_cmd, request_admin "
        "FROM request_engine_discovery_definer"
    )
    op.execute("GRANT USAGE ON SCHEMA request_engine TO request_engine_discovery_definer")
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA request_engine FROM request_engine_discovery_definer"
    )
    op.execute(
        "GRANT SELECT ON request_engine.organizations, request_engine.locations, "
        "request_engine.offerings, request_engine.offering_versions, request_engine.resources, "
        "request_engine.resource_public_profiles, request_engine.service_classifications, "
        "request_engine.offering_service_classifications, request_engine.discovery_publications "
        "TO request_engine_discovery_definer"
    )
    for table in _DISCOVERY_LOCK_RELATIONS:
        op.execute(
            f"GRANT UPDATE (id) ON request_engine.{table} TO request_engine_discovery_definer"
        )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON request_engine.discovery_booking_handoffs "
        "TO request_engine_discovery_definer"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_engine.current_organization_id() "
        "TO request_engine_discovery_definer"
    )
    op.execute("RESET ROLE")

    for name, arguments in _DISCOVERY_DEFINERS:
        function_ref = _function_ref(name, arguments)
        op.execute(f"ALTER FUNCTION {function_ref} OWNER TO request_engine_discovery_definer")
        op.execute(f"REVOKE ALL ON FUNCTION {function_ref} FROM PUBLIC")

    op.execute(
        "GRANT EXECUTE ON FUNCTION request_engine.guard_discovery_handoff_latest_version(), "
        "request_engine.guard_discovery_handoff_reservation(), "
        "request_engine.has_active_discovery_mapping(uuid) "
        "TO request_engine_schema_owner, request_engine_admin"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_engine.issue_discovery_booking_handoff("
        "text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz), "
        "request_engine.search_discovery_candidates_v2("
        "text, double precision, double precision, integer, timestamptz, timestamptz, integer) "
        "TO request_engine_discovery, request_engine_admin"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_engine.read_discovery_booking_handoff(text) "
        "TO request_engine_app, request_engine_admin"
    )


def downgrade() -> None:
    raise RuntimeError("schema cohesion hardening is not reversible")
