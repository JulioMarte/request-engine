"""Agent-proposed, HUMAN-approved staff invitations and controller policy v8 (ADR 0019).

Adds the tenant-isolated ``staff_invitation_proposals`` owner table. A proposal is
inert: inserting one requires current ``staff.propose_invitation`` authority (an
active HUMAN staff member or an active AGENT) and grants, stages or sends nothing.
Only a current HUMAN ``staff.invite`` manager may decide it, and an approval must
link the decider's own pending invitation for the same email.

Also appends immutable ``tenant-controller-v8`` (v7 plus delegable operational
``staff.propose_invitation``) so a controller can grant that capability to an
agent, and admits v1-v7 -> v8 through the existing dual-consent adoption.
"""

from alembic import op
from sqlalchemy import text

revision: str = "0043_staff_invitation_proposals"
down_revision: str | None = "0042_password_optional_passkey"
branch_labels: str | None = None
depends_on: str | None = None

_V1_TO_V6 = (
    "'tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',"
    "'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6'"
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
    # CREATE OR REPLACE keeps ownership and ACLs. Existing v6/v7 consent is never
    # retargeted: pending receipts keep their recorded target policy.
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def _proposals() -> None:
    op.execute("""
        CREATE TABLE request_engine.staff_invitation_proposals (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
            email text NOT NULL CHECK(length(email) BETWEEN 3 AND 320
                AND email = lower(btrim(email)) AND email ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'),
            display_name text CHECK(display_name IS NULL
                OR (display_name = btrim(display_name) AND length(display_name) BETWEEN 1 AND 200)),
            note text CHECK(note IS NULL
                OR (note = btrim(note) AND length(note) BETWEEN 1 AND 1000)),
            proposed_by_principal_id uuid NOT NULL,
            provenance_reference text NOT NULL
                CHECK(length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            status text NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected')),
            revision bigint NOT NULL DEFAULT 1 CHECK(revision > 0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            decided_at timestamptz,
            decided_by_principal_id uuid,
            decision_provenance_reference text
                CHECK(length(btrim(decision_provenance_reference)) BETWEEN 1 AND 500),
            invitation_id uuid,
            rejection_reason text CHECK(rejection_reason IS NULL OR
                (rejection_reason = btrim(rejection_reason)
                 AND length(rejection_reason) BETWEEN 1 AND 500)),
            UNIQUE(organization_id,id),
            FOREIGN KEY(organization_id,proposed_by_principal_id)
                REFERENCES request_engine.principals(organization_id,id),
            FOREIGN KEY(organization_id,decided_by_principal_id)
                REFERENCES request_engine.principals(organization_id,id),
            FOREIGN KEY(organization_id,invitation_id)
                REFERENCES request_engine.staff_invitations(organization_id,id),
            CONSTRAINT staff_invitation_proposals_decision_fields CHECK(
                (status = 'pending') = (decided_at IS NULL AND decided_by_principal_id IS NULL
                    AND decision_provenance_reference IS NULL)),
            CONSTRAINT staff_invitation_proposals_approval_link CHECK(
                (status = 'approved') = (invitation_id IS NOT NULL)),
            CONSTRAINT staff_invitation_proposals_rejection_reason CHECK(
                status = 'rejected' OR rejection_reason IS NULL),
            CHECK(decided_at IS NULL OR decided_at >= created_at)
        );
        ALTER TABLE request_engine.staff_invitation_proposals
            OWNER TO request_engine_schema_owner;
        CREATE UNIQUE INDEX staff_invitation_proposals_pending_email_uq
            ON request_engine.staff_invitation_proposals(organization_id,email)
            WHERE status = 'pending';
        CREATE UNIQUE INDEX staff_invitation_proposals_invitation_uq
            ON request_engine.staff_invitation_proposals(organization_id,invitation_id)
            WHERE invitation_id IS NOT NULL;
        -- Approvals inbox: tenant + status filter with keyset id ordering.
        CREATE INDEX staff_invitation_proposals_inbox_idx
            ON request_engine.staff_invitation_proposals(organization_id,status,id);
        ALTER TABLE request_engine.staff_invitation_proposals ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.staff_invitation_proposals FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON request_engine.staff_invitation_proposals
            USING(organization_id = request_engine.current_organization_id())
            WITH CHECK(organization_id = request_engine.current_organization_id());
        GRANT SELECT, INSERT, UPDATE ON request_engine.staff_invitation_proposals
            TO request_engine_app;

        CREATE FUNCTION request_cmd.assert_staff_invitation_proposer() RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_actor uuid; v_org uuid;
        BEGIN
            BEGIN
                v_actor := current_setting('request_engine.authenticated_principal_id',
                    true)::uuid;
                v_org := request_engine.current_organization_id();
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Tenant actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_actor IS NULL OR v_org IS NULL THEN
                RAISE EXCEPTION 'Tenant actor provenance is required' USING ERRCODE = '28000';
            END IF;
            PERFORM 1 FROM request_engine.principals AS p
              JOIN request_engine.principal_authority_grants AS g
                ON g.principal_id = p.id AND g.organization_id = v_org
               AND g.capability_key = 'staff.propose_invitation'
               AND g.authority_plane = 'operational' AND g.status = 'active'
             WHERE p.id = v_actor AND p.organization_id = v_org
               AND p.principal_plane = 'tenant' AND p.active
               AND ((p.principal_kind = 'human' AND EXISTS(
                        SELECT 1 FROM request_engine.staff_memberships AS m
                         WHERE m.principal_id = p.id AND m.organization_id = v_org
                           AND m.status = 'active'))
                    OR (p.principal_kind = 'agent' AND EXISTS(
                        SELECT 1 FROM request_engine.agent_profiles AS a
                         WHERE a.principal_id = p.id AND a.organization_id = v_org
                           AND a.status = 'active')))
             FOR SHARE OF p, g;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Principal lacks staff invitation proposal authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN v_actor;
        END $$;
        ALTER FUNCTION request_cmd.assert_staff_invitation_proposer()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.assert_staff_invitation_proposer() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.assert_staff_invitation_proposer()
            TO request_engine_app;

        CREATE FUNCTION request_engine.guard_staff_invitation_proposal() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_decider uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revision <> 1 OR NEW.status <> 'pending'
                    OR NEW.proposed_by_principal_id IS DISTINCT FROM
                        request_cmd.assert_staff_invitation_proposer() THEN
                    RAISE EXCEPTION 'Invalid staff invitation proposal' USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            -- Only a current HUMAN staff.invite manager decides; agents fail here.
            v_decider := request_cmd.assert_staff_invitation_manager();
            IF NEW.decided_by_principal_id IS DISTINCT FROM v_decider THEN
                RAISE EXCEPTION 'Decision must record the current manager'
                    USING ERRCODE = '42501';
            END IF;
            IF OLD.status <> 'pending' OR NEW.status NOT IN ('approved','rejected')
                OR NEW.revision <> OLD.revision + 1
                OR (NEW.id,NEW.organization_id,NEW.email,NEW.display_name,NEW.note,
                    NEW.proposed_by_principal_id,NEW.provenance_reference,NEW.created_at)
                    IS DISTINCT FROM
                   (OLD.id,OLD.organization_id,OLD.email,OLD.display_name,OLD.note,
                    OLD.proposed_by_principal_id,OLD.provenance_reference,OLD.created_at) THEN
                RAISE EXCEPTION 'Invalid staff invitation proposal decision'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'approved' AND NOT EXISTS(
                SELECT 1 FROM request_engine.staff_invitations AS i
                 WHERE i.id = NEW.invitation_id AND i.organization_id = NEW.organization_id
                   AND i.email = NEW.email AND i.invited_by_principal_id = v_decider
                   AND i.status = 'pending') THEN
                RAISE EXCEPTION 'Approval must link the decider''s pending invitation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        ALTER FUNCTION request_engine.guard_staff_invitation_proposal()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_staff_invitation_proposal() FROM PUBLIC;
        CREATE TRIGGER guard_staff_invitation_proposal BEFORE INSERT OR UPDATE
            ON request_engine.staff_invitation_proposals
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_staff_invitation_proposal();
    """)


def _controller_policy_v8() -> None:
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies(policy_key,revision,grants)
        SELECT 'tenant-controller-v8',8,grants || '[
            {"capability_key":"staff.propose_invitation",
             "authority_plane":"operational","delegable": true}
        ]'::jsonb
        FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v7';
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                          WHERE policy_key='tenant-controller-v8') THEN
                RAISE EXCEPTION 'v8 requires immutable v7 policy';
            END IF;
        END $$;
        ALTER TABLE request_engine.controller_policy_adoption_requests
            DROP CONSTRAINT controller_policy_adoption_requests_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_requests_target_policy_key_check
                CHECK(target_policy_key IN
                    ('tenant-controller-v6','tenant-controller-v7','tenant-controller-v8'));
        ALTER TABLE request_engine.controller_policy_adoption_facts
            DROP CONSTRAINT controller_policy_adoption_facts_target_policy_key_check,
            ADD CONSTRAINT controller_policy_adoption_facts_target_policy_key_check
                CHECK(target_policy_key IN
                    ('tenant-controller-v6','tenant-controller-v7','tenant-controller-v8'));
    """)
    _replace_function_text(
        "request_cmd.request_controller_policy_adoption(uuid,bigint,text,text,text,uuid)",
        (
            (
                "'tenant-controller-v5','tenant-controller-v6','tenant-controller-v7')",
                "'tenant-controller-v5','tenant-controller-v6','tenant-controller-v7',"
                "'tenant-controller-v8')",
            ),
            (
                "WHERE policy_key='tenant-controller-v7')",
                "WHERE policy_key='tenant-controller-v8')",
            ),
            (
                "'tenant-controller-v5','tenant-controller-v6') THEN",
                "'tenant-controller-v5','tenant-controller-v6','tenant-controller-v7') THEN",
            ),
            (
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v7',v_revision,",
                "VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v8',v_revision,",
            ),
            (
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v7',v_revision,1::bigint,",
                "RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v8',v_revision,1::bigint,",
            ),
        ),
    )
    _replace_function_text(
        "request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)",
        (
            (
                "'tenant-controller-v5','tenant-controller-v6'))",
                "'tenant-controller-v5','tenant-controller-v6'))\n"
                "                OR (v_request.target_policy_key='tenant-controller-v8'\n"
                "                    AND v_request.source_policy_key IN\n"
                f"                    ({_V1_TO_V6},'tenant-controller-v7'))",
            ),
        ),
    )


def upgrade() -> None:
    _proposals()
    _controller_policy_v8()


def downgrade() -> None:
    raise RuntimeError("initial controller policy history is immutable; roll forward")
