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
-- concern only currently actionable rows. Worker due/reclaim indexes are
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

-- Shared-capacity conflict detection joins append-only root history to the
-- currently live CapacityClaim set by claim id. A range-only GiST was measured
-- and rejected: PostgreSQL still preferred scanning all CapacityClaim history.
-- Keep a physically small partial B-tree over live claim ids instead, allowing
-- the planner to join the live subset to shared_capacity_claim_links without
-- walking released/replaced history. The resource-leading GiST from 042 remains
-- the correct access path for local Booking overlap checks.
CREATE INDEX capacity_claims_active_id_idx
    ON request_engine.capacity_claims (id)
    WHERE status = 'active';

RESET search_path;
RESET ROLE;
COMMIT;
