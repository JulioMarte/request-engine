BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- G15 evidence showed that verified-contact selection otherwise walks every
-- contact point for the recipient party and filters verification state.
CREATE INDEX party_contact_points_verified_lookup_idx
    ON request_engine.party_contact_points (
        organization_id,
        party_id,
        created_at,
        id
    )
    WHERE active AND verified;

-- Communications dispatch/reconciliation checks are subject-specific and
-- concern only currently actionable rows.  Worker due/reclaim indexes are
-- intentionally different access paths and do not bound this lookup.
CREATE INDEX scheduled_actions_active_subject_idx
    ON request_engine.scheduled_actions (
        organization_id,
        owner_module,
        subject_kind,
        subject_id,
        action_type,
        action_version,
        execute_at
    )
    WHERE status IN ('pending', 'leased');

-- Shared-capacity conflict detection starts from a global shared-capacity root,
-- so it cannot use the resource-leading GiST from migration 042.  Restrict the
-- overlap index to live claims and key it directly by the temporal range.
CREATE INDEX capacity_claims_active_during_idx
    ON request_engine.capacity_claims USING gist (during)
    WHERE status = 'active';

RESET search_path;
RESET ROLE;
COMMIT;
