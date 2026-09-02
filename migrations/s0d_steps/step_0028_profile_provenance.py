"""Attach portable profile snapshots to their publishing organization."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

ALTER TABLE request_engine.portable_person_profiles
    ADD COLUMN publisher_organization_id uuid NOT NULL
        REFERENCES request_engine.organizations(id);
ALTER TABLE request_engine.portable_person_profiles
    DROP CONSTRAINT portable_person_profiles_pkey;
ALTER TABLE request_engine.portable_person_profiles
    ADD PRIMARY KEY (portable_person_id, publisher_organization_id);
CREATE INDEX portable_person_profiles_person_idx
    ON request_engine.portable_person_profiles(portable_person_id)
    WHERE active;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)
