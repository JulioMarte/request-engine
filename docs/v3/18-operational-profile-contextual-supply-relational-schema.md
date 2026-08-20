# Operational Profile & Contextual Supply — Relational Schema Design

Status: accepted Phase C schema design for `feature/operational-profile-contextual-supply` before executable migration authoring.

Normative sources:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
docs/v3/16-operational-profile-contextual-supply-clarifications.md
docs/v3/17-operational-profile-contextual-supply-implementation-inventory.md
docs/adr/0012-contextual-resource-location-supply.md
```

Production baseline:

```text
migrations/versions/0001_initial.py
```

This document defines the minimal additive relational delta for F1. It does not rewrite the released V3 baseline and it does not authorize changes under `migrations/sql/v3_candidate/`, `migrations/sql/v3_initial/` or `migrations/sql/design_chain/`.

---

## 1. Design goals

The schema must make the following behavior possible without weakening released V3 invariants:

```text
one Resource -> multiple Locations
independent Resource schedule by Location
Location-wide recurring hours and exceptions
Resource-wide and Resource-at-Location exceptions
fixed OfferingVersion default price
Resource + Location + OfferingVersion effective price/duration override
future effective contextual terms
stale option detection
immutable Reservation commercial commitment
explicit F1 assignment provenance on CapacityClaim
legacy V3 booking fallback
```

The design remains tenant-scoped. Cross-tenant discovery remains F2.

---

## 2. Compatibility principle

Existing V3 structures remain valid:

```text
resources.location_id
availability_schedules
schedule_exceptions
reservations
capacity_claims
```

They are not bulk converted into inferred contextual rows.

Normative resolver rule:

```text
accepted contextual ResourceLocationAssignment exists for the selected context
  -> F1 contextual resolver is authoritative
else
  -> released V3 Resource/location/schedule behavior remains authoritative
```

A Resource must never combine legacy wildcard semantics and F1 assignment semantics inside one resolution attempt. Once the F1 path is selected for a Resource/context, only explicit effective assignments prove Location eligibility.

---

## 3. Existing tables extended in place

### 3.1 `organizations`

Add narrow typed operational defaults while retaining `public_profile` for compatibility:

```text
legal_name text NULL
public_display_name text NULL
default_timezone text NULL
default_locale text NULL
default_currency text NULL
operational_status text NOT NULL DEFAULT 'active'
```

Rules:

```text
operational_status IN ('active', 'inactive')
default_currency uses uppercase ISO-style 3-letter code when present
default timezone/locale are semantic-command validated; timezone is also validated by application ZoneInfo before persistence
```

`display_name` remains released-V3 identity. `public_display_name` is an explicit F1 public operational override and must not silently rewrite `display_name`.

### 3.2 `locations`

Retain released fields and add typed operational structure:

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

Structural constraints:

```text
(latitude IS NULL) = (longitude IS NULL)
latitude BETWEEN -90 AND 90
longitude BETWEEN -180 AND 180
country_code is uppercase two-letter code when present
operational_revision > 0
```

`active` and `timezone` remain authoritative released fields.

Location operational revision advances exactly one step for material booking availability mutations, including:

```text
active/timezone changes
Location recurring-hour writes
Location-hours exception writes
```

Address/contact/coordinate changes do not need to stale an appointment option unless they alter a material booking field; they still remain auditable semantic mutations.

### 3.3 `capacity_claims`

Add nullable F1 provenance:

```text
resource_location_assignment_id uuid NULL
```

Legacy claims remain NULL.

For F1 contextual booking/hold claims the value is required by the supported F1 command path and must point to an assignment that:

```text
belongs to the same Organization
belongs to capacity_claims.resource_id
belongs to the Hold/Reservation Location
covers the claim interval under accepted effective semantics
```

The column is provenance/configuration context only. `resource_id` remains the capacity serialization root and the existing CapacityClaim row remains the capacity-consumption truth.

---

## 4. Organization public operational contacts

Create:

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
public boolean NOT NULL DEFAULT true
created_at timestamptz
updated_at timestamptz
```

Initial channels:

```text
phone
whatsapp
email
```

Constraints:

```text
UNIQUE (organization_id, id)
UNIQUE (organization_id, channel, normalized_value)
normalized_value <> ''
```

This relation is independent from `party_contact_points`. Reusing value-normalization helpers is allowed; reusing Party contact ownership/lifecycle is not.

---

## 5. Location public operational contacts

Create:

```text
location_public_contact_endpoints
```

Columns mirror Organization endpoints plus:

```text
location_id uuid NOT NULL
```

Tenant proof uses a composite FK:

```text
(organization_id, location_id)
  -> locations(organization_id, id)
```

Unique operational identity:

```text
UNIQUE (organization_id, location_id, channel, normalized_value)
```

Possession of an endpoint never grants authority.

---

## 6. Location recurring operational hours

Create:

```text
location_operational_hours
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
location_id uuid NOT NULL
weekday smallint NOT NULL
local_start time NOT NULL
local_end time NOT NULL
valid_from date NULL
valid_until date NULL
active boolean NOT NULL DEFAULT true
created_at timestamptz
```

The Location IANA timezone is authoritative; timezone is deliberately not duplicated on each row.

Constraints follow the proven V3 recurring-availability shape:

```text
weekday BETWEEN 0 AND 6
local_start < local_end
valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from
```

Writes must serialize against the Location configuration root and bump `locations.operational_revision`.

Overlapping recurring rows are not automatically invalid: multiple windows on the same weekday are a legitimate representation, e.g. `08:00-12:00` and `13:00-17:00`. Application commands normalize/reject ambiguous duplicate intent where required.

---

## 7. Location-hours exceptions

Create:

```text
location_hours_exceptions
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
location_id uuid NOT NULL
during tstzrange NOT NULL
exception_kind text NOT NULL
reason text NULL
created_at timestamptz
```

Allowed kinds:

```text
available
unavailable
```

Range rules:

```text
non-empty
bounded lower/upper
[lower, upper)
```

Ambiguous overlapping Location exceptions for one exact Location are forbidden by an exclusion constraint using the existing `btree_gist` extension:

```text
EXCLUDE USING gist (
  organization_id WITH =,
  location_id WITH =,
  during WITH &&
)
```

This deliberately forces a semantic command to express the final one-off Location state instead of stacking contradictory available/unavailable exceptions over the same instant.

Every write bumps `locations.operational_revision`.

---

## 8. Resource-at-Location assignment

Create canonical persisted entity:

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
created_at timestamptz
updated_at timestamptz
```

Status:

```text
active
retired
```

`effective_during` is bounded below and may be open-ended above. It uses `[)` semantics.

Tenant proof:

```text
(organization_id, resource_id) -> resources(organization_id, id)
(organization_id, location_id) -> locations(organization_id, id)
```

Ambiguous historical/effective assignment overlap for the same Resource + Location is forbidden regardless of current lifecycle status:

```text
EXCLUDE USING gist (
  organization_id WITH =,
  resource_id WITH =,
  location_id WITH =,
  effective_during WITH &&
)
```

Retirement must preserve the historical interval that actually applied. A supported retirement command normally closes an open-ended interval and marks the row retired; it never retargets the row to another Resource or Location.

Assignment `revision` uses the existing exact-one-step revision semantics.

Configuration writes for an assignment lock the underlying Resource in canonical Resource-id order and participate in Resource availability/configuration serialization.

---

## 9. Resource-at-Location recurring availability

Create:

```text
resource_location_availability
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_location_assignment_id uuid NOT NULL
weekday smallint NOT NULL
local_start time NOT NULL
local_end time NOT NULL
valid_from date NULL
valid_until date NULL
active boolean NOT NULL DEFAULT true
created_at timestamptz
```

Timezone is derived through assignment -> Location and is not duplicated.

Every write:

```text
proves same Organization through composite FK
locks the assignment Resource root
bumps resources.availability_revision exactly one step for the semantic mutation
```

The existing `availability_schedules` table remains the legacy Resource-wide recurrence path only.

---

## 10. Resource-at-Location exceptions

Create:

```text
resource_location_schedule_exceptions
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_location_assignment_id uuid NOT NULL
during tstzrange NOT NULL
exception_kind text NOT NULL
reason text NULL
created_at timestamptz
```

Semantics mirror current `schedule_exceptions` but the scope is explicit assignment context.

The existing `schedule_exceptions` table remains the F1 Resource-wide exception source as well as the legacy V3 exception source. F1 does not duplicate Resource-wide exceptions into a new table.

For an F1 contextual Resource, effective exception composition is:

```text
existing resource-wide schedule_exceptions
+
resource_location_schedule_exceptions for selected assignment
```

An assignment-specific command never writes `schedule_exceptions`.

Every assignment-exception write bumps `resources.availability_revision`.

Overlapping broad and narrow exceptions are allowed because they represent distinct explicit scopes. Resolver precedence is safety-oriented:

```text
any applicable UNAVAILABLE at either scope blocks the interval
AVAILABLE may add Resource availability only if effective Location availability also permits the interval
```

Within one assignment-specific exception table, exact overlapping rows are rejected by exclusion to avoid contradictory state for one scope.

---

## 11. OfferingVersion base fixed commercial terms

Do not mutate the meaning of existing immutable `offering_versions` rows by putting price inside `booking_policy` or `public_data`.

Create:

```text
offering_version_booking_terms
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
offering_version_id uuid NOT NULL
amount numeric(20,6) NOT NULL
currency text NOT NULL
created_at timestamptz
```

Constraints:

```text
UNIQUE (organization_id, id)
UNIQUE (organization_id, offering_version_id)
amount >= 0
currency ~ '^[A-Z]{3}$'
```

The row is immutable after insertion, matching `OfferingVersion` immutability.

Default planned duration remains `offering_versions.duration_minutes`; it is not duplicated here.

A future change to the base/default service commercial contract normally creates a new OfferingVersion and a new immutable base-terms row. F1 future effective mutation without a new OfferingVersion is supported only through the exact contextual terms relation below, as required by the demonstrated Resource + Location use case.

Existing OfferingVersions without a base terms row remain valid V3 rows. They are not quoteable under an F1 capability that requires a price unless an effective exact contextual override supplies the required price.

---

## 12. Contextual booking terms

Create:

```text
booking_context_terms
```

Columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_location_assignment_id uuid NOT NULL
offering_version_id uuid NOT NULL
effective_during tstzrange NOT NULL
amount numeric(20,6) NULL
currency text NULL
planned_duration_minutes integer NULL
bookable boolean NOT NULL DEFAULT true
revision bigint NOT NULL DEFAULT 1
created_at timestamptz
updated_at timestamptz
```

Rules:

```text
amount and currency are both present or both absent
amount >= 0
currency is uppercase 3-letter code
planned_duration_minutes > 0 when present
at least one material override exists OR bookable=false
effective range is [) and bounded below
```

Exact-scope ambiguity is forbidden:

```text
EXCLUDE USING gist (
  organization_id WITH =,
  resource_location_assignment_id WITH =,
  offering_version_id WITH =,
  effective_during WITH &&
)
```

Resolution at a concrete instant:

```text
exact effective booking_context_terms
  amount/currency if present
  planned_duration if present
  bookable state
>
offering_version_booking_terms amount/currency
offering_versions.duration_minutes
>
missing required value => not quoteable/bookable
```

Context terms mutation participates in assignment/Resource configuration serialization and advances its own exact-one-step revision.

### Multi-resource Offering rule

Released V3 supports more than one resource requirement. F1 must not invent a hidden pricing precedence among several selected Resources.

For one appointment selection:

1. resolve an assignment for every selected Resource;
2. resolve any exact contextual terms for every selected assignment;
3. collect the material commercial tuples contributed by matching contextual rows;
4. if no contextual row contributes a value, use OfferingVersion defaults;
5. if one or more contextual rows contribute values, all contributed values for the same material field must agree after fallback;
6. conflicting amount/currency or planned duration across selected assignments is `booking_configuration_conflict` and the option is not emitted/booked.

This keeps the contract deterministic without adding requirement-specific or arbitrary pricing precedence that F1 never accepted.

---

## 13. Historical Reservation commercial commitment

Create one append-only relation:

```text
reservation_commercial_commitments
```

Columns:

```text
reservation_id uuid PK
organization_id uuid NOT NULL
offering_version_booking_terms_id uuid NULL
booking_context_terms_id uuid NULL
amount numeric(20,6) NOT NULL
currency text NOT NULL
planned_duration_minutes integer NOT NULL
configuration_fingerprint text NOT NULL
committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
```

Tenant-consistent FKs point to Reservation and optional source term rows.

The row is append-only/immutable after insertion.

It stores the resolved commercial fact, not merely references:

```text
amount
currency
planned duration
```

Therefore later assignment, schedule, Location or term changes cannot alter historical meaning.

`configuration_fingerprint` records the opaque material observation accepted by the booking transaction for audit/explanation. It is not an authorization credential.

Legacy Reservations receive no fabricated commitment row.

For F1 booking success, Reservation + commitment + contextual CapacityClaims must be created in the same transaction.

---

## 14. Stale option observation

No persistent `appointment_options` table is required.

Retain the existing signed stateless option architecture and introduce a new token format/version that can bind at least:

```text
organization_id
offering_version_id
Location
start/end
selected Resource requirement/resource pairs
selected resource_location_assignment IDs + revisions
selected Resource availability_revision values
Location operational_revision
resolved booking_context_terms IDs + revisions where applicable
base terms identity when applicable
resolved amount/currency/planned duration
material configuration fingerprint
issued_at/expires_at
```

The token is advisory. `book` re-resolves current state under authoritative locks and compares material observations.

A changed non-material public field does not stale an option.

A change in any of the following does:

```text
assignment applicability
Location operational availability
Resource recurring/broad/narrow exception availability
OfferingVersion bookable state
resolved duration
resolved amount/currency
context bookable state
```

Material mismatch returns an opaque stale/conflict result; it never silently substitutes price.

---

## 15. Serialization and lock topology

### Configuration writes

Canonical lock order:

```text
Organization/tenant authority validation
Location row when changing Location availability
Resource rows in UUID order when changing Resource/assignment context
assignment/context rows after their Resource root is locked
```

No command obtains a contextual row lock and then reaches backwards for an unlocked Resource root.

### Booking

Preserve existing V3 capacity protocol:

```text
load immutable OfferingVersion/requirements
validate subject/Location/authority
lock selected Resource rows in canonical UUID order
apply existing shared-capacity locking for globally bound Resources
resolve/revalidate F1 assignment + Location + schedule + exceptions + contextual terms
verify option material observation
create Reservation
create reservation_commercial_commitment
create CapacityClaims with assignment provenance
append audit/outbox
commit
```

Context configuration does not become a capacity mutex.

---

## 16. Revision topology

Use the minimum revisions necessary for stale detection and optimistic intent:

```text
resources.availability_revision        existing; KEEP
locations.operational_revision         ADD
resource_location_assignments.revision ADD
booking_context_terms.revision         ADD
```

Do not add revisions to every child schedule/exception row.

Child writes bump their owning aggregate/root revision:

```text
Location hours/exception -> Location operational_revision
assignment availability/exception -> Resource availability_revision
assignment lifecycle -> assignment revision + Resource availability_revision when bookability changes
booking context term mutation -> context revision + Resource availability_revision when effective bookability/commercial state changes
```

The application may hash the exact observed IDs/revisions/resolved values into the opaque configuration fingerprint.

---

## 17. RLS and runtime privileges

Every new tenant-owned table has `organization_id` and follows the released V3 defense-in-depth pattern:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
USING (organization_id = request_engine.current_organization_id())
WITH CHECK (organization_id = request_engine.current_organization_id())
```

The schema owner remains the DDL owner. Runtime app/worker roles remain NOBYPASSRLS.

After object creation, privileges must be explicit for the new relations because `GRANT ... ON ALL TABLES` from the old baseline does not automatically grant later-created tables unless default privileges exist and are proven. Phase C migration must grant only what existing runtime contracts require.

No F1 table is exposed through `request_admin` as a normal configuration path.

---

## 18. Read surfaces

Do not break released views.

Add new versioned read surfaces rather than changing V1 result shape incompatibly where existing consumers may rely on it.

Candidate additions:

```text
request_read.business_info_v2
request_read.locations_v2
```

Application readers may use underlying tenant tables inside semantic queries when a dedicated versioned read view is not yet externally promised, but public capability output must remain versioned/typed.

`business_info_v2` may expose:

```text
Organization public operational identity/defaults/central contacts
Location structured address/timezone/public contacts
Location effective informational hours
```

Private/admin revision fields are not public output.

---

## 19. Index plan

Required indexes beyond PK/unique/FK support:

```text
resource_location_assignments
  (organization_id, resource_id)
  (organization_id, location_id)
  GiST exclusion index from effective range

resource_location_availability
  (organization_id, resource_location_assignment_id, weekday)

resource_location_schedule_exceptions
  GiST scope/range exclusion + overlap lookup

location_operational_hours
  (organization_id, location_id, weekday)

location_hours_exceptions
  GiST scope/range exclusion + overlap lookup

booking_context_terms
  (organization_id, offering_version_id)
  GiST exact-scope effective exclusion
```

Do not add PostGIS in F1. Latitude/longitude B-tree indexing is unnecessary until F2 supplies an actual proximity query plan.

---

## 20. Migration order

One append-only Alembic revision may contain the initial F1 relational foundation if reviewability remains acceptable. Split only if transactional dependency or proof clarity requires it.

Order inside the migration:

```text
1. ALTER organizations/locations/capacity_claims additive columns
2. create Organization/Location public contact tables
3. create Location hours + Location exception tables
4. create ResourceLocationAssignment
5. create contextual Resource availability + exceptions
6. create OfferingVersion base terms
7. create booking contextual terms
8. create Reservation commercial commitment
9. constraints/exclusion indexes
10. exact revision / root-bump / immutability triggers
11. CapacityClaim contextual provenance guard extension
12. RLS + FORCE RLS policies
13. explicit runtime grants
14. new read views where included in this migration
```

No data rewrite is needed to make legacy V3 rows valid.

---

## 21. Upgrade behavior

Upgrade from `0001_initial` must satisfy:

```text
existing Organizations remain valid
existing Locations remain valid with NULL structured/geospatial fields
existing Resources keep location_id and legacy schedules
existing Reservations keep no invented price provenance
existing CapacityClaims keep assignment_id NULL
existing OfferingVersions keep no invented default price
all old V3 tests remain semantically valid
```

Fresh F1 configuration can be added incrementally after upgrade.

No automatic conversion from `resources.location_id` to `resource_location_assignments` occurs in the migration. Such conversion would invent effective-from history and could incorrectly change fallback behavior.

---

## 22. Downgrade policy

The first F1 revision is additive but may contain new committed F1 state after deployment. A downgrade that merely drops those tables/columns would destroy accepted operational/commercial provenance.

Therefore the production migration should explicitly reject downgrade unless a future separately reviewed rollback migration/export strategy exists.

Do not advertise destructive automatic reversibility.

---

## 23. PostgreSQL proof matrix for Phase C

Before schema work is considered proven, real PostgreSQL tests must cover at least:

### Structural/tenant

```text
cross-tenant assignment FK rejected
cross-tenant Location contact rejected
cross-tenant assignment availability rejected
cross-tenant context terms rejected
invalid coordinates rejected
invalid currency/amount rejected
overlapping Resource+Location assignment rejected
overlapping exact booking context rejected
overlapping Location exception rejected
```

### Revision/serialization

```text
Location hour mutation bumps one Location operational revision
Location exception mutation bumps one revision
assignment availability mutation bumps one Resource availability revision
assignment exception mutation bumps one Resource availability revision
assignment retirement advances exact revision and stales old observation
context mutation advances exact revision and stales old observation
```

### Historical provenance

```text
F1 claim with wrong assignment/resource rejected
F1 claim with wrong assignment/Location rejected
legacy claim with NULL assignment remains valid
Reservation commercial commitment cannot update/delete
later term changes do not alter commitment
```

### RLS/privileges

```text
app cannot read/write foreign tenant F1 rows
worker cannot read/write foreign tenant F1 rows through normal table access
admin behavior remains explicitly privileged
new tables are not accidentally PUBLIC-readable
```

### Migration

```text
alembic 0001 -> head succeeds
fresh alembic head succeeds
repeat fresh bootstrap succeeds
0001_initial SHA/content unchanged
frozen candidate/design history unchanged
```

---

## 24. Application work enabled by this schema

After the migration is proven, Phase D/E/F/G can implement:

```text
semantic Organization/Location configuration commands
ResourceLocationAssignment commands
Location and Resource exception commands
context terms commands
contextual availability resolver
commercial resolver
business.get_info v2 mapping
find_slots contextual options
signed option v2 material observation
book authoritative contextual revalidation
Reservation commercial commitment persistence
```

The schema intentionally does not create unused F2/F3/F4 concepts.

---

## 25. Phase C gate decision

The relational design is compatible with the released V3 architecture and closes the implementation-inventory gaps without changing the capacity root.

The first executable migration is authorized to proceed with these rules:

```text
ADD contextual configuration
KEEP V3 legacy path
KEEP Resource as capacity root
KEEP CapacityClaim as capacity ledger
ADD assignment provenance to new contextual claims
ADD immutable Reservation commercial commitment
ADD revision-backed stale observation inputs
NO migration-time contextual backfill
NO candidate/history edits
NO PostGIS
```

Any executable migration that materially deviates from this schema requires updating this document/contract before implementation.