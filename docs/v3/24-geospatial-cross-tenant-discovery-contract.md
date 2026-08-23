# Request Engine — F2 Geospatial Cross-Tenant Discovery Contract

Status: normative integrated contract for `feature/geospatial-cross-tenant-discovery`.

This document is the authoritative F2 contract after adversarial hardening. It incorporates the corrections originally recorded in `25-geospatial-cross-tenant-discovery-hardening.md`; document 25 remains useful as review provenance explaining why those corrections were necessary, but it no longer overrides this contract.

F2 extends the current product beyond the released V3 baseline without rewriting V3 historical evidence. `Organization` remains the tenant boundary, Booking remains the commitment authority, ADR 0011 remains authoritative for hidden shared-capacity serialization, and F1 remains authoritative for operational/contextual supply semantics.

## 1. Product capability

F2 adds one platform-facing capability:

```text
discovery.search_supply
```

It searches currently valid supply across Organizations that explicitly opted into platform discovery.

A search contains:

```text
canonical service classification
origin latitude/longitude
radius
appointment window
bounded result limit
```

A result may contain only the explicitly approved public projection:

```text
Organization public identity
Location public identity
Offering public identity
distance_meters
appointment start/end
deterministic planned duration/amount/currency
opaque discoopt_v1 handoff token
```

Concrete Resource identity is not emitted by the initial F2 contract. Discovery is advisory and never consumes capacity.

## 2. Non-negotiable boundaries

### F2-C01 — tenant ownership remains intact

`Organization` remains the security and administrative owner of tenant Location, Offering, Resource, Party and booking state. Publication grants only the narrow discovery projection defined here.

### F2-C02 — shared capacity is private implementation authority

`GlobalIdentity`, `SharedCapacityIdentity`, bindings and shared-capacity claim links remain private. They are not discovery identifiers, authorization inputs or public output.

### F2-C03 — existence is not publication

Tenant operational data is not discoverable merely because it exists, is active or is visible through that tenant's own API. F2 requires explicit active mapping plus explicit active/effective publication.

### F2-C04 — no generic cross-tenant database authority

The Discovery runtime must not receive `request_engine_admin`, `BYPASSRLS`, generic `request_engine_app` tenant-table authority or arbitrary cross-tenant relation access.

Cross-tenant reads/writes are restricted to purpose-built protected functions that expose only the F2 candidate/handoff contract.

### F2-C05 — Booking remains authoritative

Discovery never creates or mutates Reservation, CapacityClaim, CapacityHold, commercial commitment or shared-capacity provenance. Normal Booking performs the authoritative transactional revalidation and commitment.

## 3. Canonical service classification

### 3.1 ServiceClassification

A platform-owned canonical service classification has:

```text
id
classification_key
canonical_name
status
revision
created_at
updated_at
```

`classification_key` is stable, unique and machine-facing, for example:

```text
cardiology
dermatology
general_dentistry
commercial_refrigeration_repair
```

It carries no price, schedule or capacity truth.

### 3.2 OfferingServiceClassification

An Organization explicitly maps a tenant `Offering` to one active primary `ServiceClassification`.

F2 does not make fuzzy text, embeddings or LLM classification authoritative. Those systems may propose a classification; the durable mapping is created only through the semantic authority path.

### 3.3 Mapping lifecycle and provenance

Mapping authority requires:

```text
operations.manage_discovery
```

A mapping row's Organization and Offering scope are immutable. Reclassification is not an in-place rewrite of `service_classification_id`; it is:

```text
lock Offering
revoke old mapping
insert replacement mapping
append supersession/audit provenance
```

Revocation is monotonic. Concurrent first-mapping attempts serialize through the Offering lock so at most one active mapping survives.

Tenant runtimes do not receive global taxonomy enumeration authority. Taxonomy lookup and retirement predicates use narrow protected functions. Taxonomy creation/retirement remain platform-admin operations with auditable authority evidence.

## 4. DiscoveryPublication

A publication means:

> this Organization authorizes this Offering/Location/optional-Resource scope to participate in platform discovery during this effective interval.

It is authorization/provenance, not a cache of Booking truth.

A publication owns:

```text
organization_id
offering_id
location_id
resource_id?        # optional scope restriction
effective_during
status              active | revoked
provider_visibility hidden | public
revision
created_at
updated_at
```

It must not duplicate authoritative operational fields such as price, currency, duration, hours, schedule exceptions, capacity, address, coordinates, display names or appointment slots.

One publication row has immutable Organization, Offering, Location, Resource/null scope, effective interval and provider visibility. Changing visibility or scope requires revoke + new publication. Revocation is monotonic and never rewrites an already committed Reservation.

### 4.1 Overlap semantics

Exact-scope active publication intervals must not overlap.

Additionally, broad publication (`resource_id IS NULL`) and resource-specific publication for the same Organization + Offering + Location must not overlap in time. PostgreSQL serializes this mixed-scope rule with the accepted lock/check protocol. Different resource-specific publications may coexist when otherwise valid.

## 5. Platform discovery runtime authority

F2 uses a platform-facing actor distinct from tenant `ActorContext`:

```text
PlatformDiscoveryActor
  principal_id
  capabilities
  principal_kind
  authentication_method
  correlation_id
  credential_id?
```

It contains no caller-selected Organization because the operation is intentionally cross-tenant.

The public Discovery process is composed only from narrow ports:

```text
DiscoveryCandidateReader
PublishedSlotReader
DiscoveryHandoffIssuer
PlatformDiscoveryActorResolver
```

It must not receive:

```text
request_engine_app generic SessionFactory
request_engine_admin credentials
normal Booking appointment-option signing key
arbitrary cross-tenant SQL access
```

PostgreSQL exposes a dedicated grant role:

```text
request_engine_discovery
  NOLOGIN
  NOBYPASSRLS
```

Deployment credentials may inherit that role. The role receives only EXECUTE on exact protected candidate/handoff functions and no generic tenant-table DML/SELECT. Privileged function bodies remain owned by the trusted schema/admin boundary.

The protected discovery projection must never return Party/customer/patient ids, Reservation ids, CapacityClaim ids, SharedCapacityIdentity ids, GlobalIdentity ids, Representation rows, private audit evidence or unpublished tenant state.

## 6. Search query contract

`SearchPublishedSupplyQuery` contains:

```text
service_classification_key: str
origin_latitude: Decimal
origin_longitude: Decimal
radius_meters: int
window_start: datetime
window_end: datetime
limit: int
```

Initial bounds are explicit and enforced at both HTTP/application and protected-SQL boundaries:

```text
-90 <= latitude <= 90
-180 <= longitude <= 180
0 < radius_meters <= 100_000
window_start/window_end timezone-aware
window_end > window_start
window <= 7 days
1 <= limit <= 100
```

The SQL surface independently validates the contract because HTTP validation is not sufficient protection for a SECURITY DEFINER boundary.

## 7. Candidate eligibility

A candidate may enter availability evaluation only when all relevant facts are current:

```text
ServiceClassification active
Offering mapping active
DiscoveryPublication active and effective
Organization operationally active
Offering active
latest OfferingVersion is bookable
Location active and geocoded
Location inside requested radius
publication ownership/scope coherent
optional published Resource active and same-tenant coherent
```

Candidate publication does not prove appointment availability.

## 8. Geospatial semantics

Distance is derived objective data using a great-circle/Haversine-equivalent calculation over authoritative F1 coordinates.

```text
distance_meters >= 0
inside radius iff distance_meters <= radius_meters
```

The boundary is inclusive. The SQL calculation clamps the floating-point intermediate to `[0,1]` before `sqrt/asin` so valid extreme-coordinate queries cannot fail from rounding drift.

Distance does not change price, capacity, eligibility or booking priority.

## 9. Availability composition and process boundary

F2 reuses Booking slot semantics; it does not implement a second scheduler.

```text
published candidate
      ↓
internal Booking published-slot gateway
      ↓
authoritative F1/Booking availability
      ↓
publication Location/Resource scope filter
      ↓
DiscoveryOption
```

The public Discovery process talks to Booking through the remote `PublishedSlotReader` contract. The internal Booking availability process owns normal tenant-domain credentials. Composition rejects injecting a local tenant Booking reader directly into the public Discovery process.

Any future batching/performance optimization must remain behaviorally equivalent to authoritative Booking slot semantics.

## 10. Commercial eligibility

F2 emits only options for which F1 can determine a complete current contextual commitment:

```text
Location
configuration fingerprint
location operational revision
Resource/Location assignment observations
planned duration
amount
currency
```

Legacy tenant-local Booking remains supported by the existing API, but supply without the deterministic contextual/commercial provenance required by F2 is excluded from cross-tenant discovery.

F2 does not invent marketplace-specific pricing.

## 11. Global ranking and bounded exhaustive search

Successful responses are globally ordered by:

```text
1 earliest appointment start
2 distance_meters
3 stable Organization/Location/Offering/Resource/Publication tie-breakers
```

The system must not choose the nearest N publications before evaluating appointment time because that can omit a farther provider with an earlier valid appointment.

Current implementation therefore uses bounded exhaustive candidate evaluation:

```text
eligible candidates <= 200
  evaluate every candidate
  globally sort resulting options

eligible candidates >= 201
  return 422 discovery_search_too_broad
```

A future batch adapter may increase/remove the bound only while preserving the same global ranking semantics.

## 12. Opaque `discoopt_v1` handoff

F2 does not expose a normal `aptopt_v1/v2` payload. The public token is:

```text
discoopt_v1.<cryptographically-random-secret>
```

Only a SHA-256 hash of the secret is persisted. Concrete selection state remains server-side in `DiscoveryBookingHandoff`, including:

```text
Organization
Publication id + observed revision
Mapping id + observed revision
OfferingVersion
Location
concrete Booking Resource/assignment selection
start/end
commercial/configuration observations
expiry
consumed Reservation provenance
```

The token therefore cannot be decoded to recover Resource ids, assignment ids, GlobalIdentity or SharedCapacityIdentity. Authoritative integrity comes from server-side relational state and transactional fences, not caller-controlled token contents.

`provider_visibility=hidden` therefore cannot leak concrete Resource identity through token inspection. `provider_visibility=public` does not currently authorize Resource private-field output because F2 has no accepted public Resource-profile projection.

## 13. Discovery-to-Booking transactional fence

A handoff is advisory until normal tenant Booking executes.

`appointments.book` still requires ordinary Booking capability, subject authority and tenant context. For `discoopt_v1`, Booking:

1. hashes/resolves the handoff under the caller Organization;
2. reconstructs the internal option from server-side state;
3. installs only the handoff UUID as task-local execution context;
4. enters the normal Booking transaction;
5. propagates the handoff UUID transaction-locally to PostgreSQL;
6. Reservation INSERT revalidates and locks the exact observed Mapping/Publication facts;
7. existing Booking/F1 logic revalidates OfferingVersion, schedule, terms, assignment, Resource and capacity;
8. the same transaction commits Reservation, CapacityClaim/commercial provenance and handoff consumption.

The following split protocol is forbidden:

```text
validate publication
COMMIT
book
COMMIT
```

Publication/mapping freshness and Booking commitment share the authoritative transaction boundary, closing the revoke/change TOCTOU window.

## 14. Handoff lifecycle and idempotency

A fresh handoff is short-lived and single-commit-use.

```text
same request + same Idempotency-Key
  -> safe semantic replay of the prior Reservation

same consumed handoff + different new mutation
  -> stale/unavailable
  -> no second Reservation or capacity mutation
```

The consumed Reservation reference is durable same-tenant provenance. Foreign tenants cannot resolve another tenant's handoff.

A handoff becomes stale without side effects if any material observed fact is no longer valid, including Publication revocation, Mapping replacement/revocation, newer current OfferingVersion, schedule/assignment/configuration/terms change or lost capacity.

## 15. Tenant semantic commands

F2 exposes semantic operations rather than CRUD:

```text
MapOfferingToServiceClassification
PublishDiscoverySupply
RevokeDiscoveryPublication
```

They require:

```text
trusted tenant ActorContext
operations.manage_discovery
valid Representation authority
Idempotency-Key
revision-aware semantics where applicable
immutable audit evidence
```

Foreign and nonexistent identifiers preserve existing opacity rules. Conflicting replay does not create partial durable state.

## 16. HTTP surfaces

### Platform Discovery

Separate composition root:

```text
Request Engine Discovery
POST /v1/discovery/supply/search
```

Search is read-only and does not require `Idempotency-Key`. It requires `discovery.search_supply`.

### Internal Booking availability

```text
POST /internal/v1/discovery/published-slots
```

This is a process-internal contract protected by the platform discovery capability boundary and backed by tenant-domain Booking authority unavailable to the public Discovery process.

### Tenant operations

Discovery mapping/publication mutations live under:

```text
/v1/operations/discovery/*
```

They use the normal operational authority/idempotency/error envelope.

## 17. Privacy and error semantics

Normal absence of supply returns an empty result. Unknown/retired classification, unmapped Offering, unpublished/revoked scope and foreign identifiers must not become existence oracles.

Search-contract and exhaustive-bound failures are explicit 422 outcomes. Candidate invalidation between search observation and handoff issuance omits that candidate rather than producing a 500.

If material state changes after handoff issuance but before Booking, Booking returns ordinary opaque stale/unavailable semantics and creates no Reservation, CapacityClaim, commercial commitment or outbox side effect.

Shared-capacity contention remains an opaque Booking conflict and must not reveal hidden shared-root identity.

## 18. Concurrency contract

F2 adversarial evidence must preserve these outcomes:

### R1 — publish vs publish

At most one conflicting/overlapping active publication wins; loser has deterministic rejection and no partial state.

### R2 — revoke vs discovery

A search may observe a publication before revoke, but a later commit must fail if the publication is no longer valid.

### R3 — revoke vs Booking

If revoke wins before the Booking revalidation/lock boundary, Booking cannot commit. If Booking already crossed the authoritative transaction boundary, later revoke cannot rewrite the Reservation.

### R4 — mapping replacement/revoke

Inactive or superseded mapping cannot authorize new commitment. Previously issued handoffs become stale.

### R5 — terms/schedule/assignment change

Normal F1 revalidation wins. Discovery never silently substitutes a different price, Resource, Location or schedule.

### R6 — shared physical capacity across tenants

Two Organizations may legitimately discover overlapping options backed by the same hidden physical shared-capacity root. Concurrent Booking is serialized by ADR 0011. At most one overlapping commitment wins, and neither Discovery output nor loser error exposes the shared root.

### R7 — concurrent mapping/publication configuration

First mapping and broad-vs-specific publication races serialize to one coherent durable result with monotonic provenance.

## 19. Schema and least-privilege contract

F2 authoritative schema includes at minimum:

```text
service_classifications
service_classification_authority_events
offering_service_classifications
discovery_publications
discovery_booking_handoffs
```

plus required audit/supersession/protected-function support.

Database enforcement includes:

```text
keys and same-tenant composite FKs
exact revision/lifecycle guards
monotonic revocation
publication overlap protection
RLS/FORCE RLS for tenant-owned relations
least-privilege runtime grants
protected candidate projection
protected handoff issue/read/commit fences
append-only audit/provenance where required
```

`request_engine_worker` receives no F2 tenant/configuration authority. `request_engine_app` cannot execute the cross-tenant candidate surface. `request_engine_discovery` receives no generic tenant-table authority.

## 20. Module ownership

`modules/discovery` owns:

```text
canonical classification integration
Offering classification mapping
publication
cross-tenant published-supply query/projection
opaque discovery handoff issuance
```

It does not own tenant operational truth, scheduling, Booking commitment or shared capacity.

Cross-module Python imports remain contracts-only. The public Discovery process cannot collapse the remote Booking trust boundary by injecting normal tenant persistence authority.

## 21. Compatibility posture

F2 preserves:

```text
existing tenant public API behavior
F1 operational/contextual-supply behavior
legacy aptopt_v1 compatibility
aptopt_v2 tenant Booking behavior
ADR 0011 shared-capacity opacity/serialization
V3 historical reproducibility
```

A tenant with no active F2 mapping/publication behaves as before and contributes no cross-tenant discovery results.

Because Request Engine remains pre-production with no customer-owned data, unreleased F2 development migrations were intentionally consolidated before integration. This does not rewrite released V3 `0001` or integrated F1 `0002/0003` history.

The production-facing F2 Alembic shape is:

```text
0001_initial
  -> 0002_operational_profile_contextual_supply
  -> 0003_f1_runtime_acl_completion
  -> 0004_geospatial_cross_tenant_discovery
```

The SQL-bearing provisional F2 steps 0004–0010 are preserved under `migrations/f2_steps/` as implementation provenance but are not independent Alembic revisions. The consolidated `0004` executes those proven steps in order.

## 22. Definition of Done

F2 integration requires exact-head evidence for:

```text
clean Alembic bootstrap to one F2 head
classification uniqueness/lifecycle
taxonomy least privilege and audit
same-tenant mapping integrity and monotonic replacement
publication same-tenant integrity
exact and mixed-scope publication non-overlap/concurrency
operations.manage_discovery authority
idempotent replay/conflicting replay
foreign-vs-nonexistent mutation opacity
unpublished/revoked invisibility
geo radius inclusive boundary
stable global search ordering
explicit too-broad behavior at candidate bound
two-or-more Organization discovery
current F1 schedule/terms composition
opaque discoopt_v1 provider privacy
foreign handoff opacity
Publication/Mapping/OfferingVersion stale fences
schedule/terms/assignment stale fences
safe replay of consumed handoff
new mutation cannot reuse consumed handoff
normal Booking commitment from discovery handoff
Reservation + CapacityClaim + commercial provenance + consumed handoff atomicity
shared-capacity race: one opaque serialized winner
public/operational legacy regression green
current-product proof green
frozen V3 compatibility/provenance green
```

The merge candidate must preserve rejected-operation non-mutation evidence and winner/loser/final-state evidence for races.

At the consolidation commit `a41afb6164cbc8c51125a68f27176827aebbee15`, CI run #1903 proved Python/architecture, repeated bootstrap, current-product PostgreSQL evidence, V2 history, observability, frozen V3 compatibility and the aggregate V3 candidate/vertical lane green. Final integration still requires exact-head CI after documentation closure.

## 23. Explicit non-goals

F2 does not implement:

```text
LLM-authoritative taxonomy mapping
vector/semantic marketplace search as authority
provider popularity/recommendation ranking
reviews/ratings ingestion
mobile ServiceArea polygons
route/travel-time optimization
insurance/network adjudication
coupons/dynamic pricing
capacity reservation during search
cross-tenant customer/Party directory
GlobalIdentity public lookup
identity merge/split
live queue/load projection
public Resource profile beyond an accepted future contract
```

## 24. Integration state

Implementation phases A–I are closed by code and adversarial evidence. Phase J is limited to documentation reconciliation, exact-head CI and PR readiness review.

`25-geospatial-cross-tenant-discovery-hardening.md` is retained as the adversarial-review rationale that produced the integrated rules above. Where wording differs, this document is authoritative.
