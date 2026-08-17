BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- Catalog fitness requires every foreign key to have a matching prefix index.
-- These global control-plane relations are expected to remain small initially,
-- but indexed FK lookups also keep deletes/retirement checks bounded as the
-- authority history grows.
CREATE INDEX shared_capacity_identities_global_identity_idx
    ON request_engine.shared_capacity_identities (global_identity_id);
CREATE INDEX shared_capacity_authority_events_global_identity_idx
    ON request_engine.shared_capacity_authority_events (global_identity_id);
CREATE INDEX shared_capacity_authority_events_shared_capacity_idx
    ON request_engine.shared_capacity_authority_events (shared_capacity_identity_id);

-- 022 grants request_engine_admin ALL on future request_engine tables by
-- default. These five relations are intentionally different: direct mutation
-- would bypass the audited request_admin.* authority functions. Keep the
-- privileged control-plane role read-only on private state and let the
-- SECURITY DEFINER command surfaces own all mutation.
REVOKE ALL ON request_engine.global_identities,
              request_engine.shared_capacity_identities,
              request_engine.shared_capacity_bindings,
              request_engine.shared_capacity_claim_links,
              request_engine.shared_capacity_authority_events
    FROM request_engine_admin;
GRANT SELECT ON request_engine.global_identities,
                request_engine.shared_capacity_identities,
                request_engine.shared_capacity_bindings,
                request_engine.shared_capacity_claim_links,
                request_engine.shared_capacity_authority_events
    TO request_engine_admin;

-- The runtime surface must enforce, rather than merely document, the canonical
-- Resource -> SharedCapacityIdentity lock order. request_engine_app can execute
-- this function directly, so relying on the caller to have already locked the
-- Resources would permit an out-of-order shared-root lock and cross-tenant
-- denial-of-service/deadlock amplification. Normal Booking callers already hold
-- these Resource locks; re-acquiring them in the same transaction is harmless.
CREATE OR REPLACE FUNCTION request_cmd.lock_shared_capacity_roots(
    p_organization_id uuid,
    p_resource_ids uuid[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_context_organization_id uuid;
    v_requested bigint;
    v_local bigint := 0;
    v_resource_id uuid;
BEGIN
    v_context_organization_id := request_engine.current_organization_id();
    IF v_context_organization_id IS NULL
       OR p_organization_id IS NULL
       OR p_organization_id <> v_context_organization_id
    THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT count(DISTINCT value)
      INTO v_requested
      FROM unnest(COALESCE(p_resource_ids, ARRAY[]::uuid[])) AS input(value)
     WHERE value IS NOT NULL;

    IF v_requested = 0 THEN
        RETURN;
    END IF;

    -- Validate tenant ownership and take every local root in the same stable
    -- order used by Booking. Counting while locking prevents this protected
    -- function from ever acquiring a shared root first.
    FOR v_resource_id IN
        SELECT r.id
          FROM request_engine.resources r
         WHERE r.organization_id = p_organization_id
           AND r.id = ANY(p_resource_ids)
         ORDER BY r.id
         FOR UPDATE
    LOOP
        v_local := v_local + 1;
    END LOOP;

    IF v_local <> v_requested THEN
        RAISE EXCEPTION 'one or more Resources are not available in tenant context'
            USING ERRCODE = '42501';
    END IF;

    PERFORM 1
      FROM request_engine.shared_capacity_identities s
      JOIN request_engine.shared_capacity_bindings b
        ON b.shared_capacity_identity_id = s.id
       AND b.status = 'active'
     WHERE b.organization_id = p_organization_id
       AND b.resource_id = ANY(p_resource_ids)
       AND s.status = 'active'
     ORDER BY s.id
     FOR UPDATE OF s;
END
$function$;

-- RLS WITH CHECK is evaluated after BEFORE ROW triggers. guard_capacity_claim()
-- is SECURITY DEFINER so it can see private cross-tenant provenance; therefore
-- a request_engine_app statement must be rejected on tenant context before that
-- privileged trigger is allowed to inspect any referenced Resource/Hold/etc.
-- The numeric prefix intentionally makes this trigger run before the existing
-- capacity_claims_guard_capacity trigger.
CREATE FUNCTION request_engine.guard_capacity_claim_tenant_context()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_context_organization_id uuid;
BEGIN
    IF current_user = 'request_engine_app'
       OR pg_catalog.pg_has_role(current_user, 'request_engine_app', 'MEMBER')
    THEN
        v_context_organization_id := request_engine.current_organization_id();
        IF v_context_organization_id IS NULL
           OR NEW.organization_id IS DISTINCT FROM v_context_organization_id
        THEN
            RAISE EXCEPTION 'capacity claim organization context mismatch'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_00_guard_tenant_context
BEFORE INSERT OR UPDATE ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_tenant_context();

-- CapacityClaim history is monotonic. A released claim may still advance to
-- replaced when Reschedule wires its replacement claim, but inactive history
-- must never become active again. Once release/replacement provenance exists,
-- its timestamp and replacement edge cannot be rewritten later.
CREATE FUNCTION request_engine.guard_capacity_claim_terminal_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.status = 'replaced' THEN
        IF NEW.status <> 'replaced'
           OR NEW.released_at IS DISTINCT FROM OLD.released_at
           OR NEW.replaced_by_claim_id IS DISTINCT FROM OLD.replaced_by_claim_id
        THEN
            RAISE EXCEPTION 'terminal CapacityClaim % cannot be rewritten', OLD.id
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'released' THEN
        IF NEW.status NOT IN ('released', 'replaced') THEN
            RAISE EXCEPTION 'terminal CapacityClaim % cannot reactivate from released to %',
                OLD.id, NEW.status
                USING ERRCODE = '23514';
        END IF;
        IF NEW.released_at IS DISTINCT FROM OLD.released_at THEN
            RAISE EXCEPTION 'released CapacityClaim % release timestamp is immutable', OLD.id
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'released'
           AND NEW.replaced_by_claim_id IS DISTINCT FROM OLD.replaced_by_claim_id
        THEN
            RAISE EXCEPTION 'released CapacityClaim % replacement edge requires replaced status', OLD.id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_guard_terminal_transition
BEFORE UPDATE OF status, released_at, replaced_by_claim_id ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_terminal_transition();

-- A promoted claim retains its Hold id as provenance. That provenance is only
-- meaningful if the Hold and Reservation describe the same subject, offering,
-- location and interval; otherwise raw SQL could attribute one subject's held
-- capacity to another Reservation while satisfying aggregate claim counts.
CREATE FUNCTION request_engine.guard_promoted_capacity_claim_owner()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_matches boolean;
BEGIN
    IF NEW.status <> 'active'
       OR NEW.hold_id IS NULL
       OR NEW.reservation_id IS NULL
    THEN
        RETURN NEW;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM request_engine.capacity_holds h
          JOIN request_engine.reservations r
            ON r.organization_id = h.organization_id
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id
           AND r.id = NEW.reservation_id
           AND h.offering_version_id = r.offering_version_id
           AND h.subject_party_id = r.subject_party_id
           AND h.location_id IS NOT DISTINCT FROM r.location_id
           AND h.during = r.during
    ) INTO v_matches;

    IF NOT v_matches THEN
        RAISE EXCEPTION 'promoted CapacityClaim Hold/Reservation provenance mismatch'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_guard_promoted_owner
BEFORE INSERT OR UPDATE OF hold_id, reservation_id, status
ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_promoted_capacity_claim_owner();

-- SharedCapacityClaimLink is append-only, so the material claim facts it
-- explains must not be rewritable underneath it. Lifecycle fields may advance,
-- and an active Hold claim may acquire its Reservation id exactly once during
-- Hold confirmation, but tenant/resource/requirement/interval/quantity/source
-- provenance is immutable after the link exists.
CREATE FUNCTION request_engine.guard_linked_capacity_claim_provenance()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_linked boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_claim_links link
         WHERE link.capacity_claim_id = OLD.id
    ) INTO v_linked;

    IF NOT v_linked THEN
        RETURN NEW;
    END IF;

    IF OLD.id IS DISTINCT FROM NEW.id
       OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.requirement_id IS DISTINCT FROM NEW.requirement_id
       OR OLD.hold_id IS DISTINCT FROM NEW.hold_id
       OR OLD.during IS DISTINCT FROM NEW.during
       OR OLD.quantity IS DISTINCT FROM NEW.quantity
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'linked CapacityClaim material provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.reservation_id IS NOT NULL
       AND NEW.reservation_id IS DISTINCT FROM OLD.reservation_id
    THEN
        RAISE EXCEPTION 'linked CapacityClaim Reservation provenance cannot be rewritten'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.reservation_id IS NULL
       AND NEW.reservation_id IS NOT NULL
       AND (OLD.status <> 'active' OR NEW.status <> 'active')
    THEN
        RAISE EXCEPTION 'only an active linked Hold claim may be promoted to a Reservation'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_guard_linked_provenance
BEFORE UPDATE ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_linked_capacity_claim_provenance();

-- A Resource may be re-authorized after revocation, including back to the same
-- SharedCapacityIdentity. It may not, however, be moved to a different shared
-- root while a live CapacityClaim still carries historical serialization
-- provenance for the old root. That would make one physical commitment stop
-- consuming the old root and ambiguously start consuming another.
CREATE FUNCTION request_engine.guard_shared_capacity_rebinding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims c
          JOIN request_engine.shared_capacity_claim_links link
            ON link.capacity_claim_id = c.id
          LEFT JOIN request_engine.reservations r
            ON r.organization_id = c.organization_id
           AND r.id = c.reservation_id
          LEFT JOIN request_engine.capacity_holds h
            ON h.organization_id = c.organization_id
           AND h.id = c.hold_id
         WHERE c.organization_id = NEW.organization_id
           AND c.resource_id = NEW.resource_id
           AND link.shared_capacity_identity_id <> NEW.shared_capacity_identity_id
           AND c.status = 'active'
           AND (
               (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
               OR
               (c.reservation_id IS NULL AND h.status = 'active'
                AND h.expires_at > clock_timestamp())
           )
    ) THEN
        RAISE EXCEPTION 'Resource has live commitments bound to another shared capacity root'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER shared_capacity_bindings_guard_rebinding
BEFORE INSERT ON request_engine.shared_capacity_bindings
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_shared_capacity_rebinding();

-- Trigger functions are internal implementation details. PostgreSQL grants
-- EXECUTE on new functions to PUBLIC by default unless the default privilege
-- hardening is present; restate the deny explicitly for reviewability.
REVOKE ALL ON FUNCTION request_engine.guard_shared_capacity_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_shared_capacity_rebinding() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_tenant_context() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_terminal_transition() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_promoted_capacity_claim_owner() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_linked_capacity_claim_provenance() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;