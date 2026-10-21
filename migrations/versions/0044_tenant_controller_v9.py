"""Append front-desk operation authority as immutable tenant-controller-v9.

``tenant-controller-v9`` = immutable v8 plus exactly fifteen delegable operational
grants that the Today console and queue setup require (each is the capability of a
current HTTP owner operation; none is platform-plane):

* queue setup: ``queue.configure`` (``queue_service_queue_create``);
* live queue reads: ``queue.list``, ``queue.staff_read``;
* live queue commands: ``queue.check_in`` (reservation check-in and walk-in
  admission), ``queue.call_next``, ``queue.skip``, ``queue.mark_no_show``,
  ``queue.operator_select``, ``queue.recall_hold``, ``queue.release_recall_hold``;
* actual service: ``service_session.start`` (the only way a called entry obtains the
  ServiceSession that the Today console completes), ``service_session.complete``;
* appointment day actions: ``appointments.confirm_attendance``,
  ``appointments.record_arrival_estimate``;
* business profile/contacts: ``organization.manage_profile``.

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Tenancy (initial controller policy and its adoption).
* Guarantees: initial-controller-policy immutability, explicit authority, legacy
  controller-policy adoption (dual consent, no backfill, no revoked-grant restore).
* Change class: CONTROLLED additive. One private catalog row is inserted; the two
  adoption target CHECK constraints widen to v6-v9; two existing definer functions
  are re-created from their installed text through unique anchors (identity,
  recovery, lock order, ownership and ACLs preserved; the transactional migration
  aborts if any anchor differs).
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT and lock order of consent/apply are unchanged;
  only the accepted source/target policy keys change (new consent targets v9; apply
  admits v1-v8 -> v9 while keeping v1-v5 -> v6, v1-v6 -> v7, v1-v7 -> v8 for
  already-recorded consent). v9 self-adoption is rejected.
* Tenant/RLS/roles: no new table, privilege, role or runtime callable.
* Failure/concurrency: unchanged; the catalog is global private configuration.
* Roll-forward: no principal, grant, root fact, request or adoption fact is
  backfilled or retargeted. Only organizations provisioned after the application
  selects v9 receive it; existing roots move only through platform-approved
  adoption. Downgrade is refused (immutable policy history).
* Falsification: tests/db/test_initial_controller_policy.py (exact manifest delta,
  fresh v9 root), tests/db/test_tenant_controller_v9_populated_upgrade.py (physical
  populated 0043 -> head upgrade, v8 -> v9 adoption adds exactly the delta) and
  tests/e2e/test_tenant_controller_v9_front_desk_http.py (owner HTTP journey and
  bounded delegation).
"""

from alembic import op
from sqlalchemy import text

revision: str = "0044_tenant_controller_v9"
down_revision: str | None = "0043_staff_invitation_proposals"
branch_labels: str | None = None
depends_on: str | None = None

_V1_TO_V8 = (
    "'tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',"
    "'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6',"
    "'tenant-controller-v7','tenant-controller-v8'"
)
_TARGETS = (
    "'tenant-controller-v6','tenant-controller-v7','tenant-controller-v8','tenant-controller-v9'"
)


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
    # Preserve installed recovery/identity locks, ownership and ACLs. No old consent
    # is retargeted; completed and pending v6/v7/v8 receipts keep their target.
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO request_engine.initial_controller_policies(policy_key,revision,grants)
        SELECT 'tenant-controller-v9',9,grants || '[
            {{"capability_key":"queue.configure",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.list",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.staff_read",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.check_in",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.call_next",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.skip",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.mark_no_show",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.operator_select",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.recall_hold",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"queue.release_recall_hold",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"service_session.start",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"service_session.complete",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"appointments.confirm_attendance",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"appointments.record_arrival_estimate",
             "authority_plane":"operational","delegable": true}},
            {{"capability_key":"organization.manage_profile",
             "authority_plane":"operational","delegable": true}}
        ]'::jsonb
        FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v8';
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                          WHERE policy_key='tenant-controller-v9') THEN
                RAISE EXCEPTION 'v9 requires immutable v8 policy';
            END IF;
        END $$;
        ALTER TABLE request_engine.controller_policy_adoption_requests
            DROP CONSTRAINT controller_policy_adoption_requests_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_requests_target_policy_key_check
                CHECK(target_policy_key IN ({_TARGETS}));
        ALTER TABLE request_engine.controller_policy_adoption_facts
            DROP CONSTRAINT controller_policy_adoption_facts_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_facts_target_policy_key_check
                CHECK(target_policy_key IN ({_TARGETS}));
    """)
    _replace_function_text(
        "request_cmd.request_controller_policy_adoption(uuid,bigint,text,text,text,uuid)",
        (
            (
                "'tenant-controller-v7','tenant-controller-v8')",
                "'tenant-controller-v7','tenant-controller-v8','tenant-controller-v9')",
            ),
            (
                "WHERE policy_key='tenant-controller-v8')",
                "WHERE policy_key='tenant-controller-v9')",
            ),
            (
                "'tenant-controller-v6','tenant-controller-v7') THEN",
                "'tenant-controller-v6','tenant-controller-v7','tenant-controller-v8') THEN",
            ),
            (
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v8',v_revision,",
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v9',v_revision,",
            ),
            (
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v8',v_revision,1::bigint,",
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v9',v_revision,1::bigint,",
            ),
        ),
    )
    _replace_function_text(
        "request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)",
        (
            (
                "'tenant-controller-v6','tenant-controller-v7'))",
                "'tenant-controller-v6','tenant-controller-v7'))\n"
                "                OR (v_request.target_policy_key='tenant-controller-v9'\n"
                "                    AND v_request.source_policy_key IN\n"
                f"                    ({_V1_TO_V8}))",
            ),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("initial controller policy history is immutable; roll forward")
