"""Add phone lookup index for party contact points (S0b FIX-A).

Revision ID: 0024_s0b_party_contact_lookup
Revises: 0023_s0b_party_identity_docs
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_s0b_party_contact_lookup"
down_revision: str | Sequence[str] | None = "0023_s0b_party_identity_docs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

-- Serves the parties.lookup phone predicate: active contact points in the
-- phone/whatsapp channels matched by (organization, normalized value).
-- Indexes carry no privileges; only the schema-owner wrapper is needed.
CREATE INDEX party_contact_points_value_lookup_idx
    ON request_engine.party_contact_points (organization_id, normalized_value, channel)
    WHERE active;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0024 introduces the party contact lookup index and is not reversible")
