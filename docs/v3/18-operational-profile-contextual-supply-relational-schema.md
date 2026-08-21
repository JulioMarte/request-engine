# Operational Profile & Contextual Supply — Relational Schema, As-Built Reconciliation

Status: as-built Phase C relational design/reconciliation for `feature/operational-profile-contextual-supply`.

Current executable migration:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

Normative semantic sources remain:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
docs/v3/16-operational-profile-contextual-supply-clarifications.md
docs/v3/17-operational-profile-contextual-supply-implementation-inventory.md
docs/adr/0012-contextual-resource-location-supply.md
```

Current status/proof sources:

```text
docs/v3/20-operational-profile-contextual-supply-implementation-handoff.md
docs/v3/21-operational-profile-contextual-supply-documentation-audit.md
```

This document was originally written before executable migration authoring. It is now reconciled to the consolidated as-built F1 migration.

If this document and the executable migration disagree on a physical column, constraint, trigger, role grant or SQL implementation detail, the migration is the current executable truth and the discrepancy must be fixed here before merge readiness. The migration does **not** override the normative F1 product/transaction semantics in `15/16` merely by existing.

---

## 1. Greenfield consolidation decision

F1 initially evolved through provisional local revisions `0002 -> 0003 -> 0004 -> 0005` while the schema, shared-capacity guard and runtime ACL were being hardened.

Request Engine has not stored production/customer-owned F1 data and those provisional revisions were never deployed. Under the premise documented in:

```text
docs/v3/19-greenfield-validation-data-premise.md
```

they were consolidated into one intended launch revision:

```text
0002_f1_supply
```

The consolidated revision contains four concerns that must all remain reviewable/proven:

```text
1. base operational/contextual relational schema
2. commercial-source serialization and multi-source provenance
3. compatibility with released shared-capacity protection
4. final F1 runtime ACL/RLS hardening
```

This consolidation does not authorize editing the released baseline.

Non-negotiable frozen provenance:

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

F1 does not bulk invent contextual history for them.

Resolver rule:

```text
Resource has entered accepted contextual assignment semantics
  -> explicit ResourceLocationAssignment is required for contextual Location eligibility

Resource has never entered contextual assignment semantics
  -> released V3 Resource/location/schedule behavior remains available
```

Once a Resource has contextual assignment history, retirement does not silently restore legacy wildcard Location semantics.

Legacy Reservations and CapacityClaims are not retroactively assigned prices or ResourceLocationAssignment provenance they never recorded.

---

## 3. Existing tables extended in place

### 3.1 `organizations`

As built:

```text
legal_name text NULL
default_timezone text NULL
default_locale text NULL
default_currency text NULL
operational_status text NOT NULL DEFAULT 'active'
```

Structural rules:

```text
legal/default string fields are nonblank when present
default_currency matches ^[A-Z]{3}$ when present
operational_status IN ('active', 'inactive')
```

`organizations.display_name` remains the canonical public/display identity. F1 does not introduce a competing display-name column.

### 3.2 `locations`

As built:

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

Structural rules:

```text
(latitude IS NULL) = (longitude IS NULL)
latitude BETWEEN -90 AND 90
longitude BETWEEN -180 AND 180
country_code matches ^[A-Z]{2}$ when present
operational_revision > 0
```

Released `active` and `timezone` remain authoritative.

`operational_revision` is a material booking observation token. Material changes include:

```text
Location active/timezone state
Location recurring operational-hour writes
Location-hours exception writes
```

Address/contact/geocoding edits do not need to stale an AppointmentOption unless they change booking material state.

### 3.3 `capacity_claims`

As built:

```text
resource_location_assignment_id uuid NULL
```

Legacy claims remain `NULL`.

A contextual claim carrying the field must prove:

```text
same Organization
assignment belongs to claim Resource
assignment Location equals Hold/Reservation Location
assignment is active at claim creation
assignment effective range contains claim interval
assignment provenance cannot later be retargeted
```

This field is contextual provenance only. `resource_id` remains the capacity root and `CapacityClaim` remains the capacity-consumption ledger.

---

## 4. Organization public operational contacts

Table:

```text
organization_public_contact_endpoints
```

As-built columns:

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

The executable name is **`is_public`**, not the earlier pre-authoring spelling `public`.

Supported initial channels:

```text
phone
whatsapp
email
```

Key constraints:

```text
UNIQUE (organization_id, id)
UNIQUE (organization_id, channel, normalized_value)
normalized_value <> ''
label nonblank when present
```

This relation is independent from `party_contact_points` ownership/lifecycle.

Current implementation gap outside the schema: there is read support, but no dedicated semantic Organization-public-contact mutation command yet. See `20/21`.

---

## 5. Location public operational contacts

Table:

```text
location_public_contact_endpoints
```

Columns mirror Organization endpoints plus:

```text
location_id uuid NOT NULL
```

Tenant consistency:

```text
(organization_id, location_id)
  -> locations(organization_id, id)
```

Operational identity:

```text
UNIQUE (organization_id, location_id, channel, normalized_value)
```

The as-built semantic command is:

```text
SetLocationPublicContacts
```

Possession of an endpoint never grants authority.

---

## 6. Location recurring operational hours

Table:

```text
location_operational_hours
```

As-built columns:

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
created_at timestamptz NOT NULL
```

Timezone comes from the owning Location.

Constraints:

```text
weekday BETWEEN 0 AND 6
local_start < local_end
valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from
```

Child mutations advance `locations.operational_revision` through the Location root.

Multiple non-identical windows on the same weekday are legitimate, e.g. morning/afternoon blocks. Semantic commands own normalized intent.

---

## 7. Location-hours exceptions

Table:

```text
location_hours_exceptions
```

As-built columns:

```text
id uuid PK
organization_id uuid NOT NULL
location_id uuid NOT NULL
during tstzrange NOT NULL
exception_kind text NOT NULL
reason text NULL
active boolean NOT NULL DEFAULT true
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Allowed kinds:

```text
available
unavailable
```

Ranges are non-empty, bounded and half-open `[)`.

Active same-Location overlap is rejected using `btree_gist` exclusion.

Cancellation/retirement is represented by `active=false`; supported runtime flows do not require destructive DELETE.

Every effective mutation advances the Location material observation.

Location effective schedule is resolved before Resource availability; Resource additional availability cannot bypass a closed Location.

---

## 8. Resource-at-Location assignment

Canonical persisted entity:

```text
resource_location_assignments
```

As-built columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_id uuid NOT NULL
location_id uuid NOT NULL
effective_during tstzrange NOT NULL
status text NOT NULL DEFAULT 'active'
revision bigint NOT NULL DEFAULT 1
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Status:

```text
active
retired
```

Tenant proof:

```text
(organization_id, resource_id) -> resources(organization_id, id)
(organization_id, location_id) -> locations(organization_id, id)
```

Same Resource + Location effective intervals cannot overlap, including historical/retired rows, so one exact context is not ambiguous.

A Resource may have overlapping assignments to **different** Locations; that is intentional eligibility/configuration and does not itself consume capacity.

Identity cannot be retargeted between Resource/Location/Organization.

A retired assignment cannot be reactivated.

Most importantly, an assignment effective-range edit is rejected with SQLSTATE `55000` if it would cause any existing contextual `CapacityClaim` to fall outside the assignment range. This protects durable claim provenance.

Assignment lifecycle changes also advance the underlying Resource availability observation.

---

## 9. Resource-at-Location recurring availability

Table:

```text
resource_location_availability
```

As-built columns:

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
created_at timestamptz NOT NULL
```

Timezone is derived:

```text
assignment -> Location -> timezone
```

Child writes advance the owning Resource's `availability_revision` through a database backstop.

Released `availability_schedules` remains the legacy recurrence source for never-contextualized Resources.

---

## 10. Resource exception scopes

### 10.1 Assignment-specific

Table:

```text
resource_location_schedule_exceptions
```

As-built columns:

```text
id uuid PK
organization_id uuid NOT NULL
resource_location_assignment_id uuid NOT NULL
during tstzrange NOT NULL
exception_kind text NOT NULL
reason text NULL
active boolean NOT NULL DEFAULT true
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Same assignment active overlaps are rejected by exclusion.

### 10.2 Resource-wide

Released V3:

```text
schedule_exceptions
```

remains the Resource-wide source.

F1 does not duplicate broad exceptions into a second table.

Effective contextual Resource state composes:

```text
Resource-wide schedule_exceptions
+
assignment-specific resource_location_schedule_exceptions
```

Safety rule:

```text
any applicable unavailable rule blocks
available may add Resource availability only while effective Location availability permits it
```

Broad and narrow rows may overlap because they are intentionally different scopes.

---

## 11. OfferingVersion base booking terms

Table:

```text
offering_version_booking_terms
```

As-built columns:

```text
id uuid PK
organization_id uuid NOT NULL
offering_version_id uuid NOT NULL
amount numeric(20,6) NOT NULL
currency text NOT NULL
created_at timestamptz NOT NULL
```

Rules:

```text
one row per OfferingVersion
amount >= 0
currency matches ^[A-Z]{3}$
row immutable after insertion
```

Default planned duration remains `offering_versions.duration_minutes`.

An OfferingVersion without a base-term row remains a valid legacy row. F1 may still resolve complete price from an exact contextual term.

Base-term configuration serializes against the OfferingVersion root before insertion/deletion.

---

## 12. Contextual booking terms

Table:

```text
booking_context_terms
```

As-built columns:

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
active boolean NOT NULL DEFAULT true
revision bigint NOT NULL DEFAULT 1
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Structural rules:

```text
amount/currency both present or both absent
amount >= 0 when present
currency matches ^[A-Z]{3}$ when present
planned_duration_minutes > 0 when present
at least one material override exists OR bookable=false
effective range is non-empty, lower-bounded, half-open [)
revision > 0
```

Exact active ambiguity is prevented by GiST exclusion over:

```text
organization_id
resource_location_assignment_id
offering_version_id
effective_during
```

Context mutation serializes against the assignment's Resource root so commercial mutation and authoritative booking cannot cross out of order.

Context-term changes use the exact term revision/source observation rather than broad-staling every Offering on the Resource.

### Multi-resource resolution

Released V3 permits multiple Resource requirements.

F1 has no hidden pricing precedence among selected Resources.

For every selected assignment:

1. resolve its exact contextual term if any;
2. fall back field-by-field to OfferingVersion defaults;
3. require complete amount/currency/duration;
4. require every selected Resource context to resolve to the same final commercial tuple;
5. otherwise treat the configuration as conflicting/non-bookable.

Every contributing contextual row must be preserved as provenance; do not choose an arbitrary primary context.

---

## 13. Reservation commercial commitment — current as-built model

### 13.1 Material commitment table

Table:

```text
reservation_commercial_commitments
```

Current physical columns:

```text
reservation_id uuid PK
organization_id uuid NOT NULL
offering_version_booking_terms_id uuid NULL
booking_context_terms_id uuid NULL          # residual single-source column
amount numeric(20,6) NOT NULL
currency text NOT NULL
planned_duration_minutes integer NOT NULL
configuration_fingerprint text NOT NULL
committed_at timestamptz NOT NULL
```

The row is append-only/immutable.

Material fact:

```text
amount
currency
planned_duration_minutes
configuration_fingerprint
committed_at
```

is persisted directly so historical explanation never depends exclusively on mutable current configuration.

### 13.2 Multi-source contextual provenance

Table added by the consolidated migration:

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

It is append-only and tenant-isolated.

This is the canonical as-built representation for **0..N contextual source rows** that contributed to one committed Reservation commercial fact.

The current contextual booking writer inserts every contributing contextual source into this table.

### 13.3 Known P0 inconsistency

The residual direct `reservation_commercial_commitments.booking_context_terms_id` is no longer populated by the current writer, but the current migration still has a row CHECK equivalent to:

```text
offering_version_booking_terms_id IS NOT NULL
OR booking_context_terms_id IS NOT NULL
```

This is incompatible with a valid context-only price when:

```text
no offering_version_booking_terms row exists
exact BookingContextTerms supplies amount/currency
OfferingVersion supplies duration
```

The resolver supports that F1 contract, but the commitment row can fail before its bridge provenance rows are inserted.

This is a **known correctness blocker**, not a documentation-only discrepancy.

Before merge, preferred greenfield reconciliation is:

```text
remove obsolete direct booking_context_terms_id unless a concrete use remains
remove/rework the row-level source CHECK
keep offering_version_booking_terms_id optional
keep reservation_commercial_commitment_context_terms as canonical contextual provenance
prove context-only booking
prove all multi-resource contextual sources persist
```

Do not force base terms to exist solely to satisfy the old CHECK; exact-context resolution is an accepted F1 rule.

---

## 14. AppointmentOption stale observation

No persistent AppointmentOption relation is required.

F1 retains signed stateless option architecture and adds:

```text
aptopt_v2
```

Material binding includes:

```text
organization_id
offering_version_id
Location
start/end
selected requirement/resource pairs
assignment IDs/revisions where contextual
Resource availability revisions
Location operational_revision
resolved amount/currency/duration
material configuration fingerprint
issued_at/expires_at
```

The booking transaction re-resolves current authoritative state under locks and compares material observation.

Changes that must stale or invalidate include:

```text
assignment applicability
Location operational availability
Resource recurrence/exceptions
Offering current bookable state
resolved duration
resolved amount/currency
context active/bookable state
```

Non-material public-profile edits do not need to stale an option.

---

## 15. Revision topology

As built:

```text
resources.availability_revision              released; KEEP
locations.operational_revision               F1
resource_location_assignments.revision       F1
booking_context_terms.revision               F1
```

Location child availability writes advance Location observation.

Assignment availability/exception/lifecycle changes advance Resource availability observation as applicable.

F1 exact-revision aggregates use a dedicated helper:

```text
request_engine.guard_f1_exact_revision_step()
```

This is intentional: F1 does not widen the trigger inventory/behavior of the released frozen-V3 `guard_exact_revision_step()` surface merely for convenience.

Revision values are opaque observations; arithmetic distance has no product meaning.

---

## 16. Lock and serialization topology

### Configuration writes

Required order/direction:

```text
authority/tenant validation
Location root for Location availability changes
Resource root for Resource/assignment availability changes
assignment/context rows after Resource root
OfferingVersion root for immutable base commercial terms
```

Commercial context writes lock the assignment's Resource root before changing terms.

No external geocoding/provider I/O occurs while authoritative locks are held.

### Contextual booking

Current transaction protocol:

```text
idempotency
lock/current OfferingVersion
subject/Location/origin validation
subject authority
lock expected Location
load requirements
lock selected Resources in canonical order
validate capabilities
lock selected assignments
validate Resource availability observations
load current contextualization
compose Location + Resource schedules/exceptions
load live capacity
re-resolve commercial terms
recompute/compare configuration fingerprint
apply shared-capacity serialization when bound
insert Reservation
insert CapacityClaims with assignment provenance
insert immutable commercial commitment
insert every contextual-source bridge row
audit/outbox/idempotency completion
commit
```

Context configuration never becomes a capacity mutex.

---

## 17. CapacityClaim guard split and shared-capacity compatibility

Released V3 already has privileged shared-capacity visibility requirements that ordinary tenant RLS cannot satisfy.

The consolidated F1 migration preserves the narrow SECURITY DEFINER capacity responsibility while separating tenant-local contextual assignment validation.

Final shape conceptually:

```text
capacity_claims_00_guard_tenant_context
  -> tenant context first

capacity_claims_10_guard_contextual_assignment
  -> invoker-rights assignment/resource/location/effective-range validation

capacity_claims_guard_capacity
  -> narrow SECURITY DEFINER capacity + cross-tenant shared-capacity check
```

Why this split matters:

- cross-tenant shared-capacity detection can see the private global provenance it already requires;
- contextual assignment lookup remains constrained by tenant context/FORCE RLS;
- a guessed foreign assignment UUID does not become an existence oracle through the privileged capacity function;
- contextual assignment does not bypass shared-capacity mutex behavior.

Contextual assignment provenance is immutable on an existing claim.

---

## 18. RLS and final runtime ACL

Every new tenant-owned F1 relation has `organization_id` and final defense-in-depth behavior:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
USING organization_id = request_engine.current_organization_id()
WITH CHECK organization_id = request_engine.current_organization_id()
```

F1 trigger/helper functions also have PUBLIC execute removed. The migration establishes default privileges so future F1 helper functions fail closed unless explicitly granted.

### Final role disposition

The base migration block initially grants new relations to app/worker while objects are assembled, but the final `_RUNTIME_ACL_SQL` hardening block revokes authoritative F1 relation access from:

```text
request_engine_worker
```

Final intended authority:

```text
request_engine_app
  tenant-domain authoritative handlers according to explicit table grants/RLS

request_engine_worker
  no direct authoritative F1 relation privileges

request_engine_admin
  explicit privileged administration, not the normal business configuration path

PUBLIC
  no F1 relation access / no trigger-helper execution
```

This preserves Production Worker Assembly's worker-control vs tenant-domain separation.

Any documentation/test that assumes the final worker can directly mutate F1 tables is stale.

---

## 19. Index/exclusion plan as built

Important lookup/exclusion support includes:

```text
resource_location_assignments
  Resource/status lookup
  Location/status lookup
  GiST exact Resource+Location effective-range exclusion

resource_location_availability
  assignment + weekday + active lookup

resource_location_schedule_exceptions
  GiST active assignment/range exclusion

location_operational_hours
  Location + weekday + active lookup

location_hours_exceptions
  GiST active Location/range exclusion

booking_context_terms
  OfferingVersion + active lookup
  GiST active exact-scope effective-range exclusion

capacity_claims
  partial assignment-provenance lookup index
```

F1 deliberately does **not** add PostGIS. Distance/radius search belongs to F2 and should drive its own query/index design.

---

## 20. Migration execution mechanics

`0002_f1_supply` is online-mode only.

The migration uses the live psycopg driver connection/`ClientCursor` for the large base SQL block and Alembic `op.execute` for later hardening blocks.

It explicitly switches to:

```text
request_engine_schema_owner
```

for schema creation/hardening and resets role/search path afterward.

The migration is intentionally irreversible through ordinary Alembic downgrade:

```text
downgrade() -> RuntimeError
```

because dropping F1 configuration/commercial provenance after real deployment would destroy accepted business state.

---

## 21. Upgrade behavior

Upgrade from `0001_initial` preserves:

```text
existing Organizations
existing Locations with NULL new structured/geospatial fields
existing Resources/location_id
existing legacy Resource recurrence/exceptions
existing Reservations with no invented commercial commitment
existing CapacityClaims with assignment provenance NULL
existing OfferingVersions with no invented base price
released V3 booking semantics for never-contextualized Resources
```

No automatic conversion from `resources.location_id` into `resource_location_assignments` occurs. Such conversion would invent historical effective time and could change fallback behavior.

---

## 22. Current semantic command mapping

Tenancy:

```text
UpdateOrganizationOperationalProfile
```

Catalog:

```text
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
```

Booking:

```text
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

Future contextual terms use `ConfigureBookingContextTerms` effective dating; no separate storage/lifecycle is needed merely because the effective start is in the future.

Known semantic-surface gaps:

```text
CreateLocation ownership/path
Organization public operational contact mutation
```

---

## 23. Current PostgreSQL proof

The F1 runner includes current dedicated tests for:

```text
schema/constraints
RLS/runtime privileges
business operational info
catalog contextual discovery
Organization/Location operational commands
contextual config/lifecycle commands
contextual direct booking
config-vs-book races
temporal/commercial provenance
contextual shared-capacity
released V3 booking regressions
```

At implementation checkpoint:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
run 32498624044
```

the dedicated F1 PostgreSQL job passed on the consolidated migration.

The same run also passed Python quality, V2 design history, repeated V3 bootstrap and observability. The long frozen-V3 compatibility job was cancelled by a later documentation push, so one fresh exact-head complete run is still required before merge readiness.

---

## 24. Remaining schema/proof obligations

Before Phase C/H can be considered final rather than merely implemented:

1. fix the context-only commercial commitment source/CHECK defect in §13.3;
2. add context-only price booking proof;
3. confirm multi-resource commitment provenance preserves every contextual source;
4. keep concurrent overlap/exclusion tests for contextual terms/assignment changes rather than relying only on sequential errors;
5. keep historical CapacityClaim range-provenance protection green;
6. keep runtime worker privilege denial green;
7. run final clean bootstrap/upgrade to exactly `0002_f1_supply` on the final head;
8. run frozen V3 compatibility to completion on that same final head;
9. verify frozen baseline files have no content changes.

---

## 25. Phase C disposition

The fundamental F1 relational architecture remains sound:

```text
ADD explicit contextual eligibility/configuration
KEEP released V3 legacy path
KEEP Resource as capacity root
KEEP CapacityClaim as capacity ledger
ADD assignment provenance to contextual claims
ADD immutable material Reservation commercial commitment
ADD 0..N contextual commercial-source provenance
ADD revision/fingerprint stale observations
KEEP shared-capacity serialization
KEEP worker/domain privilege split
NO migration-time invented contextual history
NO frozen V3 edits
NO PostGIS in F1
```

But Phase C should **not** be called fully closed while the residual single-context commitment column/CHECK can reject a contract-valid context-only commercial booking.

Fix that inconsistency first, prove it, then treat the consolidated schema as the candidate F1 launch revision.