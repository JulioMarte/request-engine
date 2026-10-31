"""Append appointment-note authority as immutable tenant-controller-v10.

``tenant-controller-v10`` = immutable v9 plus exactly one delegable operational
grant: ``appointments.annotate`` (the capability of the Booking owner command
``appointments_note_add`` introduced with migration ``0002_reservation_notes``).
Reading notes stays under ``appointments.day_board``, already held since v1. The
new capability is not platform-plane and carries no lifecycle/capacity authority.

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Tenancy (initial controller policy and its adoption). The
  delegated capability itself is owned by Booking.
* Guarantees: initial-controller-policy immutability, explicit authority, legacy
  controller-policy adoption (dual consent, no backfill, no revoked-grant restore).
* Change class: CONTROLLED additive. One private catalog row is inserted; the two
  adoption target CHECK constraints widen to v6-v10; two existing definer
  functions are re-created from their installed text through unique anchors
  (identity, recovery, lock order, ownership and ACLs preserved; the transactional
  migration aborts if any anchor differs).
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT and lock order of consent/apply are unchanged;
  only the accepted source/target policy keys change (new consent targets v10;
  apply admits v1-v9 -> v10 while keeping v1-v5 -> v6, v1-v6 -> v7, v1-v7 -> v8
  and v1-v8 -> v9 for already-recorded consent). v10 self-adoption is rejected.
* Tenant/RLS/roles: no new table, privilege, role or runtime callable.
* Failure/concurrency: unchanged; the catalog is global private configuration.
* Roll-forward: no principal, grant, root fact, request or adoption fact is
  backfilled or retargeted. Only organizations provisioned after the application
  selects v10 receive it; existing roots move only through platform-approved
  adoption. Downgrade is refused (immutable policy history).
* Falsification: tests/db/test_initial_controller_policy.py (exact manifest delta
  against an independent reviewed oracle, fresh v10 root grant counts),
  tests/db/test_tenant_controller_v9_adoption.py (v8 -> v10 adoption adds exactly
  the v9 + v10 delta, v10 self-adoption rejected) and the controller-policy
  adoption HTTP suites (adoption targets v10).
"""

from alembic import op
from sqlalchemy import text

revision: str = "0003_tenant_controller_v10"
down_revision: str | None = "0002_reservation_notes"
branch_labels: str | None = None
depends_on: str | None = None

_V1_TO_V9 = (
    "'tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',"
    "'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6',"
    "'tenant-controller-v7','tenant-controller-v8','tenant-controller-v9'"
)
_TARGETS = (
    "'tenant-controller-v6','tenant-controller-v7','tenant-controller-v8',"
    "'tenant-controller-v9','tenant-controller-v10'"
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
    # is retargeted; completed and pending v6/v7/v8/v9 receipts keep their target.
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO request_engine.initial_controller_policies(policy_key,revision,grants)
        SELECT 'tenant-controller-v10',10,grants || '[
            {{"capability_key":"appointments.annotate",
             "authority_plane":"operational","delegable": true}}
        ]'::jsonb
        FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v9';
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                          WHERE policy_key='tenant-controller-v10') THEN
                RAISE EXCEPTION 'v10 requires immutable v9 policy';
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
            # Known-policy guard: v10 is a recognised (but non-adoptable) source.
            (
                "'tenant-controller-v8','tenant-controller-v9')",
                "'tenant-controller-v8','tenant-controller-v9','tenant-controller-v10')",
            ),
            # The target policy row must exist.
            (
                "WHERE policy_key='tenant-controller-v9')",
                "WHERE policy_key='tenant-controller-v10')",
            ),
            # Adoptable sources for new consent: v1-v9 (v10 self-adoption rejected).
            (
                "'tenant-controller-v7','tenant-controller-v8') THEN",
                "'tenant-controller-v7','tenant-controller-v8','tenant-controller-v9') THEN",
            ),
            (
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v9',v_revision,",
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v10',v_revision,",
            ),
            (
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v9',v_revision,1::bigint,",
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v10',v_revision,1::bigint,",
            ),
        ),
    )
    _replace_function_text(
        "request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)",
        (
            (
                "'tenant-controller-v6','tenant-controller-v7','tenant-controller-v8'))",
                "'tenant-controller-v6','tenant-controller-v7','tenant-controller-v8'))\n"
                "                OR (v_request.target_policy_key='tenant-controller-v10'\n"
                "                    AND v_request.source_policy_key IN\n"
                f"                    ({_V1_TO_V9}))",
            ),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("initial controller policy history is immutable; roll forward")
