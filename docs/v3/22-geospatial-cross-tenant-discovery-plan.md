# Request Engine — F2 Geospatial Cross-Tenant Discovery Plan

Status: active implementation/closure plan for `feature/geospatial-cross-tenant-discovery`.

This document turns the accepted F2 direction in `14-operational-intelligence-roadmap.md` into an implementation plan that is safe to execute against the current post-F1 `development` architecture.

It is intentionally more restrictive than the roadmap where ambiguity could otherwise become an unsafe SQL/API decision. It does not rewrite released V3 history, ADR 0011 shared-capacity semantics, or the accepted F1 contract.

---

## 1. Mission

F2 must allow a platform-facing caller to discover concrete, currently valid, explicitly published operational supply across multiple Organizations without receiving generic cross-tenant read authority.

Representative request:

```text
I need a cardiologist today at 5 PM within 10 km.
```

Representative answer:

```text
option A
  tenant/public business identity
  Location
  optionally public Resource/provider identity
  concrete OfferingVersion
  distance
  currently valid time option
  deterministic contextual commercial terms

option B
  ...
```

The user/application chooses an option. Request Engine may filter and order by objective criteria, but F2 does not create an autonomous recommendation engine.

Core product rule:

> Cross-tenant discovery is a projection over explicitly published operational truth. It is not a bypass around tenant ownership, RLS, shared-capacity privacy, or booking revalidation.

---

## 2. Starting point and authoritative references

F2 starts from the integrated `development` state after F1 Operational Profile / Contextual Supply.

Primary references:

1. `v3/14-operational-intelligence-roadmap.md`
   - accepted F2 product direction;
   - Platform Discovery Authority separated from Platform Admin;
   - explicit publication requirement;
   - geospatial proximity;
   - user-choice ranking rule.
2. `v3/15-operational-profile-contextual-supply-contract.md`
   - current Organization/Location operational truth;
   - Location coordinates/hours;
   - Resource-at-Location assignment and availability;
   - contextual Resource + Location + OfferingVersion terms;
   - stale-option revalidation and commercial provenance.
3. `v3/16-operational-profile-contextual-supply-clarifications.md`
   - open F2 requirement for canonical cross-tenant service classification;
   - tenant display strings are insufficient authority.
4. `v3/12-cross-tenant-shared-capacity-design.md` and ADR 0011
   - shared-capacity serialization is private and does not grant cross-tenant read authority;
   - GlobalIdentity / SharedCapacityIdentity knowledge is not discovery authorization.
5. `architecture/pre-production-evolution-policy.md`
   - current contracts may intentionally evolve with equal-or-stronger evidence.
6. `architecture/branch-integration-contract.md`
   - one serialized development integration lane;
   - exact-head proof before merge.
7. `testing/*`
   - current-product evidence must prove durable effects/non-effects, tenant opacity and concurrency behavior rather than merely HTTP status codes.

F2 precedence on this branch is expected to become:

```text
future F2 normative contract
  >
this F2 implementation/closure plan
  >
v3/14 F2 roadmap direction
  >
F1 contract for underlying tenant-local supply
  >
released V3 baseline where not intentionally superseded
```

A separate F2 normative contract MUST be produced before persistence/API semantics are considered closed.

---

## 3. Scope

F2 owns the minimum capability required to expose and search tenant-authorized supply across Organizations.

In scope:

```text
platform discovery authority
explicit tenant-owned discovery publication
publication lifecycle and audit
canonical cross-tenant service classification
explicit tenant Offering -> canonical classification mapping
geospatial radius filtering
objective distance output/order
cross-tenant discovery query/read model
safe public projection of Organization/Location/Resource fields
currently valid OfferingVersion resolution
F1 contextual availability/price/duration composition
opaque handling of unpublished/foreign/private state
booking handoff using a concrete existing appointment option
revalidation before booking
revocation/staleness behavior
PostgreSQL/RLS/least-privilege proof
production-like cross-tenant E2E evidence
```

F2 does not create independent booking/capacity truth. `CapacityClaim` and existing Booking serialization remain authoritative.

---

## 4. Explicit non-goals

Do not implement the following as part of F2 unless a later adversarial review proves they are necessary for correctness:

```text
CRM/customer directory
public GlobalIdentity directory
public SharedCapacityIdentity directory
automatic provider identity matching
EHR/clinical data
free-form RAG as discovery authority
LLM/fuzzy text as authoritative service classification
universal taxonomy editor for every business concept
recommendation/"best provider" engine
sponsored ranking
reviews/ratings persistence as transactional truth
Google Business synchronization
mobile ServiceArea semantics
travel-time/routing engine
live clinic queue state
same-day live workload projection
F3/F4/F5 queue/recovery behavior
arbitrary cross-tenant SQL/RLS bypass for chatbots
new capacity ledger
```

External reputation or map-provider enrichment may later be composed at presentation time, but it must not become F2 operational authority accidentally.

---

## 5. Non-negotiable invariants

### F2-I01 — Organization remains the ownership boundary

A discovery request spanning Organizations does not make tenant-local entities globally owned.

### F2-I02 — Shared-capacity identity is not discovery authority

`GlobalIdentity`, `SharedCapacityIdentity`, bindings and private shared claim provenance remain hidden. Shared physical capacity may influence availability through existing Booking rules only.

### F2-I03 — Existence is not publication

```text
operationally exists
!=
published for platform discovery
```

No Location, Offering, OfferingVersion or Resource becomes discoverable merely because it exists or is bookable tenant-locally.

### F2-I04 — Publication is explicit, revocable, tenant-authorized and auditable

Every discoverable supply path must be traceable to current publication authority.

### F2-I05 — Publication does not duplicate operational truth

Publication controls visibility/eligibility for discovery. It must not copy authoritative price, duration, schedule or capacity into a second mutable truth source.

### F2-I06 — Canonical service matching is explicit

Tenant-owned names/descriptions remain presentation data. Cross-tenant matching uses an approved canonical classification/code mapping.

NLP/fuzzy similarity may propose a mapping to an authorized operator but cannot silently establish it.

### F2-I07 — Discovery authority is least privilege

Platform Discovery Authority may read only the projection required for published discovery and request valid operational availability. It is not `request_engine_admin`, generic RLS bypass, or broad tenant read authority.

### F2-I08 — Unpublished/private state is non-enumerable

Discovery must not expose whether an otherwise matching private tenant Offering, Resource or Location exists.

### F2-I09 — Discovery is advisory; booking revalidates

A discovered option is not a capacity commitment. Booking must revalidate current F1 configuration, publication-sensitive handoff rules where applicable, schedules, terms and capacity.

### F2-I10 — Distance is derived presentation/query data

Coordinates are authoritative Location operational facts from F1. `distance_meters` is derived from origin + Location coordinates and never changes booking truth.

### F2-I11 — Ranking cannot change eligibility

Initial ordering may use objective distance and deterministic tie-breakers. Popularity, if later introduced, may change presentation order only and cannot hide valid supply, change price or select on behalf of the user.

### F2-I12 — Cross-tenant shared contention remains opaque

If two published options ultimately map to the same hidden shared physical capacity, existing shared-capacity serialization decides booking. Discovery never reveals the shared root or foreign commitment metadata.

### F2-I13 — Revocation stops future discovery without rewriting history

Unpublishing supply removes it from future discovery. It must not mutate historical Reservation/CapacityClaim/commercial provenance.

### F2-I14 — Current-product compatibility remains hard

Tenant-local public API, F1 booking, legacy V3 booking, shared capacity, workers and frozen V3 compatibility remain proven unless F2 explicitly supersedes a contract under the evolution policy.

---

## 6. Canonical cross-tenant service classification

This is the most important unresolved semantic dependency inherited from document 16.

Problem:

```text
Tenant A: Cardiología
Tenant B: Consulta cardiológica
Tenant C: Evaluación cardiovascular
```

String similarity is not sufficient authority to claim that all three satisfy the same platform request.

### Planned model

F2 should introduce a narrow platform-owned classification vocabulary, conceptually:

```text
ServiceClassification
  stable opaque/code identity
  canonical machine-facing key
  lifecycle status
  optional human labels/descriptions
```

and an explicit tenant mapping, conceptually:

```text
OfferingServiceClassification
  Organization
  Offering (or other accepted catalog owner)
  ServiceClassification
  status/effective validity when required
  authority/audit provenance
```

The exact names and cardinalities remain contract work, but the following decision is already required:

> The mapping is explicit data, not inferred query-time semantics.

### Mapping authority

Only authorized tenant/control-plane operations may activate/revoke mappings.

A future AI configuration assistant may say:

```text
"This Offering probably maps to cardiology. Approve?"
```

but approval creates the authoritative mapping; the model suggestion itself does not.

### Taxonomy scope discipline

F2 must not attempt to model every medical/business specialty ontology globally. The first taxonomy should contain only the stable classification needed for demonstrated discovery use cases and remain evolvable.

---

## 7. Discovery publication model

The roadmap uses the conceptual term `DiscoveryPublication`. F2 should preserve that intent unless implementation analysis finds a more accurate name.

Publication must answer:

```text
what tenant supply is allowed to appear in platform discovery?
```

It must not answer:

```text
what is the price?
what is the capacity?
what hours are available?
```

Those come from F1/current Booking/Catalog truth.

### Required publication semantics

Before SQL, the normative contract must determine the smallest unambiguous publication scope capable of expressing:

```text
publish this service at this Location
optionally expose provider/Resource identity when policy allows
exclude other Locations
exclude other Offerings
revoke publication without deleting tenant operational data
```

The implementation inventory must explicitly evaluate whether publication is best anchored to:

```text
Organization + Location + Offering
Organization + Location + OfferingVersion
ResourceLocationAssignment + OfferingVersion
or another normalized policy relation
```

The final choice must avoid two failures:

1. automatically publishing a newly created/versioned service configuration that was never reviewed for discovery;
2. forcing publication rows to duplicate F1 contextual terms or capacity.

### Resource visibility

Publication of supply and publication of provider identity are separate concerns.

A tenant may eventually need:

```text
service/location discoverable
provider identity hidden until later
```

versus:

```text
specific provider publicly discoverable
```

F2 contract must make this explicit rather than infer it from presence of a Resource row.

---

## 8. Discovery authority and security model

F2 introduces a capability/authority distinct from both tenant operational mutation and platform administration.

Conceptually:

```text
PlatformAdminAuthority
  global identity / trusted admin work

PlatformDiscoveryAuthority
  search explicitly published supply
  read explicitly public projection fields
  request operational availability for published supply
  hand concrete selected option into ordinary authorized booking
```

These MUST NOT collapse into one role.

### Database boundary

The preferred direction is a narrow protected query surface or dedicated read composition that can intentionally span tenant publication rows while returning only approved projection fields.

Do not solve F2 by granting the normal application role unrestricted SELECT across tenant tables.

The Phase B design must compare at least:

```text
SECURITY DEFINER discovery query functions with fixed search_path + explicit projection
controlled discovery read role/views
Python orchestration over narrowly authorized DB functions
```

and choose the least powerful design that can express the query safely.

Every privileged database surface must prove:

```text
caller authority validation
fixed/controlled search_path where privileged
no dynamic SQL from untrusted search fields
tenant publication filtering before private projection
no UUID/existence oracle
least-privilege grants
bounded query inputs
```

---

## 9. Geospatial contract

F1 owns normalized fixed Location coordinates. F2 consumes them.

Minimum query inputs:

```text
classification/service query
origin latitude
origin longitude
radius_meters
requested date/time or discovery window
optional deterministic result limit
```

Possible later filters:

```text
city/region
currency
specific public provider
```

but they must not be added simply because SQL can support them.

### Coordinate validation

Inputs must validate standard latitude/longitude bounds. Radius must be positive and bounded by an explicit product maximum to avoid an accidental global table scan API.

### Distance implementation

Phase B must decide whether current scale justifies:

```text
PostgreSQL built-in numeric great-circle calculation
or
PostGIS/geography
```

Do not add PostGIS merely for fashion. Choose it only if correctness/indexing/query-plan requirements justify the operational dependency.

Regardless of implementation:

```text
distance calculation must be deterministic enough for contract tests
radius boundary behavior must be specified
ordering ties must have a stable secondary key
```

---

## 10. Discovery query semantics

A discovery result must represent a concrete option candidate assembled from current authoritative facts.

Conceptual pipeline:

```text
canonical service classification
        ↓
active explicit tenant mapping
        ↓
active explicit DiscoveryPublication
        ↓
public Organization/Location projection
        ↓
current eligible OfferingVersion
        ↓
F1 Resource-at-Location eligible supply
        ↓
effective Location hours/exceptions
        ↓
effective Resource/assignment availability/exceptions
        ↓
contextual terms/default resolution
        ↓
objective geo filter/order
        ↓
concrete discovery options
```

The query must not materialize a fake global Resource aggregate.

### Time semantics

The contract must state whether a query asks for:

```text
exact desired start time
window/range
next available
```

The first implementation should prefer the smallest demonstrated query shape rather than simultaneously implementing every scheduler UX.

### Option identity

F2 should reuse the current appointment-option mechanism where possible rather than invent a parallel discoverable-slot token.

If cross-tenant discovery requires a new option envelope/version, it must preserve:

```text
opaque identity
material configuration observations
expiry/staleness
concrete tenant ownership
booking revalidation
```

and must not leak tenant-private IDs beyond approved public/capability identifiers.

---

## 11. Public projection contract

For a published result, expose only fields justified for platform discovery.

Candidate projection:

```text
public Organization display/operational identity
public Organization contact endpoints when publication policy permits
public Location display name/address/contact endpoints
Location coordinates only if product policy intentionally exposes them
computed distance_meters
public Offering display identity
concrete OfferingVersion capability identity required for booking
price amount/currency resolved through F1
planned duration resolved through F1
availability/start/end
optional public Resource/provider display identity
```

The normative contract must distinguish:

```text
needed internally to calculate result
!=
allowed to return externally
```

Foreign/private UUIDs, authority refs, Representation ids, GlobalIdentity, SharedCapacityIdentity, claim ids and unpublished configuration remain excluded.

---

## 12. Mutation surface

F2 likely requires semantic mutations for:

```text
create/activate/deactivate service classification mapping
create/activate/update/revoke DiscoveryPublication
```

These commands must follow the current operational-control-plane standards established in F1:

```text
explicit authority
idempotency key
same key + same body => semantic replay
same key + different body => deterministic conflict
expected revision when mutating revision-owned state
tenant isolation
stable error classification
audit provenance
no partial durable side effects on rejection
```

Do not expose direct table DML as the supported product operation.

---

## 13. Concurrency and race inventory

Before implementation is called complete, F2 must prove at least these races.

### R1 — publication revoke vs discovery

A query racing revocation must either observe the publication before the revocation serialization point or omit it after; no partially unpublished projection.

### R2 — publication revoke vs booking

A previously discovered option may race unpublication. The contract must explicitly decide whether publication is required only for discovery issuance or must still be active at booking.

Default design question to resolve before SQL:

> Does revoking marketplace visibility invalidate an already issued option, or only prevent new discovery?

This must not be accidental.

### R3 — Offering/version change vs discovery

A result cannot silently combine old publication intent with incompatible new OfferingVersion semantics.

### R4 — classification mapping revoke vs discovery

A revoked mapping must stop future classification matches without rewriting tenant Offering history.

### R5 — F1 contextual terms change vs discovery/book

Discovery may issue an option from current terms; booking revalidation must reject stale material changes according to the established F1 option semantics.

### R6 — schedule/exception/assignment change vs discovery/book

Same stale/revalidation discipline as F1.

### R7 — local/shared capacity contention after discovery

Two users can discover apparently free supply. Existing Booking/local/shared capacity locks decide the winner; no F2 publication lock substitutes for capacity serialization.

### R8 — publication idempotency/concurrent create

Equivalent retries create one semantic publication/audit result; conflicting concurrent intent cannot create ambiguous active publication rows.

### R9 — taxonomy mapping uniqueness

Concurrent mappings must not leave one tenant Offering ambiguously mapped to mutually incompatible canonical classifications when the contract declares them exclusive.

### R10 — boundary-distance behavior

Locations at/around the radius boundary must have deterministic inclusion semantics and stable tests.

---

## 14. Phase plan

## Phase A — Current-state inventory

Do not write SQL first.

Produce an explicit inventory of:

```text
current Catalog/Booking/Tenancy models involved
F1 Location coordinate persistence/read APIs
Offering/OfferingVersion lifecycle
ResourceLocationAssignment/contextual terms readers
appointment option issuance/revalidation
public identifiers vs internal UUIDs
current operational authority/idempotency/audit infrastructure
RLS policies and runtime roles
current cross-tenant privileged functions
shared-capacity private surfaces
current public/operational FastAPI composition
current tests proving tenant opacity
```

Deliverable:

```text
old -> reuse / extend / supersede / new / out-of-scope disposition
```

No table or API name is final before this inventory.

## Phase B — Normative F2 contract

Create a dedicated F2 contract document.

It must close:

```text
publication granularity
publication lifecycle
booking effect of later unpublication
canonical classification model/cardinality
classification authority
Platform Discovery Authority contract
public projection fields
geo input/radius semantics
distance calculation choice
query time shape
option/handoff semantics
revision/idempotency/error behavior
RLS/privileged-query strategy
migration ownership
```

This is the gate before persistence implementation.

## Phase C — Relational and privilege design

Design append-only migration from current head (`0003_f1_runtime_acl_completion.py`).

Expected next migration is `0004_*` if no other migration lands first; the actual revision number must be reconciled with current `development` immediately before implementation.

Define:

```text
classification relations
explicit Offering mapping relations
publication relations
keys/uniqueness/effective validity
revision model
audit/idempotency ownership
RLS/grants
narrow discovery query surface
indexes supporting classification + publication + geo filtering
```

Prove clean bootstrap and upgrade from current production migration head.

## Phase D — Semantic configuration commands

Implement supported mapping/publication mutations through module-owned application commands and adapters.

Required proof:

```text
authority
idempotency
stale revision
foreign target opacity
unknown target opacity
one durable effect/audit
rejected operation leaves no partial durable state
```

## Phase E — Discovery read model/query

Implement the narrow cross-tenant query surface.

It must compose current truth rather than denormalize a second booking engine.

Start with one demonstrated search shape and deterministic result ordering.

## Phase F — HTTP/capability surface

Expose discovery through a dedicated capability/API boundary appropriate for platform callers.

Do not automatically place it in tenant-local public API routes if that would blur authority semantics.

Define stable error envelopes for:

```text
invalid geo query
invalid/unknown canonical classification
unauthorized discovery caller
no published matches
stale/expired option where relevant
```

"No matches" should normally be an empty successful search result, not an existence oracle error.

## Phase G — Booking handoff

Prove:

```text
discover across tenant A/B
select one concrete option
book only selected tenant option
normal tenant Booking authority applies
F1 material observations revalidate
shared-capacity mutex still applies when bound
foreign tenant metadata remains opaque
```

F2 does not create a cross-tenant super-booking transaction.

## Phase H — Adversarial security/concurrency proof

Run PostgreSQL-backed tests for every invariant/race above.

Include an adversarial matrix covering:

```text
published vs unpublished
same classification across multiple tenants
foreign/unknown UUID probes
revoked publication
revoked classification mapping
wrong discovery authority
expired authority if Representation-based
radius boundary
same provider physically shared across tenants
simultaneous booking after same discovery result
contextual terms stale after discovery
Location hours exception after discovery
Resource assignment retirement after discovery
```

## Phase I — Test architecture integration

New F2 evidence should follow durable ownership rather than create a permanent feature silo by default.

Preferred destinations:

```text
tests/modules/...         domain/application semantics
tests/db/...              relational/RLS/privilege proofs when introduced
tests/e2e/...             platform discovery -> selected booking journeys
tests/architecture/...    authority/surface/governance invariants
```

Feature-local integration directories are temporary only when useful during active implementation and must have an explicit post-merge disposition.

Extend `current-guarantees.toml` / proof map when F2 introduces new durable guarantees.

## Phase J — Documentation reconciliation and exact-head closure

Before merge:

```text
roadmap reflects F1 integrated + F2 active/implemented state
F2 plan matches actual implementation
F2 normative contract matches actual behavior
ADR added only if F2 creates a durable hard-to-reverse architecture decision not already covered by existing ADRs
module ownership/connection surfaces updated if necessary
migration docs current
operational/public API docs current
test guarantee inventory current
no stale "future F2" wording remains in authoritative indexes
```

Then require exact-head CI against current `development` and normal PR integration-lane rules.

---

## 15. Evidence matrix / Definition of Done

F2 is not merge-ready because a query returns results. It is merge-ready only when all of the following are proven.

### Classification

- equivalent tenant Offerings can be mapped to one canonical classification explicitly;
- unmapped Offering is not matched by fuzzy/display text;
- revoked mapping disappears from future discovery;
- foreign mapping state is not enumerable.

### Publication

- operational supply is invisible until explicitly published;
- publication can be revoked;
- publication mutation is authorized/idempotent/audited;
- rejected/conflicting publication leaves no partial durable effects;
- publication does not duplicate price/schedule/capacity truth.

### Geo

- exact radius semantics are tested;
- distance is deterministic within accepted tolerance;
- stable ordering exists for equal/near-equal distance;
- invalid coordinates/radius fail predictably;
- bounded radius prevents accidental unrestricted global scans.

### Cross-tenant privacy

- discovery authority returns only published projection fields;
- app/worker/tenant callers cannot use discovery internals as generic cross-tenant SELECT;
- unpublished foreign vs nonexistent probes are observationally equivalent where required;
- shared-capacity/global-identity state remains private.

### Operational correctness

- Location hours/exceptions affect discovery;
- Resource assignment availability/exceptions affect discovery;
- contextual price/duration resolve exactly as F1 defines;
- stale material changes between discovery and booking are revalidated;
- booking writes ordinary tenant-owned Reservation/CapacityClaim provenance.

### Concurrency

- two callers can discover the same capacity and Booking still serializes correctly;
- cross-tenant shared physical capacity still produces one winner where exclusive;
- publication/mapping races cannot create ambiguous active state;
- revocation race behavior matches the normative contract.

### Compatibility

- existing tenant-local public API remains compatible;
- F1 operator/customer journeys remain green;
- legacy V3 booking/capacity proof remains green;
- frozen V3 public compatibility and historical provenance remain green;
- current-product CI proof remains green.

---

## 16. Decisions deliberately deferred to Phase B

The plan intentionally does not pretend the following are already settled:

1. exact persisted name and granularity of `DiscoveryPublication`;
2. whether publication anchors to Offering or OfferingVersion;
3. whether provider identity publication is a flag/policy or a separate publication relation;
4. whether unpublication invalidates already issued options or only future searches;
5. whether canonical classification mapping is one-to-one or permits multiple compatible classifications per Offering;
6. whether classification vocabulary is global-only or supports hierarchy/aliases in the first iteration;
7. PostGIS versus bounded numeric great-circle implementation;
8. exact external discovery endpoint/capability naming;
9. whether a new appointment-option envelope/version is required;
10. the narrowest database privilege/query mechanism for safe cross-tenant projection.

These are not implementation details. They affect security, stale semantics, auditability or future compatibility and therefore must be decided explicitly in the F2 contract before SQL is treated as authoritative.

---

## 17. First execution sequence

The immediate work order for this branch is:

```text
A1  inventory current F1/V3 code + schema + API surfaces
A2  produce old -> new disposition
A3  adversarially review publication/classification/authority choices
B1  write normative F2 contract
B2  define race matrix and public projection
B3  choose geo/query strategy
C1  design relational model and privileges
C2  only then create append-only migration
D+  implement commands/query/API/evidence
```

Do not skip A/B and jump directly to `0004`. F2 crosses the tenant isolation boundary intentionally, so mistakes in authority/publication semantics are substantially harder to repair after persistence/API shape has been normalized into code.

---

## 18. Merge condition

The branch may merge into `development` only when:

```text
complete F2 intended scope implemented
normative contract reconciled with implementation
all F2 invariants/races have executable evidence
no cross-tenant generic read capability introduced
current-product guarantees remain green
frozen V3 compatibility/provenance remains green
branch is up to date with development
.github/development-integration-lane matches this branch
exact PR head passes required CI
PR is mergeable with no unresolved review blockers
```

The guiding rule for F2 is:

> Publish intent explicitly; derive options from current truth; reveal only the approved projection; revalidate before commitment.
