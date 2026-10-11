"""Explicit fresh-root configuration authority; existing roots are unchanged."""

from alembic import op

revision: str = "0021_tenant_controller_v6"
down_revision: str | None = "0020_retention_recorder_role"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies(policy_key,revision,grants)
        SELECT 'tenant-controller-v6',6,grants || '[
            {"capability_key": "booking.read_supply",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "catalog.read_configuration",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "communications.read_configuration",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.create_definition",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.publish_definition_version",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.set_definition_active",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.read_definitions",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.read_inbox",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "communications.configure",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.submit",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.read",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.cancel",
             "authority_plane": "operational", "delegable": true},
            {"capability_key": "requests.party_override",
             "authority_plane": "operational", "delegable": true}
        ]'::jsonb
        FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v5';
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                          WHERE policy_key='tenant-controller-v6') THEN
                RAISE EXCEPTION 'v6 requires immutable v5 policy';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("initial controller policy history is immutable; roll forward")
