BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, request_admin, pg_catalog;

-- Cross-tenant shared capacity is an internal control-plane capability.  The
-- global identity tables intentionally contain no tenant-readable PII and are
-- not granted to ordinary runtime roles.
CREATE TABLE request_engine.global_identities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    identity_kind text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    evidence_ref text,
    created_authority_ref text NOT NULL,
    creation_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    retired_at timestamptz,
    CHECK (identity_kind IN ('person', 'organization')),
    CHECK (status IN ('active', 'retired')),
    CHECK (created_authority_ref <> ''),
    CHECK (creation_reason <> ''),
    CHECK ((status = 'retired') = (retired_at IS NOT NULL))
);

CREATE TABLE request_engine.shared_capacity_identities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    global_identity_id uuid NOT NULL
        REFERENCES request_engine.global_identities(id),
    status text NOT NULL DEFAULT 'active',
    created_authority_ref text NOT NULL,
    creation_reason text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    retired_at timestamptz,
    CHECK (status IN ('active', 'retired')),
    CHECK (created_authority_ref <> ''),
    CHECK (creation_reason <> ''),
    CHECK (revision > 0),
    CHECK ((status = 'retired') = (retired_at IS NOT NULL))
);

CREATE TABLE request_engine.shared_capacity_bindings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    shared_capacity_identity_id uuid NOT NULL
        REFERENCES request_engine.shared_capacity_identities(id),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'active',
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    authorized_by text NOT NULL,
    authorization_reason text NOT NULL,
    revoked_by text,
    revocation_reason text,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    CHECK (status IN ('active', 'revoked')),
    CHECK (authorized_by <> ''),
    CHECK (authorization_reason <> ''),
    CHECK (revision > 0),
    CHECK (valid_until IS NULL OR valid_until >= valid_from),
    CHECK (
        (status = 'active' AND valid_until IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL)
        OR
        (status = 'revoked' AND valid_until IS NOT NULL AND revoked_by IS NOT NULL
         AND revoked_by <> '' AND revocation_reason IS NOT NULL AND revocation_reason <> '')
    )
);

CREATE UNIQUE INDEX shared_capacity_bindings_one_active_resource_idx
    ON request_engine.shared_capacity_bindings (organization_id, resource_id)
    WHERE status = 'active';
CREATE INDEX shared_capacity_bindings_active_root_idx
    ON request_engine.shared_capacity_bindings (shared_capacity_identity_id, organization_id, resource_id)
    WHERE status = 'active';

-- This is serialization provenance only.  It deliberately does not duplicate
-- interval, quantity, status, owner, tenant or appointment data from
-- CapacityClaim, so CapacityClaim remains the sole capacity-consumption truth.
CREATE TABLE request_engine.shared_capacity_claim_links (
    capacity_claim_id uuid PRIMARY KEY
        REFERENCES request_engine.capacity_claims(id),
    shared_capacity_identity_id uuid NOT NULL
        REFERENCES request_engine.shared_capacity_identities(id),
    linked_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX shared_capacity_claim_links_root_idx
    ON request_engine.shared_capacity_claim_links (shared_capacity_identity_id, capacity_claim_id);

CREATE TABLE request_engine.shared_capacity_authority_events (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    event_kind text NOT NULL,
    global_identity_id uuid REFERENCES request_engine.global_identities(id),
    shared_capacity_identity_id uuid REFERENCES request_engine.shared_capacity_identities(id),
    binding_id uuid,
    resource_organization_id uuid,
    resource_id uuid,
    authority_ref text NOT NULL,
    reason text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_kind IN (
        'global_identity.created',
        'shared_capacity.created',
        'binding.activated',
        'binding.revoked'
    )),
    CHECK (authority_ref <> ''),
    CHECK (reason <> ''),
    CHECK (jsonb_typeof(details) = 'object')
);

ALTER TABLE request_engine.shared_capacity_bindings ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_capacity_bindings_tenant_isolation
    ON request_engine.shared_capacity_bindings
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

CREATE TRIGGER shared_capacity_bindings_touch
BEFORE UPDATE ON request_engine.shared_capacity_bindings
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE FUNCTION request_engine.guard_shared_capacity_binding()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.shared_capacity_identity_id <> NEW.shared_capacity_identity_id
       OR OLD.organization_id <> NEW.organization_id
       OR OLD.resource_id <> NEW.resource_id
       OR OLD.valid_from <> NEW.valid_from
       OR OLD.authorized_by <> NEW.authorized_by
       OR OLD.authorization_reason <> NEW.authorization_reason
       OR OLD.created_at <> NEW.created_at
    THEN
        RAISE EXCEPTION 'SharedCapacityBinding identity and creation provenance are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked SharedCapacityBinding cannot be reactivated'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'SharedCapacityBinding revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER shared_capacity_bindings_guard
BEFORE UPDATE ON request_engine.shared_capacity_bindings
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_shared_capacity_binding();

CREATE TRIGGER shared_capacity_claim_links_append_only
BEFORE UPDATE OR DELETE ON request_engine.shared_capacity_claim_links
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER shared_capacity_authority_events_append_only
BEFORE UPDATE OR DELETE ON request_engine.shared_capacity_authority_events
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

-- -------------------------------------------------------------------------
-- Trusted control-plane authority
-- -------------------------------------------------------------------------

CREATE FUNCTION request_admin.create_global_identity(
    p_identity_kind text,
    p_evidence_ref text,
    p_authority_ref text,
    p_reason text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_id uuid;
BEGIN
    IF p_identity_kind NOT IN ('person', 'organization')
       OR p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid GlobalIdentity authority request'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO request_engine.global_identities (
        identity_kind, evidence_ref, created_authority_ref, creation_reason
    ) VALUES (
        p_identity_kind, NULLIF(btrim(p_evidence_ref), ''), btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, global_identity_id, authority_ref, reason
    ) VALUES (
        'global_identity.created', v_id, btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_id;
END
$function$;

CREATE FUNCTION request_admin.create_shared_capacity_identity(
    p_global_identity_id uuid,
    p_authority_ref text,
    p_reason text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_id uuid;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityIdentity authority request'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
      FROM request_engine.global_identities
     WHERE id = p_global_identity_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GlobalIdentity is not active'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO request_engine.shared_capacity_identities (
        global_identity_id, created_authority_ref, creation_reason
    ) VALUES (
        p_global_identity_id, btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, global_identity_id, shared_capacity_identity_id,
        authority_ref, reason
    ) VALUES (
        'shared_capacity.created', p_global_identity_id, v_id,
        btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_id;
END
$function$;

CREATE FUNCTION request_admin.activate_shared_capacity_binding(
    p_organization_id uuid,
    p_resource_id uuid,
    p_shared_capacity_identity_id uuid,
    p_authority_ref text,
    p_reason text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_binding_id uuid;
    v_capacity_model text;
    v_conflict boolean;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityBinding authority request'
            USING ERRCODE = '22023';
    END IF;

    -- Canonical lock order: tenant-local Resource first, shared root second.
    SELECT capacity_model
      INTO v_capacity_model
      FROM request_engine.resources
     WHERE organization_id = p_organization_id
       AND id = p_resource_id
       AND active
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource is not active'
            USING ERRCODE = '22023';
    END IF;
    IF v_capacity_model <> 'exclusive' THEN
        RAISE EXCEPTION 'initial shared-capacity bindings require exclusive Resource capacity'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
      FROM request_engine.shared_capacity_identities
     WHERE id = p_shared_capacity_identity_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SharedCapacityIdentity is not active'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_bindings
         WHERE organization_id = p_organization_id
           AND resource_id = p_resource_id
           AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'Resource already has an active SharedCapacityBinding'
            USING ERRCODE = '23505';
    END IF;

    -- Activating a binding must not turn already-valid commitments into an
    -- overlap.  Existing live claims on this Resource become linked only after
    -- this check succeeds while both serialization roots are held.
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims local_claim
          JOIN request_engine.shared_capacity_claim_links foreign_link
            ON foreign_link.shared_capacity_identity_id = p_shared_capacity_identity_id
          JOIN request_engine.capacity_claims foreign_claim
            ON foreign_claim.id = foreign_link.capacity_claim_id
          LEFT JOIN request_engine.reservations local_reservation
            ON local_reservation.organization_id = local_claim.organization_id
           AND local_reservation.id = local_claim.reservation_id
          LEFT JOIN request_engine.capacity_holds local_hold
            ON local_hold.organization_id = local_claim.organization_id
           AND local_hold.id = local_claim.hold_id
          LEFT JOIN request_engine.reservations foreign_reservation
            ON foreign_reservation.organization_id = foreign_claim.organization_id
           AND foreign_reservation.id = foreign_claim.reservation_id
          LEFT JOIN request_engine.capacity_holds foreign_hold
            ON foreign_hold.organization_id = foreign_claim.organization_id
           AND foreign_hold.id = foreign_claim.hold_id
         WHERE local_claim.organization_id = p_organization_id
           AND local_claim.resource_id = p_resource_id
           AND local_claim.status = 'active'
           AND foreign_claim.status = 'active'
           AND foreign_claim.id <> local_claim.id
           AND foreign_claim.during && local_claim.during
           AND (
               (local_claim.reservation_id IS NOT NULL AND local_reservation.status = 'confirmed')
               OR
               (local_claim.reservation_id IS NULL AND local_hold.status = 'active'
                AND local_hold.expires_at > clock_timestamp())
           )
           AND (
               (foreign_claim.reservation_id IS NOT NULL AND foreign_reservation.status = 'confirmed')
               OR
               (foreign_claim.reservation_id IS NULL AND foreign_hold.status = 'active'
                AND foreign_hold.expires_at > clock_timestamp())
           )
    ) INTO v_conflict;

    IF v_conflict THEN
        RAISE EXCEPTION 'capacity unavailable'
            USING ERRCODE = '23P01';
    END IF;

    INSERT INTO request_engine.shared_capacity_bindings (
        shared_capacity_identity_id, organization_id, resource_id,
        authorized_by, authorization_reason
    ) VALUES (
        p_shared_capacity_identity_id, p_organization_id, p_resource_id,
        btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_binding_id;

    INSERT INTO request_engine.shared_capacity_claim_links (
        capacity_claim_id, shared_capacity_identity_id
    )
    SELECT c.id, p_shared_capacity_identity_id
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = p_organization_id
       AND c.resource_id = p_resource_id
       AND c.status = 'active'
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
           OR
           (c.reservation_id IS NULL AND h.status = 'active'
            AND h.expires_at > clock_timestamp())
       )
    ON CONFLICT (capacity_claim_id) DO NOTHING;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, shared_capacity_identity_id, binding_id,
        resource_organization_id, resource_id, authority_ref, reason
    ) VALUES (
        'binding.activated', p_shared_capacity_identity_id, v_binding_id,
        p_organization_id, p_resource_id, btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_binding_id;
END
$function$;

CREATE FUNCTION request_admin.revoke_shared_capacity_binding(
    p_binding_id uuid,
    p_authority_ref text,
    p_reason text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_binding request_engine.shared_capacity_bindings%ROWTYPE;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityBinding revocation request'
            USING ERRCODE = '22023';
    END IF;

    SELECT *
      INTO v_binding
      FROM request_engine.shared_capacity_bindings
     WHERE id = p_binding_id;
    IF NOT FOUND OR v_binding.status <> 'active' THEN
        RAISE EXCEPTION 'SharedCapacityBinding is not active'
            USING ERRCODE = '22023';
    END IF;

    -- Same canonical order as booking/activation: Resource, then shared root.
    PERFORM 1
      FROM request_engine.resources
     WHERE organization_id = v_binding.organization_id
       AND id = v_binding.resource_id
     FOR UPDATE;
    PERFORM 1
      FROM request_engine.shared_capacity_identities
     WHERE id = v_binding.shared_capacity_identity_id
     FOR UPDATE;

    -- Re-read after acquiring serialization roots so a concurrent transition
    -- cannot be applied based on the stale snapshot above.
    SELECT *
      INTO v_binding
      FROM request_engine.shared_capacity_bindings
     WHERE id = p_binding_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SharedCapacityBinding is not active'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.shared_capacity_bindings
       SET status = 'revoked',
           valid_until = clock_timestamp(),
           revoked_by = btrim(p_authority_ref),
           revocation_reason = btrim(p_reason),
           revision = revision + 1
     WHERE id = p_binding_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, shared_capacity_identity_id, binding_id,
        resource_organization_id, resource_id, authority_ref, reason
    ) VALUES (
        'binding.revoked', v_binding.shared_capacity_identity_id, p_binding_id,
        v_binding.organization_id, v_binding.resource_id,
        btrim(p_authority_ref), btrim(p_reason)
    );
END
$function$;

-- -------------------------------------------------------------------------
-- Runtime serialization surface.  Ordinary tenant code gets no global IDs
-- back: it can only ask the protected function to lock roots for Resources it
-- already owns.
-- -------------------------------------------------------------------------

CREATE FUNCTION request_cmd.lock_shared_capacity_roots(
    p_organization_id uuid,
    p_resource_ids uuid[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_requested bigint;
    v_local bigint;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
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

    SELECT count(*)
      INTO v_local
      FROM request_engine.resources
     WHERE organization_id = p_organization_id
       AND id = ANY(p_resource_ids);
    IF v_local <> v_requested THEN
        RAISE EXCEPTION 'one or more Resources are not available in tenant context'
            USING ERRCODE = '42501';
    END IF;

    -- Resource rows MUST already be locked by the caller.  Shared roots are
    -- then acquired in UUID order, yielding one global order for multi-resource
    -- booking and reschedule operations.
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

-- -------------------------------------------------------------------------
-- CapacityClaim defense-in-depth.  The function is SECURITY DEFINER solely so
-- it can compare against private links belonging to other tenants.  Errors do
-- not include foreign identifiers or tenant metadata.
-- -------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_capacity_model text;
    v_capacity_units integer;
    v_resource_active boolean;
    v_resource_location uuid;
    v_owner_offering_version uuid;
    v_owner_during tstzrange;
    v_owner_location uuid;
    v_requirement_offering_version uuid;
    v_required_capability uuid;
    v_required_quantity integer;
    v_other_quantity bigint;
    v_other_count bigint;
    v_promoting_hold boolean;
    v_shared_capacity_identity_id uuid;
    v_shared_conflict boolean;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT r.capacity_model, r.capacity_units, r.active, r.location_id
      INTO v_capacity_model, v_capacity_units, v_resource_active, v_resource_location
      FROM request_engine.resources r
     WHERE r.organization_id = NEW.organization_id
       AND r.id = NEW.resource_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % does not exist for capacity claim', NEW.resource_id
            USING ERRCODE = '23503';
    END IF;
    IF NOT v_resource_active THEN
        RAISE EXCEPTION 'Resource % is inactive', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.resource_id <> NEW.resource_id AND EXISTS (
        SELECT 1 FROM request_engine.shared_capacity_claim_links
         WHERE capacity_claim_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'linked CapacityClaim cannot move between Resources; release/recreate it'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.offering_version_id, r.during, r.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id
           AND r.status = 'confirmed';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'active reservation claim requires confirmed Reservation %', NEW.reservation_id
                USING ERRCODE = '23514';
        END IF;

        v_promoting_hold := NEW.hold_id IS NOT NULL AND (
            TG_OP = 'INSERT' OR OLD.reservation_id IS NULL
        );
        IF v_promoting_hold AND NOT EXISTS (
            SELECT 1
              FROM request_engine.capacity_holds h
             WHERE h.organization_id = NEW.organization_id
               AND h.id = NEW.hold_id
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
               AND h.offering_version_id = v_owner_offering_version
               AND h.during = v_owner_during
        ) THEN
            RAISE EXCEPTION 'cannot promote expired, terminal, or mismatched CapacityHold %', NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.hold_id IS NULL THEN
            RAISE EXCEPTION 'active hold claim requires CapacityHold'
                USING ERRCODE = '23514';
        END IF;
        SELECT h.offering_version_id, h.during, h.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id
           AND h.status = 'active'
           AND h.expires_at > clock_timestamp();
        IF NOT FOUND THEN
            RAISE EXCEPTION 'active hold claim requires live, unexpired CapacityHold %', NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.during <> v_owner_during THEN
        RAISE EXCEPTION 'CapacityClaim interval must equal its Hold/Reservation interval'
            USING ERRCODE = '23514';
    END IF;
    IF v_owner_location IS NOT NULL
       AND v_resource_location IS NOT NULL
       AND v_owner_location <> v_resource_location THEN
        RAISE EXCEPTION 'Resource % belongs to a different Location than the Hold/Reservation', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT rr.offering_version_id, rr.capability_id, rr.quantity
      INTO v_requirement_offering_version, v_required_capability, v_required_quantity
      FROM request_engine.offering_resource_requirements rr
     WHERE rr.organization_id = NEW.organization_id
       AND rr.id = NEW.requirement_id;
    IF NOT FOUND OR v_requirement_offering_version <> v_owner_offering_version THEN
        RAISE EXCEPTION 'CapacityClaim requirement does not belong to the owner OfferingVersion'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.quantity <> v_required_quantity THEN
        RAISE EXCEPTION 'CapacityClaim quantity % does not satisfy requirement quantity %', NEW.quantity, v_required_quantity
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM request_engine.resource_capability_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.resource_id = NEW.resource_id
           AND a.capability_id = v_required_capability
    ) THEN
        RAISE EXCEPTION 'Resource % does not satisfy required capability', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(sum(c.quantity), 0), count(*)
      INTO v_other_quantity, v_other_count
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id AND h.id = c.hold_id
     WHERE c.organization_id = NEW.organization_id
       AND c.resource_id = NEW.resource_id
       AND c.status = 'active'
       AND c.id <> NEW.id
       AND c.during && NEW.during
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
           (c.reservation_id IS NULL AND h.status = 'active' AND h.expires_at > clock_timestamp())
       );
    IF v_capacity_model = 'exclusive' AND v_other_count > 0 THEN
        RAISE EXCEPTION 'exclusive Resource % has overlapping live capacity', NEW.resource_id
            USING ERRCODE = '23P01';
    END IF;
    IF v_capacity_model = 'units' AND v_other_quantity + NEW.quantity > v_capacity_units THEN
        RAISE EXCEPTION 'Resource % capacity exceeded: requested %, live %, capacity %',
            NEW.resource_id, NEW.quantity, v_other_quantity, v_capacity_units
            USING ERRCODE = '23P01';
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        PERFORM 1
          FROM request_engine.shared_capacity_identities
         WHERE id = v_shared_capacity_identity_id
           AND status = 'active'
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;

        SELECT EXISTS (
            SELECT 1
              FROM request_engine.shared_capacity_claim_links link
              JOIN request_engine.capacity_claims c
                ON c.id = link.capacity_claim_id
              LEFT JOIN request_engine.reservations r
                ON r.organization_id = c.organization_id AND r.id = c.reservation_id
              LEFT JOIN request_engine.capacity_holds h
                ON h.organization_id = c.organization_id AND h.id = c.hold_id
             WHERE link.shared_capacity_identity_id = v_shared_capacity_identity_id
               AND c.id <> NEW.id
               AND c.status = 'active'
               AND c.during && NEW.during
               AND (
                   (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
                   (c.reservation_id IS NULL AND h.status = 'active'
                    AND h.expires_at > clock_timestamp())
               )
        ) INTO v_shared_conflict;

        IF v_shared_conflict THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

CREATE FUNCTION request_engine.attach_shared_capacity_claim_link()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_shared_capacity_identity_id uuid;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        INSERT INTO request_engine.shared_capacity_claim_links (
            capacity_claim_id, shared_capacity_identity_id
        ) VALUES (
            NEW.id, v_shared_capacity_identity_id
        )
        ON CONFLICT (capacity_claim_id) DO NOTHING;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_attach_shared_capacity
AFTER INSERT OR UPDATE OF resource_id, hold_id, reservation_id, status
ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.attach_shared_capacity_claim_link();

REVOKE ALL ON request_engine.global_identities FROM PUBLIC;
REVOKE ALL ON request_engine.shared_capacity_identities FROM PUBLIC;
REVOKE ALL ON request_engine.shared_capacity_bindings FROM PUBLIC;
REVOKE ALL ON request_engine.shared_capacity_claim_links FROM PUBLIC;
REVOKE ALL ON request_engine.shared_capacity_authority_events FROM PUBLIC;
REVOKE ALL ON request_engine.global_identities FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.shared_capacity_identities FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.shared_capacity_bindings FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.shared_capacity_claim_links FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.shared_capacity_authority_events FROM request_engine_app, request_engine_worker;

REVOKE ALL ON FUNCTION request_admin.create_global_identity(text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.create_shared_capacity_identity(uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.activate_shared_capacity_binding(uuid, uuid, uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.revoke_shared_capacity_binding(uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(uuid, uuid[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.attach_shared_capacity_claim_link() FROM PUBLIC;

GRANT SELECT ON request_engine.global_identities,
                request_engine.shared_capacity_identities,
                request_engine.shared_capacity_bindings,
                request_engine.shared_capacity_claim_links,
                request_engine.shared_capacity_authority_events
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.create_global_identity(text, text, text, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.create_shared_capacity_identity(uuid, text, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.activate_shared_capacity_binding(uuid, uuid, uuid, text, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.revoke_shared_capacity_binding(uuid, text, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.lock_shared_capacity_roots(uuid, uuid[])
    TO request_engine_app, request_engine_admin;

RESET search_path;
RESET ROLE;
COMMIT;
