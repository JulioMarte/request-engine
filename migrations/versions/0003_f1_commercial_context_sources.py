"""Add multi-source contextual commercial provenance for F1 Reservations.

Revision ID: 0003_f1_context_sources
Revises: 0002_f1_supply
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_f1_context_sources"
down_revision: str | Sequence[str] | None = "0002_f1_supply"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE TABLE request_engine.reservation_commercial_commitment_context_terms (
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    booking_context_terms_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, reservation_id, booking_context_terms_id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservation_commercial_commitments (
            organization_id, reservation_id
        ),
    FOREIGN KEY (organization_id, booking_context_terms_id)
        REFERENCES request_engine.booking_context_terms (organization_id, id)
);

COMMENT ON TABLE request_engine.reservation_commercial_commitment_context_terms IS
    'Append-only provenance linking one committed Reservation commercial fact to every exact contextual term row that contributed to its resolution.';

CREATE TRIGGER reservation_commercial_commitment_context_terms_append_only
BEFORE UPDATE OR DELETE
ON request_engine.reservation_commercial_commitment_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

ALTER TABLE request_engine.reservation_commercial_commitment_context_terms
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.reservation_commercial_commitment_context_terms
    FORCE ROW LEVEL SECURITY;

CREATE POLICY reservation_commercial_commitment_context_terms_tenant_isolation
ON request_engine.reservation_commercial_commitment_context_terms
USING (organization_id = request_engine.current_organization_id())
WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.reservation_commercial_commitment_context_terms FROM PUBLIC;
GRANT SELECT, INSERT
ON request_engine.reservation_commercial_commitment_context_terms
TO request_engine_app, request_engine_worker;
GRANT ALL PRIVILEGES
ON request_engine.reservation_commercial_commitment_context_terms
TO request_engine_admin;

RESET ROLE;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "F1 commercial provenance is append-only production history and is not downgradable"
    )
