"""Let a tenant manager delegate exact business-Party Representation scopes to staff.

Business need: a staff member holding the configuration capabilities (for example
``organization.manage_profile``, ``catalog.manage``, ``booking.manage_supply``)
still needs an exact active ``operations.manage_*`` Representation of the business
Party. Until now only the provisioned controller (and a holder of
``organization.bootstrap``, for itself) could hold one, so delegated administrators
were refused. This migration adds the narrow owner write behind the Tenancy
operation ``staff_manage_representations`` (capability ``staff.manage_authority``).

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Tenancy (staff authority / Party Representation).
* Guarantees: INV-AUTHORITY-001, INV-TENANT-001, INV-PRIVILEGE-001,
  INV-IDEMPOTENCY-001 (Python owner), INV-PROVENANCE-001 and the new
  INV-STAFF-REPRESENTATION-001.
* Change class: CONTROLLED additive. ``request_engine.representations`` gains
  ``delegable`` (default true: every pre-existing row was created by root
  provisioning or by self-bootstrap, the only previous writers),
  ``granted_by_principal_id`` and ``provenance_reference`` (staff-delegation
  provenance), and ``revoked_at``/``revoked_by_principal_id``. A CHECK requires a
  grantor and provenance for every non-delegable row; a guard trigger makes the
  delegation provenance columns immutable. One SECURITY DEFINER function
  ``request_engine.replace_staff_representations`` is added and granted only to
  ``request_engine_app``.
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT: Python validates and acquires idempotency;
  the function acquires the shared identity-topology gate, the tenant staff root
  and the current HUMAN ``staff.manage_authority`` manager (actor Principal FOR
  SHARE), then the target active membership and target Principal FOR UPDATE
  (exact authority revision), then the authority Party FOR SHARE (Principal
  before Party, as every Representation reader and the bootstrap writer), then
  the actor's own delegable Representation rows FOR SHARE, then writes target
  Representation rows (their trigger bumps the already locked target Principal).
* Ceiling: each added scope requires the actor to hold an active, currently
  valid, delegable Representation of the same Party and scope. Rows written here
  are never delegable (no re-delegation chain). Only non-delegable rows inside the
  actor's ceiling are revoked; delegable (root/bootstrap) rows are never touched,
  so this operation cannot strip a controller's root Representation. Self-target
  and non-HUMAN targets are refused.
* Tenant/RLS/roles: no new table, role or RLS policy. Runtime role ACLs on the
  table are unchanged.
* Failure/concurrency: stale revision 40001, missing/foreign membership or Party
  P0002, ceiling/self/kind 42501, invalid scope/provenance 22023. Supported staff
  writers serialize on the tenant staff root.
* Roll-forward: no backfill of new authority; existing rows become delegable by
  default, which matches their provenance. Downgrade drops the function, trigger
  and columns only when no non-delegable row exists.
* Also: ``request_engine.staff_invitations.delivery_channel`` ('email' default,
  'link') records how the current proof generation was handed over. Owner:
  Tenancy. It is metadata, not authority; acceptance still requires the proof
  digest, expiry, pending status and a native HUMAN session. Existing rows are
  email invitations, matching the default.
* Falsification: tests/db/test_staff_representation_delegation.py (ceiling,
  re-delegation, root protection, revision, tenant opacity, restricted role) and
  tests/e2e/test_staff_representation_delegation_http.py (delegated admin
  configures; revocation denies the very next request).
"""

from alembic import op

revision: str = "0005_staff_representations"
down_revision: str | None = "0003_tenant_controller_v10"
branch_labels: str | None = None
depends_on: str | None = None

_SCOPES = (
    "'operations.manage_profile','operations.manage_supply',"
    "'operations.manage_terms','operations.manage_discovery'"
)


def upgrade() -> None:
    op.execute(f"""
-- Staff invitation delivery channel (display/audit metadata of the current
-- generation). 'link' means the inviter received the proof once in the command
-- response; only its SHA256 digest is stored, exactly as for email.
ALTER TABLE request_engine.staff_invitations
    ADD COLUMN delivery_channel text DEFAULT 'email' NOT NULL,
    ADD CONSTRAINT staff_invitations_delivery_channel_check
        CHECK (delivery_channel IN ('email', 'link'));

ALTER TABLE request_engine.representations
    ADD COLUMN delegable boolean DEFAULT true NOT NULL,
    ADD COLUMN granted_by_principal_id uuid,
    ADD COLUMN provenance_reference text,
    ADD COLUMN revoked_at timestamp with time zone,
    ADD COLUMN revoked_by_principal_id uuid,
    ADD CONSTRAINT representations_delegation_provenance_check CHECK (
        (granted_by_principal_id IS NULL) = (provenance_reference IS NULL)
        AND (delegable OR granted_by_principal_id IS NOT NULL)
        AND (provenance_reference IS NULL
             OR length(btrim(provenance_reference)) BETWEEN 1 AND 500)
    ),
    ADD CONSTRAINT representations_revocation_check CHECK (
        (status = 'revoked') OR (revoked_at IS NULL AND revoked_by_principal_id IS NULL)
    ),
    ADD CONSTRAINT representations_granted_by_principal_fkey
        FOREIGN KEY (organization_id, granted_by_principal_id)
        REFERENCES request_engine.principals(organization_id, id),
    ADD CONSTRAINT representations_revoked_by_principal_fkey
        FOREIGN KEY (organization_id, revoked_by_principal_id)
        REFERENCES request_engine.principals(organization_id, id);

CREATE FUNCTION request_engine.guard_representation_delegation_provenance()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF NEW.delegable IS DISTINCT FROM OLD.delegable
       OR NEW.granted_by_principal_id IS DISTINCT FROM OLD.granted_by_principal_id
       OR NEW.provenance_reference IS DISTINCT FROM OLD.provenance_reference THEN
        RAISE EXCEPTION 'Representation delegation provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
ALTER FUNCTION request_engine.guard_representation_delegation_provenance()
    OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_engine.guard_representation_delegation_provenance()
    FROM PUBLIC;
CREATE TRIGGER representations_delegation_provenance_guard
    BEFORE UPDATE ON request_engine.representations
    FOR EACH ROW EXECUTE FUNCTION request_engine.guard_representation_delegation_provenance();

CREATE FUNCTION request_engine.replace_staff_representations(
    p_membership_id uuid,
    p_authority_party_id uuid,
    p_expected_authority_revision bigint,
    p_desired_scopes text[],
    p_provenance_reference text
) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_actor_id uuid;
            v_target_id uuid;
            v_target_kind text;
            v_current_revision bigint;
            v_scope text;
            v_desired text[] := COALESCE(p_desired_scopes, ARRAY[]::text[]);
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('staff.manage_authority');

            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR EXISTS (
                   SELECT 1 FROM unnest(v_desired) AS scope
                    WHERE scope IS NULL OR scope NOT IN ({_SCOPES})
               )
               OR cardinality(v_desired)
                  <> cardinality(ARRAY(SELECT DISTINCT scope FROM unnest(v_desired) AS scope))
            THEN
                RAISE EXCEPTION 'Desired staff Representation scopes are invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT membership.principal_id
              INTO v_target_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.id = p_membership_id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Staff membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff Representation self-delegation is forbidden'
                    USING ERRCODE = '42501';
            END IF;

            SELECT authority_revision, principal_kind
              INTO v_current_revision, v_target_kind
              FROM request_engine.principals
             WHERE organization_id = v_org_id
               AND id = v_target_id
               AND active
               AND principal_plane = 'tenant'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Staff membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_kind <> 'human' THEN
                RAISE EXCEPTION 'Staff Representation delegation requires a HUMAN target'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Staff authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            PERFORM 1
              FROM request_engine.parties
             WHERE organization_id = v_org_id
               AND id = p_authority_party_id
               AND active
               AND party_kind = 'organization'
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Authority Party not found'
                    USING ERRCODE = 'P0002';
            END IF;

            -- The actor's delegable ceiling for this Party, locked once.
            PERFORM 1
              FROM request_engine.representations AS actor_rep
             WHERE actor_rep.organization_id = v_org_id
               AND actor_rep.principal_id = v_actor_id
               AND actor_rep.represented_party_id = p_authority_party_id
               AND actor_rep.status = 'active'
               AND actor_rep.delegable
             FOR SHARE;

            FOREACH v_scope IN ARRAY v_desired LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.representations AS actor_rep
                     WHERE actor_rep.organization_id = v_org_id
                       AND actor_rep.principal_id = v_actor_id
                       AND actor_rep.represented_party_id = p_authority_party_id
                       AND actor_rep.scope_key = v_scope
                       AND actor_rep.authority_kind = 'delegated'
                       AND actor_rep.status = 'active'
                       AND actor_rep.delegable
                       AND actor_rep.valid_from <= clock_timestamp()
                       AND (actor_rep.valid_until IS NULL
                            OR actor_rep.valid_until > clock_timestamp())
                ) THEN
                    RAISE EXCEPTION 'Desired Representation exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            -- Revoke only staff-delegated rows inside the actor's ceiling.
            UPDATE request_engine.representations AS target_rep
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE target_rep.organization_id = v_org_id
               AND target_rep.principal_id = v_target_id
               AND target_rep.represented_party_id = p_authority_party_id
               AND target_rep.status = 'active'
               AND NOT target_rep.delegable
               AND target_rep.scope_key IN ({_SCOPES})
               AND NOT (target_rep.scope_key = ANY(v_desired))
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.representations AS actor_rep
                    WHERE actor_rep.organization_id = v_org_id
                      AND actor_rep.principal_id = v_actor_id
                      AND actor_rep.represented_party_id = p_authority_party_id
                      AND actor_rep.scope_key = target_rep.scope_key
                      AND actor_rep.status = 'active'
                      AND actor_rep.delegable
               );

            FOREACH v_scope IN ARRAY v_desired LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.representations AS target_rep
                     WHERE target_rep.organization_id = v_org_id
                       AND target_rep.principal_id = v_target_id
                       AND target_rep.represented_party_id = p_authority_party_id
                       AND target_rep.scope_key = v_scope
                       AND target_rep.status = 'active'
                       AND target_rep.valid_from <= clock_timestamp()
                       AND (target_rep.valid_until IS NULL
                            OR target_rep.valid_until > clock_timestamp())
                ) THEN
                    INSERT INTO request_engine.representations (
                        organization_id, principal_id, represented_party_id,
                        authority_kind, scope_key, valid_until, delegable,
                        granted_by_principal_id, provenance_reference
                    ) VALUES (
                        v_org_id, v_target_id, p_authority_party_id,
                        'delegated', v_scope, NULL, false,
                        v_actor_id, btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;

            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE organization_id = v_org_id
               AND id = v_target_id;
            RETURN v_current_revision;
        END
        $$;
ALTER FUNCTION request_engine.replace_staff_representations(uuid, uuid, bigint, text[], text)
    OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION
    request_engine.replace_staff_representations(uuid, uuid, bigint, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    request_engine.replace_staff_representations(uuid, uuid, bigint, text[], text)
    TO request_engine_app;
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM request_engine.representations WHERE NOT delegable) THEN
        RAISE EXCEPTION 'staff-delegated Representations exist; roll forward instead';
    END IF;
END $$;
DROP FUNCTION request_engine.replace_staff_representations(uuid, uuid, bigint, text[], text);
DROP TRIGGER representations_delegation_provenance_guard ON request_engine.representations;
DROP FUNCTION request_engine.guard_representation_delegation_provenance();
ALTER TABLE request_engine.representations
    DROP CONSTRAINT representations_revoked_by_principal_fkey,
    DROP CONSTRAINT representations_granted_by_principal_fkey,
    DROP CONSTRAINT representations_revocation_check,
    DROP CONSTRAINT representations_delegation_provenance_check,
    DROP COLUMN revoked_by_principal_id,
    DROP COLUMN revoked_at,
    DROP COLUMN provenance_reference,
    DROP COLUMN granted_by_principal_id,
    DROP COLUMN delegable;
ALTER TABLE request_engine.staff_invitations
    DROP CONSTRAINT staff_invitations_delivery_channel_check,
    DROP COLUMN delivery_channel;
""")
