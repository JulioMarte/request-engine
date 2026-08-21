# Operational Profile & Contextual Supply — Relational Schema, As-Built Reconciliation

Status: as-built Phase C relational design/reconciliation for `feature/operational-profile-contextual-supply`.

Current executable migration:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

Normative semantic sources:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
docs/v3/13-operational-profile-contextual-supply-plan.md
docs/adr/0012-contextual-resource-location-supply.md
```

Historical clarification provenance:

```text
docs/v3/16-operational-profile-contextual-supply-clarifications.md
```

Current proof/status sources:

```text
docs/v3/20-operational-profile-contextual-supply-implementation-handoff.md
docs/v3/21-operational-profile-contextual-supply-documentation-audit.md
```

If this document and the executable migration disagree on a physical column, constraint, trigger, role grant or SQL implementation detail, `0002_f1_supply` is the executable truth and this document must be corrected. SQL does not override F1 product/transaction semantics merely by existing.

---

## 1. Greenfield consolidation decision

F1 originally evolved through provisional local revisions while schema, commercial provenance, shared-capacity compatibility and ACLs were being hardened.

Because no production/customer-owned F1 data or deployed F1 migration history existed, those provisional revisions were consolidated into one intended launch revision:

```text
0001_initial
  -> 0002_f1_supply
```

The consolidated revision contains:

```text
1. operational-profile/contextual-supply schema
2. immutable commercial commitment + multi-source provenance
3. contextual CapacityClaim assignment provenance
4. shared-capacity guard compatibility
5. final F1 RLS/runtime ACL hardening
```

Frozen/released provenance remains immutable:

```text
migrations/versions/0001_initial.py
migrations/sql/v3_candidate/*
migrations/sql/v3_initial/*
migrations/sql/design_chain/*
```

---

## 2. Compatibility principle

Released V3 structures remain valid:

```text
resources.location_id
availability_schedules
schedule_exceptions
reservations
capacity_holds
capacity_claims
```

F1 does not invent contextual history for legacy rows.

Resolver rule:

```text
Resource has contextual assignment history
  -> explicit ResourceLocationAssignment governs contextual Location eligibility

Resource has never entered contextual assignment semantics
  -> released V3 Resource/Location/schedule fallback remains available
```

Retiring contextual assignment history does not silently restore legacy wildcard Location semantics.

Legacy Reservations/CapacityClaims are not retroactively assigned prices or assignment provenance they never recorded.

---

## 3. Existing relations extended

### 3.1 `organizations`

Added:

```text
legal_name text NULL
default_timezone text NULL
default_locale text NULL
default_currency text NULL
operational_status text NOT NULL DEFAULT 'active'
```

Rules include nonblank optional strings, three-letter currency format and:

```text
operational_status IN ('active', 'inactive')
```

`organizations.display_name` remains the public/display identity.

### 3.2 `locations`

Added:

```text
address_line1 text NULL
address_line2 text NULL
locality text NULL
administrative_area text NULL
postal_code text NULL
country_code text NULL
latitude numeric(9,6) NULL
longitude numeric(9,6) NULL
geocoding_source text NULL
geocoded_at timestamptz NULL
operational_revision bigint NOT NULL DEFAULT 1
```

Rules:

```text
(latitude IS NULL) = (longitude IS NULL)
latitude BETWEEN -90 AND 90
longitude BETWEEN -180 AND 180
country_code matches ^[A-Z]{2}$ when present
operational_revision > 0
```

Material booking changes advance `operational_revision`. Recurring hours and Location-hours exception children bump the Location root through database triggers.

### 3.3 `capacity_claims`

Added:

```text
resource_location_assignment_id uuid NULL
```

Legacy claims remain `NULL`.

A contextual claim must prove same-tenant assignment/Resource/Location consistency and that the assignment contains the claim interval at creation. Later assignment edits may not invalidate existing claim provenance.

This field is provenance only; `resource_id` remains the capacity root.

---

## 4. Public operational contacts

### 4.1 Organization contacts

Table:

```text
organization_public_contact_endpoints
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
channel text NOT NULL
normalized_value text NOT NULL
label text NULL
active boolean NOT NULL DEFAULT true
is_public boolean NOT NULL DEFAULT true
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Initial channels:

```text
phone
whatsapp
email
```

The executable column name is `is_public`, not `public`.

Semantic mutation is implemented through `SetOrganizationPublicContacts`; this relation is not PartyContactPoint identity.

### 4.2 Location contacts

Table:

```text
location_public_contact_endpoints
```

It mirrors the Organization endpoint shape plus:

```text
location_id uuid NOT NULL
```

Composite FK guarantees:

```text
(organization_id, location_id)
  -> locations(organization_id, id)
```

Semantic mutation is `SetLocationPublicContacts`.

Possession of either endpoint type never grants authority.

---

## 5. Location operational availability

### 5.1 Recurring hours

Table:

```text
location_operational_hours
```

Columns:

```text
id
organization_id
location_id
weekday
local_start
local_end
valid_from?
valid_until?
active
created_at
```

Rules include valid weekday, `local_start < local_end` and tenant-consistent Location FK.

### 5.2 One-off Location-hours exceptions

Table:

```text
location_hours_exceptions
```

Columns:

```text
id
organization_id
location_id
during tstzrange
exception_kind  # available | unavailable
reason?
active
created_at
updated_at
```

Ranges are non-empty, bounded and half-open. Active overlapping exceptions for the same exact Location are rejected by GiST exclusion.

Recurring-hour and exception writes advance `locations.operational_revision`.

Effective physical availability is resolved before Resource availability; Resource additional availability cannot bypass a closed Location.

---

## 6. Resource-at-Location assignment

Table:

```text
resource_location_assignments
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_id uuid NOT NULL
location_id uuid NOT NULL
effective_during tstzrange NOT NULL
status text NOT NULL DEFAULT 'active'
revision bigint NOT NULL DEFAULT 1
created_at
updated_at
```

Status:

```text
active
retired
```

Composite FKs bind Resource and Location to the same Organization.

For one exact Resource + Location, overlapping effective ranges are rejected by GiST exclusion.

Identity cannot be retargeted. Retired assignments cannot be reactivated.

A range edit is rejected if any existing contextual CapacityClaim would fall outside the new range. Assignment lifecycle changes also advance Resource availability observation.

Assignment is eligibility/configuration, never capacity consumption.

---

## 7. Resource-at-Location recurring availability

Table:

```text
resource_location_availability
```

Columns:

```text
id
organization_id
resource_location_assignment_id
weekday
local_start
local_end
valid_from?
valid_until?
active
created_at
```

Timezone derives from:

```text
ResourceLocationAssignment -> Location -> timezone
```

Child writes advance the owning Resource's availability observation.

Released `availability_schedules` remains the recurrence source for never-contextualized Resources.

---

## 8. Resource exception scopes

### Assignment-specific

Table:

```text
resource_location_schedule_exceptions
```

Columns include assignment, bounded half-open `during`, `available|unavailable`, reason and active flag. Active overlap for the same assignment is rejected.

### Resource-wide

Released V3:

```text
schedule_exceptions
```

remains the broad Resource-wide source. F1 does not duplicate it.

Effective contextual Resource state composes both scopes. Broad/narrow overlap is valid because they intentionally represent different intent; an applicable unavailable rule blocks and an available rule still cannot bypass a closed Location.

---

## 9. OfferingVersion base booking terms

Table:

```text
offering_version_booking_terms
```

Columns:

```text
id
organization_id
offering_version_id
amount numeric(20,6)
currency text
created_at
```

One row per OfferingVersion, immutable after insertion. Amount is nonnegative and currency matches `^[A-Z]{3}$`.

Default planned duration remains `offering_versions.duration_minutes`.

A base-term row is optional; a valid context-only price may be completed by exact BookingContextTerms.

---

## 10. Contextual booking terms

Table:

```text
booking_context_terms
```

Columns:

```text
id
organization_id
resource_location_assignment_id
offering_version_id
effective_during tstzrange
amount?
currency?
planned_duration_minutes?
bookable
active
revision
created_at
updated_at
```

Rules:

```text
amount/currency both present or both absent
amount >= 0 when present
currency matches ^[A-Z]{3}$ when present
planned_duration_minutes > 0 when present
at least one material override exists OR bookable=false
effective range lower-bounded, non-empty and half-open
revision > 0
```

Exact active overlap for one assignment + OfferingVersion is rejected by GiST exclusion.

Commercial mutation serializes through the assignment's Resource root so booking and configuration cannot cross nondeterministically.

For multi-resource Offerings, every selected context resolves field-by-field against the same OfferingVersion defaults; all selected Resources must converge on one final amount/currency/duration tuple or the option is conflicting/non-bookable.

---

## 11. Reservation commercial commitment — final model

### 11.1 Material commitment

Table:

```text
reservation_commercial_commitments
```

Current executable columns:

```text
reservation_id uuid PRIMARY KEY
organization_id uuid NOT NULL
offering_version_booking_terms_id uuid NULL
amount numeric(20,6) NOT NULL
currency text NOT NULL
planned_duration_minutes integer NOT NULL
configuration_fingerprint text NOT NULL
committed_at timestamptz NOT NULL
```

There is **no direct `booking_context_terms_id` column** in the final consolidated migration.

The row is immutable and stores the historical material commercial fact directly.

`offering_version_booking_terms_id` is optional base-source provenance; it is correctly `NULL` for context-only pricing.

### 11.2 Multi-source contextual provenance

Table:

```text
reservation_commercial_commitment_context_terms
```

Columns:

```text
organization_id uuid NOT NULL
reservation_id uuid NOT NULL
booking_context_terms_id uuid NOT NULL
created_at timestamptz NOT NULL
PRIMARY KEY (organization_id, reservation_id, booking_context_terms_id)
```

This append-only bridge is the canonical 0..N contextual-source provenance for one Reservation commercial commitment.

The writer inserts every contributing contextual source; no arbitrary primary context is invented.

The obsolete direct contextual-source field and row-level source-presence CHECK are absent from the final migration, allowing a valid context-only price to persist its material commitment and bridge provenance coherently.

---

## 12. Revision and serialization backstops

F1 intentionally does **not** widen the released V3 revision trigger inventory.

The consolidated migration defines:

```text
guard_f1_exact_revision_step()
```

for F1 revisioned aggregates such as ResourceLocationAssignment and BookingContextTerms.

Other database backstops include:

```text
Location operational revision bump from material child writes
Resource availability revision bump from assignment/schedule children
assignment identity/range/claim-provenance guard
context-term scope/resource locking
OfferingVersion base-term root lock
contextual CapacityClaim assignment guard
immutable commercial commitment/provenance triggers
```

These backstop, rather than replace, Python-owned semantic orchestration.

---

## 13. Shared-capacity compatibility

Contextual assignment does not alter capacity identity:

```text
ResourceLocationAssignment -> eligibility/context
Resource                   -> capacity root
CapacityClaim              -> capacity consumption
```

For globally bound Resources, released cross-tenant shared-capacity locking remains additive.

The consolidated migration preserves released capacity protection while adding narrow contextual-assignment provenance validation. Contextual booking is explicitly proven unable to bypass shared-capacity contention.

---

## 14. RLS and runtime ACL

Every new tenant-owned F1 relation enables and forces RLS using Organization tenant context.

Internal trigger/helper functions have PUBLIC execution revoked.

A key final ACL rule is:

> `request_engine_worker` has no direct privileges on authoritative F1 tenant-domain relations.

The migration may contain earlier grant blocks as part of construction ordering, but the final hardening block revokes worker access from:

```text
organization_public_contact_endpoints
location_public_contact_endpoints
location_operational_hours
location_hours_exceptions
resource_location_assignments
resource_location_availability
resource_location_schedule_exceptions
offering_version_booking_terms
booking_context_terms
reservation_commercial_commitments
reservation_commercial_commitment_context_terms
```

Tenant-domain handlers use the app/domain session side of Production Worker Assembly. Worker control-plane authority remains separate.

---

## 15. Semantic write surfaces

The relational model is not a generic CRUD contract.

Implemented semantic responsibilities include:

```text
UpdateOrganizationOperationalProfile
SetOrganizationPublicContacts
CreateLocation
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

Authority/idempotency/audit and stale-intent behavior live in application/adapters while PostgreSQL backstops tenant and structural invariants.

---

## 16. Time semantics

Recurring schedules are wall-clock rules in the owning Location IANA timezone.

Concrete authoritative ranges are timezone-aware half-open intervals.

DST nonexistent/ambiguous local instants are explicitly rejected/resolved; server-local timezone never becomes authority.

This is proven with contextual spring-forward gap and fall-back fold integration tests.

---

## 17. Proven relational invariants

Canonical F1 tests prove at least:

```text
same-tenant composite FKs
RLS/role isolation
ResourceLocationAssignment non-overlap
BookingContextTerms non-overlap
Location-hours exception non-overlap
assignment exception non-overlap
revision-step guards
Location/Resource material revision propagation
worker privilege hardening
internal helper execution hardening
immutable commercial commitment
append-only multi-source provenance
context-only commercial commitment
CapacityClaim assignment provenance protection
shared-capacity compatibility
```

Canonical Phase H implementation proof checkpoint:

```text
c1966f04c0b36fbe8b5bc41f85bb69e8a6831503
workflow run 32516044052
```

All required CI jobs were green on that code checkpoint.

---

## 18. Upgrade semantics and completion rule

Upgrade:

```text
0001_initial -> 0002_f1_supply
```

creates F1 schema without inventing historical contextual facts for released V3 data.

Because this is an unshipped greenfield F1 revision, its internal design was consolidated before production use. Once deployed, this revision becomes immutable production history like `0001_initial`.

This document is reconciled only while it matches `0002_f1_supply` on table/column names, provenance cardinality, revision/serialization ownership, RLS/runtime ACL, shared-capacity compatibility and legacy fallback semantics.

The final merge-readiness gate remains a fresh exact-head canonical CI run after documentation and repository cleanup. This document must not resurrect removed provisional migrations, obsolete direct contextual-source columns or already-closed semantic gaps.