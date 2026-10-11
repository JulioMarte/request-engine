"""Acquire the topology gate directly at invitation materialization entry."""

from alembic import op

revision: str = "0010_invitation_topology_gate"
down_revision: str | None = "0009_staff_email_invitations"
branch_labels: str | None = None
depends_on: str | None = None


def _install(*, gate_statement: str) -> None:
    # Closed migration constants only; no caller input enters this SQL.
    # Keep the 0009 proof/session validation and materialization body unchanged.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION request_cmd.materialize_invited_staff(
            p_id uuid,p_digest text,p_authority uuid,p_identity uuid,p_session uuid,p_membership
                uuid,p_principal uuid,p_binding uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_invitation request_engine.staff_invitations%ROWTYPE; v_anchor uuid;
        BEGIN
            {gate_statement}
            SELECT * INTO STRICT v_invitation FROM request_cmd.lock_staff_invitation_acceptance(
                p_id,p_digest,p_authority,p_identity,p_session);
            IF v_invitation.status = 'accepted' THEN RETURN; END IF;
            SELECT organization_party_id INTO v_anchor FROM
                request_engine.organization_root_provisioning_facts
                WHERE organization_id = v_invitation.organization_id;
            IF v_anchor IS NULL THEN RAISE EXCEPTION 'Tenant root unavailable' USING ERRCODE =
                '23514'; END IF;
            INSERT INTO request_engine.principals(id,organization_id,
                principal_plane,principal_kind,external_subject)
                VALUES(p_principal,v_invitation.organization_id,'tenant','human','native:'||p_identity::text);
            INSERT INTO request_engine.identity_bindings(id,organization_id,
                principal_id,principal_plane,
                identity_authority_id,subject_id,status)
                VALUES(p_binding,v_invitation.organization_id,p_principal,'tenant',p_authority,p_identity::text,'active');
            INSERT INTO request_engine.staff_memberships(id,organization_id,
                principal_id,identity_binding_id,
                authority_anchor_party_id,status,established_by_principal_id,provenance_kind,provenance_reference,activated_at)
                VALUES(p_membership,v_invitation.organization_id,p_principal,p_binding,v_anchor,'active',
                    v_invitation.invited_by_principal_id,'staff_invitation',v_invitation.provenance_reference,clock_timestamp());
            UPDATE request_engine.staff_invitations SET status='accepted',revision=revision+1,
                accepted_native_identity_id=p_identity,membership_id=p_membership,principal_id=p_principal,binding_id=p_binding,
                updated_at=clock_timestamp() WHERE id=p_id;
            INSERT INTO request_engine.audit_records(organization_id,actor_principal_id,
                command_name,aggregate_kind,aggregate_id,details)
                VALUES(v_invitation.organization_id,p_principal,'staff.invitation.accept','StaffInvitation',p_id,
                jsonb_build_object('action','accept','reason_code','staff_invitation_accepted',
                    'revision_before',v_invitation.revision,'revision_after',v_invitation.revision+1,
                    'provenance_reference',v_invitation.provenance_reference));
        END $$;
    """)


def upgrade() -> None:
    _install(gate_statement="PERFORM request_engine.acquire_identity_topology_share();")


def downgrade() -> None:
    # 0009 still acquires the same gate through lock_staff_invitation_acceptance.
    _install(gate_statement="")
