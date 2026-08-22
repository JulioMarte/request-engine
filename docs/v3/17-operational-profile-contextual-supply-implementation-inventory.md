# Operational Profile & Contextual Supply — Phase B Implementation Inventory

Status: completed implementation inventory for `feature/operational-profile-contextual-supply` before F1 schema work.

Normative sources:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
docs/v3/16-operational-profile-contextual-supply-clarifications.md
docs/v3/13-operational-profile-contextual-supply-plan.md
docs/adr/0012-contextual-resource-location-supply.md
```

Baseline inspected: released V3 / `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573` as inherited by this feature branch.

This document closes Phase B. It records the current implementation, the F1 target disposition and the constraints that must govern Phase C. It intentionally contains no production migration SQL.

---

## 1. Executive disposition

F1 is an extension of the released V3 model, not a rewrite.

The current code has four structural facts that determine the implementation strategy:

1. `resources.location_id` currently models at most one Location directly on a Resource.
2. `availability_schedules` and `schedule_exceptions` are Resource-scoped, not Resource-at-Location scoped.
3. `OfferingVersion` has duration but no authoritative fixed amount/currency contract.
4. appointment option tokens prove slot identity and expiry but do not bind a material configuration/commercial observation.

Therefore F1 cannot be implemented correctly through a few nullable columns or by repurposing existing rows. The accepted strategy is additive contextual configuration with an explicit compatibility path.

Normative resolver rule:

```text
accepted contextual configuration exists for the Resource/context
  -> use F1 contextual resolution and F1 revalidation
else
  -> preserve released V3 booking behavior
```

Existing V3 rows are not bulk reinterpreted into invented contextual provenance.

---

## 2. Tenancy inventory

### Current

`request_engine.organizations` currently provides:

```text
id
organization_key
display_name
public_profile JSONB
created_at
updated_at
```

`Principal`, `Party`, `PartyContactPoint` and `Representation` already provide tenant-local identity/delegated authority foundations.

Python tenancy currently concentrates on Party authority resolution. There is no existing F1 Organization operational-profile command surface.

### Disposition

| Current concept | F1 disposition | Required direction |
| --- | --- | --- |
| `organizations.id` / tenant boundary | KEEP | Remains authoritative tenant/security boundary. |
| `organization_key` | KEEP | Stable tenant key; not operational profile storage. |
| `display_name` | KEEP/EXTEND | Reuse as the current public/display identity unless implementation proves a distinct typed field is required. |
| `public_profile JSONB` | KEEP FOR COMPATIBILITY | Must not become authority for timezone/currency/contacts/hours. Existing presentation data may remain. |
| typed Organization defaults | ADD | Narrow typed defaults for operational timezone/locale/currency and any separately justified legal/status field. |
| Organization public operational endpoints | ADD | Dedicated tenant-owned relation; separate lifecycle from `PartyContactPoint`. |
| `PartyContactPoint` | KEEP | Identity/communication contact for Party; do not reuse its ownership semantics for public business endpoints. |
| `Representation` authority | EXTEND/REUSE | New semantic configuration commands must use existing Principal/Representation authority patterns rather than ID possession. |

### Constraint

Do not introduce `operational_config JSONB`. Operational defaults used by execution must be typed and relationally constrained.

---

## 3. Catalog inventory

### 3.1 Location

Current `locations` provides:

```text
id
organization_id
location_key
display_name
timezone
public_data JSONB
active
created_at
updated_at
```

Current `business.get_info` reads `business_info_v1` plus `locations_v1` and exposes `public_profile` / `public_data` as opaque dictionaries.

There are no dedicated Location address, coordinate, recurring-hours, Location-hours-exception or public-operational-endpoint relations in the released schema.

### Location disposition

| Current concept | F1 disposition | Required direction |
| --- | --- | --- |
| `locations` identity/FK | KEEP | Continue as Catalog-owned physical Location identity. |
| `locations.timezone` | KEEP/STRENGTHEN | Already typed; validation/resolution must use IANA timezone semantics. |
| `locations.active` | KEEP | Preserve compatibility; a richer state must only be added if F1 commands require semantics beyond active/inactive. |
| `locations.public_data` | KEEP FOR COMPATIBILITY | Not authority for F1 address/hours/contacts/coordinates. |
| structured address | ADD | Typed structured fields/relation; same-tenant ownership. |
| latitude/longitude | ADD | Both-present-or-both-absent, range constrained; nullable for legacy Locations. |
| geocoding provenance | ADD NARROWLY | Source/timestamp only as needed; external geocoding stays outside authoritative locks. |
| recurring operational hours | ADD | Location-owned local-wall-clock recurring windows. |
| `LocationHoursException` | ADD | Explicit Location-wide closure/additional-hours lifecycle. |
| Location public operational endpoints | ADD | Typed/normalized/public/active endpoint rows; not Party contacts. |

### 3.2 Offering / OfferingVersion

Current `offering_versions` provides:

```text
version
duration_minutes
bookable
requestable
booking_policy JSONB
public_data JSONB
```

Current booking resolves `duration_minutes` directly from `OfferingVersion`. No fixed amount/currency columns or immutable reservation commercial commitment exist.

### Offering disposition

| Current concept | F1 disposition | Required direction |
| --- | --- | --- |
| `Offering` identity/lifecycle | KEEP | Remains commercial/service identity. |
| `OfferingVersion` versioning | KEEP | F1 must consume existing immutable/versioned service identity. |
| `duration_minutes` | KEEP/EXTEND SEMANTICS | Becomes the base/default planned duration for F1 contextual resolution. |
| fixed default amount/currency | ADD | Typed deterministic default terms; no formula language. |
| `booking_policy` | KEEP | Do not use as a hidden pricing/config inheritance bag. |
| `public_data` | KEEP | Presentation metadata only; not authoritative contextual terms. |
| operational workload classification | DO NOT ADD IN F1 | Deferred to F3 per clarification 16. |

---

## 4. Booking inventory

### 4.1 Resource identity and Location relationship

Current `resources` includes:

```text
organization_id
location_id nullable
resource_key
display_name
capacity_model
capacity_units
active
availability_revision
```

The current direct `resource.location_id` relation cannot represent one physician working at multiple Locations with independent effective periods and schedules.

### Disposition

| Current concept | F1 disposition | Required direction |
| --- | --- | --- |
| `Resource` | KEEP | Remains local capacity/serialization root. |
| `capacity_model` / `capacity_units` | KEEP | No contextual assignment may duplicate capacity truth. |
| `availability_revision` | EXTEND OR SUPERSEDE FOR CONTEXT OBSERVATION | Legacy revision remains valid; F1 needs material contextual revision/fingerprint semantics. |
| `resources.location_id` | KEEP AS LEGACY COMPATIBILITY | Do not drop/rewrite in initial F1 migration. Used by released V3 path when no contextual assignment exists. |
| `ResourceLocationAssignment` | ADD | Explicit effective-dated Resource-at-Location eligibility/configuration relation. |
| assignment capacity | FORBIDDEN | Assignment never consumes capacity. |

The assignment must use same-Organization composite relationships and non-ambiguous effective periods.

### 4.2 Availability schedules

Current `availability_schedules` is keyed to `resource_id` and stores recurring weekday/local-time/timezone rules.

Current domain code (`RecurringAvailability`, DST-safe local resolution, half-open concrete interval behavior) is reusable.

### Disposition

```text
availability_schedules (Resource-scoped)
  KEEP as released-V3 compatibility input

new ResourceLocationAssignment recurring availability
  ADD for contextual F1 path
```

Do not mutate legacy schedule rows to pretend they historically belonged to a ResourceLocationAssignment.

The F1 contextual schedule should derive timezone authority from the Location. Persisting a redundant timezone on contextual windows should be avoided unless a concrete integrity/versioning requirement justifies it.

### 4.3 Schedule exceptions

Current `schedule_exceptions` is Resource-wide only:

```text
resource_id
during tstzrange
available/unavailable
reason
```

This already models one of the two F1 intents: an explicit Resource-wide exception. It cannot safely represent an assignment-specific exception.

Disposition:

```text
existing Resource-scoped schedule_exceptions
  KEEP as Resource-wide / legacy-compatible behavior

Resource-at-Location exception
  ADD explicit assignment scope

LocationHoursException
  ADD under Catalog/Location ownership
```

The implementation may converge exception mechanics behind shared domain interval operations, but scope must remain explicit in persistence and commands.

A narrow exception must never silently broaden to all Resource assignments.

### 4.4 Capacity

Current `CapacityClaim` remains the authoritative local capacity-consumption ledger and is already tied to Resource + requirement + Hold/Reservation.

Disposition:

```text
CapacityHold  KEEP
CapacityClaim KEEP
Resource locking/capacity protocol KEEP
shared-capacity binding/mutex KEEP
```

F1 contextual checks occur before/alongside the existing authoritative claim protocol; they never replace it.

---

## 5. Current `find_slots` behavior and F1 disposition

Current `PostgresAppointmentAvailabilityReader`:

1. loads one `OfferingVersion` duration/policy;
2. selects candidate Resources by capability;
3. filters through `resources.location_id`;
4. loads Resource-scoped schedules/exceptions/live Claims;
5. produces advisory intervals;
6. returns `AppointmentSlot` with resource choices and at most one inferred Location.

Important current behavior:

```text
requested Location matches when
r.location_id IS NULL OR r.location_id = requested_location
```

That wildcard behavior is valid only for the released V3 fallback. It cannot be reused as F1 proof that a Resource is assigned to a contextual Location.

### F1 disposition

`find_slots` must become a two-path resolver:

```text
contextual path
  resolve effective ResourceLocationAssignment
  resolve effective Location hours + Location exceptions
  resolve assignment recurring availability
  apply Resource-wide + assignment-specific exceptions
  resolve exact/base contextual duration + fixed amount/currency
  consider live capacity advisory state
  produce material configuration observation

legacy path
  preserve current V3 resource/location/schedule behavior
```

No natural-language parsing enters Booking; the current explicit `window_start`/`window_end` design is compatible with F1.

The query contract must be extended for explicit/any Resource preference as required by F1 without breaking existing callers.

---

## 6. Appointment option token inventory

Current `SignedAppointmentOptionCodec` (`aptopt_v1`) signs:

```text
organization_id
offering_version_id
start/end
location_id
resource choices
issued_at/expires_at
```

It does not bind:

```text
contextual assignment
schedule/location-hours observation
contextual terms revision
presented amount/currency
planned duration as resolved context
material configuration fingerprint
```

### Disposition

KEEP the signed opaque-token architecture.

EXTEND through a versioned token contract (conceptually `aptopt_v2`, final name decided during implementation) that binds enough server-verifiable material observation to reject stale configuration and silent price substitution.

Do not mutate v1 decoding semantics in a way that makes already issued v1 tokens mean something different. During deployment, v1 may continue through the legacy-compatible path or be rejected with the existing expiry/invalid contract according to the final rollout proof.

---

## 7. Authoritative booking/hold commands

Current authoritative commitment code already performs the right broad transaction shape:

```text
idempotency
load bookable OfferingVersion
validate subject/Location/origin
authority
load requirements
lock Resources
validate capabilities/location
load locked availability profiles
revalidate exact slot
insert Hold/Reservation + CapacityClaims
audit/outbox
commit
```

This is an asset and must be extended, not replaced.

### F1 insertion point

After Resources are locked and before capacity commitment succeeds, contextual booking must resolve/revalidate under the same authoritative transaction:

```text
OfferingVersion current state
ResourceLocationAssignment effective state
Location effective availability
Resource contextual availability
Resource-wide + assignment exceptions
contextual/base price and duration
option material observation
existing capacity/shared-capacity protocol
```

No external geocoder/provider call may occur in this transaction.

---

## 8. Historical Reservation inventory

Current `reservations` stores:

```text
offering_version_id
subject_party_id
location_id
origin_request_id
during
status
booking_policy_snapshot
revision/timestamps
```

It does not persist an explicit committed amount/currency or resolved contextual-term provenance.

### Disposition

KEEP Reservation identity/lifecycle.

ADD immutable/explainable F1 commercial commitment fields or a Reservation-owned immutable commercial record carrying at minimum:

```text
committed_amount
currency
resolved OfferingVersion
contextual terms/assignment observation or equivalent provenance
committed_at as needed
```

Do not backfill legacy Reservations with fictional commercial provenance.

Any mutable Reservation lifecycle operation must be prevented from rewriting the original committed commercial fact unless a separate explicit new commercial commitment is created by a supported reschedule/rebooking semantic.

---

## 9. Public read models

Current read views are security-invoker views:

```text
request_read.business_info_v1
request_read.locations_v1
request_read.offering_summary_v1
request_read.reservation_status_v1
```

Current `business.get_info` exposes Organization `public_profile` and Location `public_data` but not typed F1 operational facts.

### Disposition

KEEP existing v1 views for compatibility.

ADD/EXTEND application queries through a versioned/read-compatible surface rather than silently changing meanings required by existing consumers.

F1 business information must be capable of returning safe typed:

```text
Organization operational defaults/public central endpoints
Location structured address
Location public endpoints
Location effective/recurring operational hours as contractually appropriate
Location timezone
```

Administrative revision/provenance data is not public business info.

---

## 10. Authorization and runtime DB access

Current runtime roles are tenant-table based and use RLS-protected access. The released read views use `security_invoker = true`. App/worker roles currently have SELECT/INSERT/UPDATE on tenant tables; DELETE is deliberately absent because lifecycle removal is semantic state transition.

### Disposition

KEEP:

```text
RLS defense-in-depth
tenant_transaction context
no DELETE runtime lifecycle pattern
semantic authority through Principal/Representation
request_engine_admin not used as normal clinic configuration authority
```

Every new F1 table must receive the same tenant/RLS/privilege treatment and same-Organization relational backstops.

New semantic commands must not rely merely on the broad SQL privilege being available to the app role; application authority remains mandatory.

---

## 11. Migration inventory

The repository currently has one Alembic revision:

```text
migrations/versions/0001_initial.py
```

It installs the frozen V3 initial payload. V3 candidate/design-chain SQL is historical provenance.

### F1 disposition

```text
0001_initial.py                         KEEP UNTOUCHED
migrations/sql/v3_initial/*            KEEP UNTOUCHED
migrations/sql/v3_candidate/*          KEEP UNTOUCHED
migrations/sql/design_chain/*          KEEP UNTOUCHED
new Alembic revision(s) after 0001     ADD
```

Phase C must prove both:

```text
empty database -> 0001 -> F1 head
existing released 0001 database -> F1 head
```

No F1 table or column is added to frozen payload files.

---

## 12. Old -> new disposition matrix

| V3 implementation | Disposition | F1 target |
| --- | --- | --- |
| Organization tenant identity | KEEP | Same security boundary. |
| Organization `display_name` | KEEP/EXTEND | Operational display identity. |
| Organization `public_profile` | COMPATIBILITY | Non-authoritative presentation metadata. |
| Organization operational defaults | ADD | Typed timezone/locale/currency etc. |
| Party/Principal/Representation | KEEP/EXTEND | Authority substrate for new commands. |
| PartyContactPoint | KEEP | Never silently becomes business endpoint lifecycle. |
| Location identity/timezone | KEEP/EXTEND | Physical operational place. |
| Location `public_data` | COMPATIBILITY | Presentation metadata only. |
| Location address/coordinates | ADD | Structured, constrained operational truth. |
| Location recurring hours | ADD | Physical availability baseline. |
| Location hours exceptions | ADD | One-off closure/additional availability. |
| Organization public endpoints | ADD | Central operational contact surface. |
| Location public endpoints | ADD | Location-specific operational contact surface. |
| Offering / OfferingVersion | KEEP | Existing versioned commercial service identity. |
| OfferingVersion duration | KEEP AS DEFAULT | Context may override exact planned duration. |
| OfferingVersion fixed price/currency | ADD | Deterministic base commercial terms. |
| Resource | KEEP | Capacity/serialization root. |
| Resource `location_id` | LEGACY COMPATIBILITY | Used only by released-V3 path absent contextual config. |
| ResourceCapability assignment | KEEP | Eligibility vocabulary linkage. |
| ResourceLocationAssignment | ADD | Effective-dated Resource-at-Location eligibility. |
| Resource `availability_schedules` | LEGACY/RESOURCE-WIDE KEEP | Existing V3 schedule fallback. |
| assignment recurring availability | ADD | Contextual Location-specific Resource schedule. |
| Resource `schedule_exceptions` | KEEP/RESOURCE-WIDE | Explicit Resource-wide/legacy exception semantics. |
| assignment-specific exception | ADD | Narrow Resource-at-Location exception. |
| CapacityHold | KEEP | Temporary commitment. |
| CapacityClaim | KEEP | Sole local capacity ledger. |
| Reservation | KEEP/EXTEND | Add immutable commercial/context provenance. |
| `AppointmentSlot` | EXTEND | Include resolved contextual operational/commercial output as appropriate. |
| `aptopt_v1` architecture | KEEP/VERSION | New version binds material contextual observation. |
| `find_slots` reader | EXTEND | Context resolver + exact legacy fallback. |
| booking/hold transaction | EXTEND | Context revalidation before commitment. |
| read views v1 | KEEP | Add versioned typed F1 read surfaces as needed. |
| RLS/runtime roles | KEEP/EXTEND | New relations receive equivalent isolation/privilege treatment. |
| shared-capacity mutex | KEEP | Context cannot bypass global binding/serialization. |

---

## 13. Phase C schema obligations discovered by inventory

Before application implementation, the new append-only schema must be capable of representing and proving at least:

1. typed Organization operational defaults without using `public_profile` as authority;
2. Organization and Location public operational endpoint ownership;
3. structured Location address and valid optional coordinate pair;
4. Location recurring hours and explicit Location-hours exceptions;
5. effective-dated `ResourceLocationAssignment` with same-tenant and non-ambiguous overlap rules;
6. assignment-scoped recurring availability;
7. explicit assignment-scoped exceptions while retaining Resource-wide exception intent;
8. OfferingVersion fixed default amount/currency and existing duration default;
9. effective-dated exact Resource + Location + OfferingVersion contextual fixed terms with non-ambiguous overlap rules;
10. a material configuration revision/fingerprint strategy that booking can revalidate;
11. immutable Reservation commercial commitment/provenance for new F1 bookings;
12. historical FK/reference behavior that allows assignment/config retirement without destroying Reservation/Claim meaning;
13. RLS and runtime privileges on every new relation;
14. indexes needed for effective-time resolution and authoritative lock acquisition without speculative F2 geospatial indexing.

---

## 14. Decisions intentionally NOT closed by Phase B

Phase B does not prematurely choose:

```text
exact SQL table names beyond canonical domain meaning
one-table vs narrow sibling-table layout for public operational endpoints
whether Organization defaults live directly on organizations or typed 1:1 profile row
whether Reservation commercial commitment is inline or Reservation-owned immutable child
exact fingerprint encoding/token field layout
PostGIS (still not justified by F1)
F2 canonical service taxonomy
F3 workload classification
```

These choices belong to Phase C/D and must be selected by invariant strength, compatibility and query/lock topology rather than aesthetics.

---

## 15. Phase B conclusion / gate

No hidden architecture blocker was found. The F1 contract is implementable on the released V3 architecture, but only as an additive contextual model with explicit legacy fallback.

The most dangerous incorrect implementations are now ruled out:

```text
DO NOT turn resources.location_id into a multi-location truth by reinterpretation
DO NOT migrate every legacy schedule into invented assignments
DO NOT overload public_profile/public_data as operational authority
DO NOT make assignment a capacity ledger
DO NOT weaken CapacityClaim/shared-capacity serialization
DO NOT model Location closures as N Resource exceptions
DO NOT treat assignment-specific exceptions as Resource-wide
DO NOT rely on aptopt_v1 expiry alone for stale contextual configuration
DO NOT reconstruct historical committed price from mutable current configuration
DO NOT edit frozen V3 migration history
```

Phase B is complete.

The next allowed step is Phase C: design the minimal append-only relational schema and migration proof plan against this disposition before writing application handlers.