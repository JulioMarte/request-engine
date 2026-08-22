# Request Engine — F2 Geospatial Cross-Tenant Discovery Contract

Status: normative post-V3 delta for `feature/geospatial-cross-tenant-discovery`.

This contract defines F2 semantics. It supersedes only the F2 ambiguities left open by `14-operational-intelligence-roadmap.md` and `16-operational-profile-contextual-supply-clarifications.md`. It does not rewrite released V3 history, ADR 0011 shared-capacity privacy, or the accepted F1 operational/contextual-supply contract.

## 1. Product capability

F2 adds one platform-facing capability:

```text
discovery.search_supply
```

It searches concrete currently valid supply across Organizations that explicitly opted into platform discovery.

Representative intent:

```text
service classification = cardiology
origin = lat/lon
radius = 10 km
window = today around 17:00
```

Representative result:

```text
Organization public identity
Location public identity
Offering public identity
optional public Resource/provider identity
distance_meters
one or more currently valid appointment options
deterministic current commercial terms
```

The result is advisory. It does not consume capacity.

## 2. Hard boundaries

### F2-C01 — tenant ownership remains intact

`Organization` remains the security/administrative owner of Location, Offering, Resource and booking state.

Publication grants only the narrow discovery projection defined here.

### F2-C02 — shared capacity is not discovery authority

`GlobalIdentity`, `SharedCapacityIdentity`, bindings and claim links remain private. Their identifiers and evidence never appear in F2 results.

### F2-C03 — existence is not publication

No tenant operational row becomes discoverable merely because it exists or is public inside that tenant's own API.

### F2-C04 — no generic cross-tenant database read

F2 must not use `request_engine_admin`, `BYPASSRLS`, generic SELECT grants or arbitrary SQL to search tenant state.

A purpose-built protected read function/projection may read across tenants only to produce the exact published discovery projection.

### F2-C05 — Booking remains authoritative

Discovery never creates or updates `CapacityClaim`, Reservation, CapacityHold or shared-capacity provenance.

Normal Booking revalidation remains the commitment boundary.

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

`classification_key` is stable, unique and machine-facing.

Examples:

```text
cardiology
dermatology
general_dentistry
commercial_refrigeration_repair
```

It is not a tenant Offering and carries no price, schedule or capacity truth.

### 3.2 OfferingServiceClassification

An Organization explicitly maps a tenant `Offering` to a canonical classification.

Initial cardinality:

```text
one active Offering -> one active primary ServiceClassification
```

F2 does not implement multi-label ontology graphs, synonym inference, hierarchical inheritance or probabilistic classification as authoritative state.

If later evidence requires multiple classifications per Offering, that is a deliberate contract extension.

### 3.3 Mapping authority

Tenant mapping mutation requires exact operational authority:

```text
operations.manage_discovery
```

A mapping command is idempotent, audited and revision-aware.

Fuzzy text, embeddings or an LLM may generate a proposed classification, but authoritative mapping is created only by the semantic command.

## 4. DiscoveryPublication

### 4.1 Meaning

A publication states:

> this tenant authorizes this service/location supply scope to participate in platform discovery during this effective period.

It is not a cache or copy of Booking truth.

### 4.2 Initial scope

A publication owns these references:

```text
organization_id
offering_id
location_id
resource_id?   # optional
```

plus lifecycle/provenance:

```text
effective_during
status          active | revoked
provider_visibility
revision
authority/audit provenance
created_at
updated_at
```

`provider_visibility` initial values:

```text
hidden
public
```

If `resource_id` is NULL, Booking may resolve any eligible Resource for the published Offering + Location.

If `resource_id` is present, the Resource must belong to the same Organization and have a valid Resource-at-Location path for the published Location when contextual supply applies.

### 4.3 No duplicated operational fields

Publication must not persist copies of:

```text
price
currency
planned duration
weekly hours
schedule exceptions
appointment slots
capacity state
address
coordinates
provider display name
Offering display name
```

Those values are resolved from their authoritative owners when producing discovery results.

### 4.4 Effective dating and overlap

Active publications for the same exact scope must not have ambiguous overlapping effective intervals.

Exact scope identity is:

```text
organization_id + offering_id + location_id + resource_id/null
```

The database must reject overlapping active/effective publication rows for that exact scope.

### 4.5 Revocation

Revocation is monotonic for the publication row and advances revision.

A revoked publication cannot be reactivated. A later re-publication creates a new publication row/provenance.

Revocation:

```text
prevents new discovery results
invalidates not-yet-booked discovery options at Booking revalidation
never cancels/reprices/rewrites an existing Reservation
```

## 5. Platform discovery authority

### 5.1 Actor model

F2 introduces a platform-facing authenticated actor distinct from tenant `ActorContext`.

Conceptually:

```text
PlatformDiscoveryActor
  principal_id
  capabilities
  principal_kind
  authentication_method
  correlation_id
  credential_id?
```

It does not contain a caller-selected Organization because the query is intentionally cross-tenant.

### 5.2 Capability

The actor must hold:

```text
discovery.search_supply
```

Knowledge of tenant ids, publication ids, Offering ids, Resource ids or global identity ids does not satisfy that capability.

### 5.3 Database surface

The runtime calls a narrow protected SQL surface that returns only eligible published candidates.

The protected surface must not expose generic relation access and must never return:

```text
Party/customer/patient ids
Reservation ids
CapacityClaim ids
SharedCapacityIdentity ids
GlobalIdentity ids
Representation rows
private authority/audit evidence
unpublished Organizations/Locations/Offerings/Resources
```

## 6. Query contract

Initial `SearchPublishedSupplyQuery` fields:

```text
service_classification_key: str
origin_latitude: Decimal
origin_longitude: Decimal
radius_meters: int
window_start: datetime
window_end: datetime
limit: int
```

Optional future filters are not accepted until explicitly contracted.

### 6.1 Validation

```text
-90 <= latitude <= 90
-180 <= longitude <= 180
0 < radius_meters <= configured hard maximum
window_start/window_end timezone-aware
window_end > window_start
bounded maximum search window
1 <= limit <= configured maximum
```

The initial implementation constants must be explicit and tested rather than hidden in SQL.

Recommended initial limits:

```text
radius <= 100_000 meters
window <= 7 days
limit <= 100 discovery options
```

Changing these values later is an operational/API policy change, not a schema change.

## 7. Candidate eligibility

A row may enter candidate evaluation only when all are true at query time:

```text
ServiceClassification active
Offering mapping active
DiscoveryPublication active and effective
Organization operationally active
Offering active
selected/current OfferingVersion bookable
Location active
Location has coordinates
Location inside requested radius
publication Offering/Location ownership coherent
optional Resource ownership coherent
```

Candidate publication does not prove there is an appointment slot. Booking availability must still be evaluated.

## 8. Geospatial semantics

Distance is objective derived data.

Initial algorithm:

```text
great-circle/Haversine-equivalent distance over F1 latitude/longitude
```

Contract result:

```text
distance_meters >= 0
```

Radius inclusion rule:

```text
distance_meters <= radius_meters
```

Boundary is inclusive.

Ordering:

```text
1. earliest appointment start
2. distance_meters
3. stable Organization/Location/Offering/Resource ids
```

Distance does not change price, eligibility, capacity or booking priority.

PostGIS may replace the physical calculation later without changing these semantics.

## 9. Availability composition

F2 must reuse current Booking slot semantics rather than implement a second scheduler.

Conceptually:

```text
published candidate scope
      ↓
tenant Booking FindAppointmentSlots semantics
      ↓
filter to published Location
      ↓
if resource_id published, filter to that Resource
      ↓
produce DiscoveryOption
```

The implementation may optimize this through a batch/projection adapter, but optimization must remain behaviorally equivalent to the authoritative Booking slot semantics that apply to the same tenant/context.

## 10. Commercial terms

Discovery returns the deterministic terms that apply to the concrete option according to F1 resolution:

```text
exact Resource + Location + OfferingVersion contextual terms
>
OfferingVersion base terms
>
missing required term => option not discoverable/bookable
```

Discovery does not create special marketplace pricing.

A later external reputation/promotion layer cannot alter authoritative price unless a separate accepted pricing contract exists.

## 11. Provider identity visibility

If publication has:

```text
provider_visibility = hidden
```

F2 must not expose Resource identity/name even if Booking internally selected a Resource.

If:

```text
provider_visibility = public
```

and publication references a specific Resource, F2 may return only the Resource public fields explicitly approved by the F2 projection contract.

F2 does not expose `GlobalIdentity` or use shared-capacity identity as the public provider identifier.

Initial public provider projection should be minimal. If there is no existing supported Resource public-profile field, F2 must not invent a private-field leak merely to display a doctor name; that presentation requirement must be added through an explicit public Resource profile contract.

## 12. Discovery option token / stale semantics

A discovery result must carry enough signed/versioned observations to reject stale commitment without trusting caller-supplied tenant state.

Initial approach:

```text
DiscoveryOption
  publication_id
  publication_revision
  organization_id
  offering_version_id
  location_id
  resource_id? / booking option reference
  appointment option token
  observed terms/publication metadata needed for revalidation
```

The outer discovery token must be integrity protected or contain an integrity-protected nested Booking option such that the client cannot rewrite tenant/Offering/Location/Resource coordinates.

At Booking:

```text
publication still active/effective?
classification mapping still active?
normal aptopt_v2/current Booking option still valid?
current schedule/terms/capacity valid?
```

Any material failure returns ordinary stale/unavailable semantics; foreign/private metadata is not disclosed.

## 13. Booking handoff

The platform does not acquire generic tenant mutation authority simply because it performed discovery.

After the user chooses a discovery option, Booking still requires the normal subject/tenant authorization appropriate to `appointments.book`.

Deployment/orchestration may resolve the selected Organization and route the booking request into that tenant's normal Booking capability, but the discovery actor itself is not automatically a subject-authorized booking actor.

## 14. Tenant publication commands

F2 must expose semantic commands, not CRUD endpoints:

```text
MapOfferingToServiceClassification
PublishDiscoverySupply
RevokeDiscoveryPublication
```

All require:

```text
operations.manage_discovery
```

All commands require:

```text
trusted tenant ActorContext
exact Representation authority
Idempotency-Key
immutable audit event
```

Revision expectations:

```text
mapping replacement/revocation -> expected mapping revision
publication revocation -> expected publication revision
```

Creation conflicts are deterministic and do not create duplicate durable effects.

## 15. Taxonomy administration

ServiceClassification vocabulary is platform-owned, not tenant-owned.

F2 may initially expose its mutation only through trusted administrative/database control-plane functions rather than the tenant operational HTTP app.

Required semantics if implemented in this feature:

```text
CreateServiceClassification
RetireServiceClassification
```

Retirement prevents new/active mappings from using the classification but does not rewrite historical mapping/publication/audit provenance.

Tenant operators cannot create arbitrary platform taxonomy keys through `operations.manage_discovery`.

## 16. Privacy and opacity

The following probes must not become foreign-row existence oracles:

```text
unknown classification key
retired classification
unmapped Offering
unpublished Offering/Location/Resource
revoked publication
foreign publication id
```

The public discovery search simply omits ineligible/unpublished rows.

Tenant mutation endpoints must preserve the repository's existing foreign-vs-nonexistent opacity rules.

## 17. Concurrency / race semantics

F2 must prove at least:

### R1 — publish vs publish same scope

At most one valid overlapping active publication wins. The loser receives deterministic conflict and no partial audit/publication state.

### R2 — revoke vs discovery

A query that observes publication before concurrent revoke may return an advisory option, but later Booking revalidation must reject it if publication is no longer active/effective.

### R3 — revoke vs Booking

Publication is revalidated before capacity commitment. If revoke wins before that revalidation/lock boundary, Booking does not commit. If Booking has already crossed its authoritative commit boundary, later revoke cannot rewrite the Reservation.

### R4 — mapping revoke/change vs discovery

New discovery must not use an inactive mapping. Previously issued options are stale at Booking if the mapping is no longer valid under the F2 handoff contract.

### R5 — terms/schedule/assignment change after discovery

Normal F1 Booking revalidation wins; stale option never silently substitutes a new price/resource/location.

### R6 — shared physical capacity across tenants

Two F2 options can legitimately be discovered for the same physical shared Resource before either commits. Concurrent Booking remains serialized by ADR 0011 hidden shared roots; at most one overlapping commitment wins.

F2 must not attempt to reserve capacity during discovery merely to avoid this normal optimistic race.

## 18. HTTP surfaces

F2 has two separate transport surfaces.

### 18.1 Platform discovery API

A separate composition root is preferred:

```text
Request Engine Discovery
```

Initial endpoint:

```text
GET or POST /v1/discovery/supply/search
```

A POST search body is acceptable because the query contains structured time/geo parameters and is not a mutation; it must not require Idempotency-Key.

It requires `discovery.search_supply` on a PlatformDiscoveryActor.

### 18.2 Tenant operational API

Tenant operators manage mapping/publication under:

```text
/v1/operations/discovery/*
```

These mutations keep the normal operational-app authority/idempotency/error envelope.

## 19. Error boundary

Platform search errors:

```text
401 authentication_required
403 capability_required
422 invalid search contract
```

Normal absence of supply returns an empty result, not 404 and not a tenant existence signal.

Tenant configuration errors reuse the operational envelope:

```text
403 operational_authority_required
409 stale/conflicting semantic intent
422 invalid semantic input
```

Booking failures remain Booking errors, especially opaque `appointment_unavailable` for local/shared contention.

## 20. Schema requirements

F2 append-only migration must create at minimum:

```text
service_classifications
offering_service_classifications
discovery_publications
```

plus:

```text
keys/check constraints
same-tenant composite FKs
revision/lifecycle constraints
non-overlap protection
RLS for tenant-owned mapping/publication rows
least-privilege grants
protected cross-tenant discovery read function
immutable/auditable command support
```

`service_classifications` are platform-owned and not exposed through tenant RLS enumeration by ordinary app/worker roles except through the narrow classification lookup required for authorized mapping/search.

## 21. Module contract

New post-V3 module:

```text
modules/discovery
```

Owns:

```text
classification
Offering mapping
publication
published-supply query/projection
```

Does not own source operational truth.

Cross-module Python imports are contracts-only.

## 22. Compatibility

F2 must preserve:

```text
existing tenant public API behavior
F1 operator configuration behavior
aptopt_v1 compatibility
aptopt_v2 contextual Booking behavior
shared-capacity opacity/serialization
V3 historical reproducibility
current append-only Alembic history
```

A tenant that creates no F2 mappings/publications behaves exactly as before and contributes zero rows to cross-tenant discovery.

## 23. Required evidence / Definition of Done

F2 is not merge-ready until exact-head evidence proves:

```text
clean database bootstrap 0001 -> 0002 -> 0003 -> F2 head
upgrade from current development Alembic head
classification uniqueness/lifecycle
same-tenant mapping integrity
publication same-tenant integrity
publication non-overlap/concurrency
operations.manage_discovery authority
idempotent replay/conflicting replay
foreign-vs-nonexistent mutation opacity
unpublished tenant invisibility
revoked publication invisibility
geo radius inclusive boundary
stable search ordering
cross-tenant results from two or more Organizations
current F1 terms/schedule composition
provider hidden/public projection behavior
revoke/mapping/terms/schedule stale handoff
normal Booking commitment after selected discovery option
shared-capacity race remains opaque and serialized
no direct app/worker enumeration of private tenant/global state
public/operational legacy regression green
current-product proof green
frozen V3 compatibility/provenance green
```

Evidence must inspect durable state/non-state for rejected mutations and winner/loser/final state for races.

## 24. Explicit non-goals

F2 does not implement:

```text
LLM-authoritative taxonomy mapping
semantic-vector marketplace search as authority
provider popularity/recommendation model
Google reviews/ratings ingestion
mobile ServiceArea polygons
route/travel-time optimization
insurance/network adjudication
coupons/dynamic pricing
capacity reservation during search
cross-tenant customer/Party directory
GlobalIdentity public lookup
identity merge/split
live queue/load projection (F3/F4)
```

## 25. Implementation sequence

```text
A current-state inventory                 CLOSED by doc 23
B normative contract                      CLOSED by this document
C schema / privileges / protected read    next
D semantic configuration commands
E discovery query projection
F platform + operator HTTP surfaces
G discovery -> Booking handoff
H adversarial races/privacy
I current test architecture integration
J docs/exact-head closure
```

SQL is subordinate to this contract. If implementation evidence reveals that a rule here is unsafe or incomplete, change the contract explicitly before silently changing semantics in SQL.