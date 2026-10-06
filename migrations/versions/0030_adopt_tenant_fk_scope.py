"""Bind controller policy adoption records to their tenant and identity.

The original adoption migration used single-column foreign keys for controller
and identity binding references. Those keys guaranteed existence but not that
both references belonged to the row's organization and to each other. This
forward-only migration strengthens the relational tenant boundary.
"""

from alembic import op

revision: str = "0030_adopt_tenant_fk_scope"
down_revision: str | None = "0029_ctrl_adopt_readiness"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE request_engine.controller_policy_adoption_requests
            DROP CONSTRAINT controller_policy_adoption_request_controller_principal_id_fkey,
            DROP CONSTRAINT controller_policy_adoption_requests_controller_binding_id_fkey,
            ADD CONSTRAINT controller_policy_adoption_request_controller_fk
                FOREIGN KEY(organization_id,controller_principal_id)
                REFERENCES request_engine.principals(organization_id,id) NOT VALID,
            ADD CONSTRAINT controller_policy_adoption_request_binding_fk
                FOREIGN KEY(organization_id,controller_principal_id,controller_binding_id)
                REFERENCES request_engine.identity_bindings(organization_id,principal_id,id)
                NOT VALID;
        ALTER TABLE request_engine.controller_policy_adoption_requests
            VALIDATE CONSTRAINT controller_policy_adoption_request_controller_fk;
        ALTER TABLE request_engine.controller_policy_adoption_requests
            VALIDATE CONSTRAINT controller_policy_adoption_request_binding_fk;

        ALTER TABLE request_engine.controller_policy_adoption_facts
            DROP CONSTRAINT controller_policy_adoption_fact_requester_fk,
            DROP CONSTRAINT controller_policy_adoption_fact_binding_fk,
            ADD CONSTRAINT controller_policy_adoption_fact_requester_fk
                FOREIGN KEY(organization_id,controller_principal_id)
                REFERENCES request_engine.principals(organization_id,id) NOT VALID,
            ADD CONSTRAINT controller_policy_adoption_fact_binding_fk
                FOREIGN KEY(organization_id,controller_principal_id,controller_binding_id)
                REFERENCES request_engine.identity_bindings(organization_id,principal_id,id)
                NOT VALID;
        ALTER TABLE request_engine.controller_policy_adoption_facts
            VALIDATE CONSTRAINT controller_policy_adoption_fact_requester_fk;
        ALTER TABLE request_engine.controller_policy_adoption_facts
            VALIDATE CONSTRAINT controller_policy_adoption_fact_binding_fk;
    """)


def downgrade() -> None:
    raise RuntimeError("Tenant-bound adoption references are roll-forward only")
