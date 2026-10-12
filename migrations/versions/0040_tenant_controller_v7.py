"""Append queue configuration authority and explicitly governed v7 adoption."""

from alembic import op
from sqlalchemy import text

revision: str = "0040_tenant_controller_v7"
down_revision: str | None = "0039_operator_metrics_projection"
branch_labels: str | None = None
depends_on: str | None = None


def _replace_function_text(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new in replacements:
        if definition.count(old) != 1:
            raise RuntimeError(f"Expected unique migration anchor in {signature}: {old}")
        definition = definition.replace(old, new, 1)
    # Preserve the installed recovery/identity locks, ownership and ACLs. No old
    # consent is retargeted; completed and pending v6 receipts remain v6.
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def upgrade() -> None:
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies(policy_key,revision,grants)
        SELECT 'tenant-controller-v7',7,grants || '[
            {"capability_key":"queue.read_configuration",
             "authority_plane":"operational","delegable": true}
        ]'::jsonb
        FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v6';
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                          WHERE policy_key='tenant-controller-v7') THEN
                RAISE EXCEPTION 'v7 requires immutable v6 policy';
            END IF;
        END $$;
        ALTER TABLE request_engine.controller_policy_adoption_requests
            DROP CONSTRAINT controller_policy_adoption_requests_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_requests_target_policy_key_check
                CHECK(target_policy_key IN ('tenant-controller-v6','tenant-controller-v7'));
        ALTER TABLE request_engine.controller_policy_adoption_facts
            DROP CONSTRAINT controller_policy_adoption_facts_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_facts_target_policy_key_check
                CHECK(target_policy_key IN ('tenant-controller-v6','tenant-controller-v7'));
    """)
    _replace_function_text(
        "request_cmd.request_controller_policy_adoption(uuid,bigint,text,text,text,uuid)",
        (
            (
                "'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6')",
                "'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6',"
                "'tenant-controller-v7')",
            ),
            (
                "WHERE policy_key='tenant-controller-v6')",
                "WHERE policy_key='tenant-controller-v7')",
            ),
            (
                "'tenant-controller-v3','tenant-controller-v4','tenant-controller-v5') THEN",
                "'tenant-controller-v3','tenant-controller-v4','tenant-controller-v5',"
                "'tenant-controller-v6') THEN",
            ),
            (
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v6',v_revision,",
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v7',v_revision,",
            ),
            (
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v6',v_revision,1::bigint,",
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v7',v_revision,1::bigint,",
            ),
        ),
    )
    _replace_function_text(
        "request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)",
        (
            (
                "IF NOT FOUND OR v_request.target_policy_key<>'tenant-controller-v6'\n"
                "               OR v_request.source_policy_key NOT IN\n"
                "                    ('tenant-controller-v1','tenant-controller-v2',"
                "'tenant-controller-v3',\n"
                "                     'tenant-controller-v4','tenant-controller-v5') THEN",
                "IF NOT FOUND OR NOT (\n"
                "                (v_request.target_policy_key='tenant-controller-v6'\n"
                "                 AND v_request.source_policy_key IN\n"
                "                    ('tenant-controller-v1','tenant-controller-v2',"
                "'tenant-controller-v3',\n"
                "                     'tenant-controller-v4','tenant-controller-v5'))\n"
                "                OR (v_request.target_policy_key='tenant-controller-v7'\n"
                "                    AND v_request.source_policy_key IN\n"
                "                    ('tenant-controller-v1','tenant-controller-v2',"
                "'tenant-controller-v3',\n"
                "                     'tenant-controller-v4','tenant-controller-v5',"
                "'tenant-controller-v6'))\n"
                "            ) THEN",
            ),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("initial controller policy history is immutable; roll forward")
