"""Give newly provisioned Platform Owners the narrow adoption capability.

Existing owners, grants, and the immutable first-claim v1 policy are untouched.
"""

from alembic import op

revision: str = "0026_platform_owner_v5"
down_revision: str | None = "0025_agent_credential_rotation"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        DO $migration$
        DECLARE
            v4 jsonb;
            v5 jsonb;
            definition text;
            marker text := 'WHERE policy.policy_key = ''platform-owner-v2'';';
            replacement text := 'WHERE policy.policy_key = ''platform-owner-v5'';';
        BEGIN
            SELECT grants INTO v4
              FROM request_engine.platform_owner_policies
             WHERE policy_key='platform-owner-v4' AND revision=4;
            IF v4 IS NULL THEN
                RAISE EXCEPTION 'Expected immutable platform-owner-v4 policy is missing';
            END IF;
            IF EXISTS (
                SELECT 1 FROM jsonb_array_elements(v4) AS item
                 WHERE item->>'capability_key' =
                       'platform.organization.adopt_initial_controller_policy'
            ) THEN
                RAISE EXCEPTION 'platform-owner-v4 unexpectedly contains the v5 capability';
            END IF;
            v5 := v4 || jsonb_build_array(jsonb_build_object(
                'delegable', false,
                'capability_key', 'platform.organization.adopt_initial_controller_policy'
            ));
            INSERT INTO request_engine.platform_owner_policies(policy_key,revision,grants)
            VALUES('platform-owner-v5',5,v5);

            -- The accepted baseline constrained provisioning provenance to the
            -- original v2 selector. Retain those historical facts while allowing
            -- the new immutable selector for future owner provisioning only.
            ALTER TABLE request_engine.platform_owner_provisioning_facts
                DROP CONSTRAINT platform_owner_provisioning_policy_check;
            ALTER TABLE request_engine.platform_owner_provisioning_facts
                ADD CONSTRAINT platform_owner_provisioning_policy_check
                CHECK(policy_key IN ('platform-owner-v2','platform-owner-v5'));

            -- Preserve the existing owner-provisioning transaction and ACLs. Only
            -- its immutable policy selector changes; no current grant is backfilled.
            definition := pg_get_functiondef(
                'request_platform.provision_native_platform_owner(uuid,uuid,uuid,uuid,text,text,text)'::regprocedure
            );
            IF (length(definition) - length(replace(definition, marker, '')))
                    / length(marker) <> 1
               OR position(replacement IN definition)>0 THEN
                RAISE EXCEPTION
                    'Platform Owner policy selector migration anchor is missing or ambiguous';
            END IF;
            EXECUTE replace(definition,marker,replacement);
        END
        $migration$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Platform Owner authority policy history is immutable; use a reviewed roll-forward"
    )
