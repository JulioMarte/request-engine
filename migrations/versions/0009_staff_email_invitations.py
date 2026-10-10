"""Durable staff invitations and closed-purpose Communications delivery intents."""

from alembic import op

revision: str = "0009_staff_email_invitations"
down_revision: str | None = "0008_self_org_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE request_engine.staff_memberships ADD CONSTRAINT staff_memberships_org_id_uq
                UNIQUE(organization_id,id);
        CREATE TABLE request_engine.staff_invitations (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
            email text NOT NULL CHECK(length(email) BETWEEN 3 AND 320 AND email =
                lower(btrim(email))
                AND email ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'),
            invited_by_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            provenance_reference text NOT NULL CHECK(length(btrim(provenance_reference)) BETWEEN
                1 AND 500),
            status text NOT NULL DEFAULT 'pending' CHECK(status IN
                ('pending','accepted','revoked','expired')),
            revision bigint NOT NULL DEFAULT 1 CHECK(revision > 0),
            generation integer NOT NULL DEFAULT 1 CHECK(generation > 0),
            token_digest text NOT NULL CHECK(token_digest ~ '^[0-9a-f]{64}$'),
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            accepted_native_identity_id uuid REFERENCES request_engine.native_identities(id),
            membership_id uuid REFERENCES request_engine.staff_memberships(id),
            principal_id uuid REFERENCES request_engine.principals(id),
            binding_id uuid REFERENCES request_engine.identity_bindings(id),
            UNIQUE(organization_id,id),
            FOREIGN KEY(organization_id,invited_by_principal_id) REFERENCES
                request_engine.principals(organization_id,id),
            FOREIGN KEY(organization_id,membership_id) REFERENCES
                request_engine.staff_memberships(organization_id,id),
            FOREIGN KEY(organization_id,principal_id) REFERENCES
                request_engine.principals(organization_id,id),
            FOREIGN KEY(organization_id,principal_id,binding_id) REFERENCES
                request_engine.identity_bindings(organization_id,principal_id,id),
            CHECK((status = 'accepted') = (accepted_native_identity_id IS NOT NULL
                AND membership_id IS NOT NULL AND principal_id IS NOT NULL AND binding_id IS NOT
                NULL)),
            CHECK(status = 'accepted' OR (accepted_native_identity_id IS NULL AND membership_id
                IS NULL
                AND principal_id IS NULL AND binding_id IS NULL)),
            CHECK(expires_at > created_at)
        );
        ALTER TABLE request_engine.staff_invitations OWNER TO request_engine_schema_owner;
        CREATE UNIQUE INDEX staff_invitation_pending_email ON request_engine.staff_invitations
            (organization_id,email) WHERE status = 'pending';
        ALTER TABLE request_engine.staff_invitations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.staff_invitations FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON request_engine.staff_invitations
            USING(organization_id = request_engine.current_organization_id())
            WITH CHECK(organization_id = request_engine.current_organization_id());
        GRANT SELECT, INSERT, UPDATE ON request_engine.staff_invitations TO request_engine_app;

        CREATE FUNCTION request_cmd.assert_staff_invitation_manager() RETURNS uuid
        LANGUAGE sql SECURITY DEFINER SET search_path TO pg_catalog,request_engine,pg_temp
        AS $$ SELECT request_engine.assert_staff_manager('staff.invite') $$;
        ALTER FUNCTION request_cmd.assert_staff_invitation_manager() OWNER TO
                request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.assert_staff_invitation_manager() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.assert_staff_invitation_manager() TO
                request_engine_app;
        CREATE FUNCTION request_engine.guard_staff_invitation() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revision <> 1 OR NEW.generation <> 1 OR NEW.status <> 'pending'
                    OR NEW.invited_by_principal_id IS DISTINCT FROM
                request_cmd.assert_staff_invitation_manager() THEN
                    RAISE EXCEPTION 'Invalid invitation creation' USING ERRCODE = '42501';
                END IF;
            ELSE
                IF OLD.status <> 'pending' OR NEW.revision <> OLD.revision + 1
                    OR (NEW.id,NEW.organization_id,NEW.email,
                        NEW.invited_by_principal_id,NEW.created_at,NEW.provenance_reference)
                        IS DISTINCT FROM
                (OLD.id,OLD.organization_id,OLD.email,
                    OLD.invited_by_principal_id,OLD.created_at,OLD.provenance_reference) THEN
                    RAISE EXCEPTION 'Invalid invitation lifecycle' USING ERRCODE = '23514';
                END IF;
                IF NEW.status = 'accepted' THEN
                    IF current_user <> 'request_engine_schema_owner' THEN
                        RAISE EXCEPTION 'Acceptance requires subject proof' USING ERRCODE = '42501';
                    END IF;
                ELSE
                    PERFORM request_cmd.assert_staff_invitation_manager();
                END IF;
                IF NEW.status = 'pending' THEN
                    IF NEW.generation <> OLD.generation + 1 OR NEW.token_digest =
                OLD.token_digest THEN
                        RAISE EXCEPTION 'Resend must rotate proof' USING ERRCODE = '23514';
                    END IF;
                ELSIF NEW.generation <> OLD.generation OR NEW.token_digest <> OLD.token_digest
                    OR NEW.expires_at <> OLD.expires_at THEN
                    RAISE EXCEPTION 'Terminal transition may not replace proof' USING ERRCODE =
                '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        ALTER FUNCTION request_engine.guard_staff_invitation() OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_staff_invitation() FROM PUBLIC;
        CREATE TRIGGER guard_staff_invitation BEFORE INSERT OR UPDATE ON
                request_engine.staff_invitations
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_staff_invitation();

        CREATE TABLE request_engine.staff_invitation_deliveries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
            invitation_id uuid NOT NULL,
            generation integer NOT NULL CHECK(generation > 0),
            destination_address text NOT NULL CHECK(length(destination_address) BETWEEN 3 AND 320
                AND destination_address = lower(btrim(destination_address))
                AND destination_address ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'),
            secret_reference text NOT NULL CHECK(length(secret_reference) > 0),
            secret_digest text NOT NULL CHECK(secret_digest ~ '^[0-9a-f]{64}$'),
            expires_at timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'pending'
                CHECK(status IN
                ('pending','attempting','delivered','unknown','failed','cancelled','expired')),
            attempt_no integer NOT NULL DEFAULT 0 CHECK(attempt_no >= 0),
            attempted_at timestamptz,
            retry_at timestamptz,
            last_error_class text CHECK(length(last_error_class) <= 100),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(organization_id,id),
            CHECK(expires_at > created_at),
            UNIQUE(organization_id,invitation_id,generation),
            FOREIGN KEY(organization_id,invitation_id)
                REFERENCES request_engine.staff_invitations(organization_id,id)
        );
        ALTER TABLE request_engine.staff_invitation_deliveries OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.staff_invitation_deliveries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.staff_invitation_deliveries FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON request_engine.staff_invitation_deliveries
            USING(organization_id = request_engine.current_organization_id())
            WITH CHECK(organization_id = request_engine.current_organization_id());
        GRANT SELECT, INSERT, UPDATE ON request_engine.staff_invitation_deliveries TO
                request_engine_app;

        CREATE FUNCTION request_cmd.lock_staff_invitation_admin(p_id uuid)
        RETURNS SETOF request_engine.staff_invitations
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM request_engine.assert_staff_manager('staff.invite');
            RETURN QUERY SELECT * FROM request_engine.staff_invitations
                WHERE id = p_id AND organization_id = request_engine.current_organization_id()
                FOR UPDATE;
        END $$;
        ALTER FUNCTION request_cmd.lock_staff_invitation_admin(uuid) OWNER TO
                request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.lock_staff_invitation_admin(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.lock_staff_invitation_admin(uuid) TO
                request_engine_app;

        GRANT SELECT(id,organization_id,token_digest) ON request_engine.staff_invitations
            TO request_platform_definer;
        CREATE FUNCTION request_auth.staff_invitation_target(p_id uuid,p_digest text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
            SELECT organization_id FROM request_engine.staff_invitations
                WHERE id=p_id AND token_digest=p_digest
        $$;
        ALTER FUNCTION request_auth.staff_invitation_target(uuid,text)
            OWNER TO request_platform_definer;
        REVOKE ALL ON FUNCTION request_auth.staff_invitation_target(uuid,text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.staff_invitation_target(uuid,text)
            TO request_engine_app,request_engine_schema_owner;

        CREATE FUNCTION request_cmd.lock_staff_invitation_acceptance(
            p_id uuid,p_digest text,p_authority uuid,p_identity uuid,p_session uuid)
        RETURNS SETOF request_engine.staff_invitations
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_invitation request_engine.staff_invitations%ROWTYPE; v_org uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_id IS NULL OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$'
                OR p_authority IS NULL OR p_identity IS NULL OR p_session IS NULL THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            v_org := request_auth.staff_invitation_target(p_id,p_digest);
            IF v_org IS NULL THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM set_config('request_engine.organization_id',v_org::text,true);
            SELECT * INTO v_invitation FROM request_engine.staff_invitations WHERE id = p_id;
            IF NOT FOUND OR v_invitation.token_digest IS DISTINCT FROM p_digest THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM id FROM request_engine.staff_memberships
                WHERE organization_id = v_invitation.organization_id AND status = 'active'
                ORDER BY principal_id FOR UPDATE;
            SELECT * INTO v_invitation FROM request_engine.staff_invitations WHERE id = p_id FOR
                UPDATE;
            IF v_invitation.token_digest IS DISTINCT FROM p_digest THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM 1 FROM request_engine.organizations
                WHERE id = v_invitation.organization_id AND operational_status = 'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Organization unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.identity_authorities
                WHERE id = p_authority AND kind = 'native' AND status = 'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native authority unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_identities
                WHERE id = p_identity AND identity_authority_id = p_authority AND status =
                'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native identity unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_sessions AS s
                JOIN request_engine.native_identities AS i ON i.id = s.native_identity_id
                LEFT JOIN request_engine.native_credentials AS c ON c.id = s.password_credential_id
                LEFT JOIN request_engine.webauthn_credentials AS w ON w.id =
                s.webauthn_credential_id
                LEFT JOIN request_engine.native_identity_recovery_state AS r ON
                r.native_identity_id = i.id
                WHERE s.id = p_session AND s.native_identity_id = p_identity AND s.status = 'active'
                AND s.expires_at > clock_timestamp() AND s.session_epoch = i.session_epoch
                AND NOT s.recovery_derived AND coalesce(r.state,'normal') <> 'recovery_restricted'
                AND (c.status = 'active' OR w.status = 'active') FOR SHARE OF s;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native session unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_credentials
                WHERE id = (SELECT password_credential_id FROM request_engine.native_sessions
                WHERE id = p_session)
                AND status = 'active' FOR SHARE;
            IF NOT FOUND THEN
                PERFORM 1 FROM request_engine.webauthn_credentials
                    WHERE id = (SELECT webauthn_credential_id FROM
                request_engine.native_sessions WHERE id = p_session)
                    AND status = 'active' FOR SHARE;
                IF NOT FOUND THEN RAISE EXCEPTION 'Session authenticator unavailable' USING
                ERRCODE = '42501'; END IF;
            END IF;
            IF v_invitation.status = 'accepted' THEN
                IF v_invitation.accepted_native_identity_id <> p_identity THEN
                    RAISE EXCEPTION 'Invitation belongs to another identity' USING ERRCODE =
                '42501';
                END IF;
            ELSE
                IF v_invitation.status <> 'pending' OR v_invitation.expires_at <=
                clock_timestamp() THEN
                    RAISE EXCEPTION 'Invitation no longer pending' USING ERRCODE = '55000';
                END IF;
                PERFORM 1 FROM request_engine.principals AS p
                    JOIN request_engine.staff_memberships AS m ON m.principal_id = p.id
                        AND m.organization_id = p.organization_id AND m.status = 'active'
                    JOIN request_engine.principal_authority_grants AS g ON g.principal_id = p.id
                        AND g.organization_id = p.organization_id AND g.status = 'active'
                        AND g.capability_key = 'staff.invite'
                    WHERE p.id = v_invitation.invited_by_principal_id
                        AND p.organization_id = v_invitation.organization_id
                        AND p.active AND p.principal_kind = 'human' AND p.principal_plane = 'tenant'
                    AND EXISTS (
                        SELECT 1 FROM request_engine.identity_bindings b
                        JOIN request_engine.identity_authorities a
                            ON a.id=b.identity_authority_id AND a.status='active'
                        LEFT JOIN request_engine.native_identities n
                            ON a.kind='native' AND n.id::text=b.subject_id
                            AND n.identity_authority_id=a.id
                        WHERE b.principal_id=p.id AND b.organization_id=p.organization_id
                            AND b.status='active'
                            AND (a.kind <> 'native' OR n.status='active')
                    ) FOR SHARE OF p,m,g;
                IF NOT FOUND THEN RAISE EXCEPTION 'Inviter authority withdrawn' USING ERRCODE =
                '42501'; END IF;
            END IF;
            PERFORM set_config('request_engine.organization_id',
                v_invitation.organization_id::text,true);
            PERFORM set_config('request_engine.staff_invitation_id',p_id::text,true);
            PERFORM set_config('request_engine.staff_invitation_subject',p_identity::text,true);
            RETURN NEXT v_invitation;
        END $$;
        ALTER FUNCTION request_cmd.lock_staff_invitation_acceptance(uuid,text,uuid,uuid,uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
                request_cmd.lock_staff_invitation_acceptance(uuid,text,uuid,uuid,uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
                request_cmd.lock_staff_invitation_acceptance(uuid,text,uuid,uuid,uuid)
            TO request_engine_app;

        CREATE FUNCTION request_cmd.materialize_invited_staff(
            p_id uuid,p_digest text,p_authority uuid,p_identity uuid,p_session uuid,p_membership
                uuid,p_principal uuid,p_binding uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_invitation request_engine.staff_invitations%ROWTYPE; v_anchor uuid;
        BEGIN
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
        ALTER FUNCTION request_cmd.materialize_invited_staff(
            uuid,text,uuid,uuid,uuid,uuid,uuid,uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
                request_cmd.materialize_invited_staff(uuid,text,uuid,uuid,uuid,uuid,uuid,uuid)
                FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
                request_cmd.materialize_invited_staff(uuid,text,uuid,uuid,uuid,uuid,uuid,uuid)
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION request_cmd.materialize_invited_staff(
            uuid,text,uuid,uuid,uuid,uuid,uuid,uuid);
        DROP FUNCTION request_cmd.lock_staff_invitation_acceptance(uuid,text,uuid,uuid,uuid);
        DROP FUNCTION request_cmd.lock_staff_invitation_admin(uuid);
        DROP FUNCTION IF EXISTS request_auth.staff_invitation_target(uuid,text);
        DROP TABLE request_engine.staff_invitation_deliveries;
        DROP TABLE request_engine.staff_invitations;
        DROP FUNCTION request_engine.guard_staff_invitation();
        DROP FUNCTION request_cmd.assert_staff_invitation_manager();
        ALTER TABLE request_engine.staff_memberships DROP CONSTRAINT staff_memberships_org_id_uq;
    """)
