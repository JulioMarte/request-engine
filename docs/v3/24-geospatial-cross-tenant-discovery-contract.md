# Request Engine — F2 Geospatial Cross-Tenant Discovery Contract

Status: **normative F2 contract** for `feature/geospatial-cross-tenant-discovery`.

This document is the sole authoritative F2 product/architecture contract. `25-geospatial-cross-tenant-discovery-hardening.md` is historical adversarial-review provenance only and never overrides this document.

F2 extends the current post-V3 product without rewriting released V3 evidence. `Organization` remains the tenant boundary, Booking remains commitment authority, ADR 0011 remains authoritative for hidden shared-capacity serialization, and F1 remains authoritative for contextual schedule, assignment, commercial terms and Reservation provenance.

## 1. Product capability

F2 lets a platform-facing agent search explicitly published supply across participating Organizations and answer:

```text
what service is available?
where?
with whom, when provider publication permits it?
when?
at what deterministic price/duration?
```

Example public option:

```text
Dr. A
Clinic X
27 de Febrero 10, Puerto Plata
2.1 km
5:00 PM
DOP 3,500 / 45 min
```

The user chooses an option. F2 does not select a "best" provider and does not create a second booking/capacity system.

Initial search accepts a **canonical `ServiceClassification.classification_key`**. Natural-language resolution such as `cardiólogo` -> `cardiology` belongs to the agent/NLU layer or a later classification-resolution contract; it is not silently guessed by this transaction boundary.

## 2. Security and authority boundaries

```text
Organization
  = tenant security/administrative boundary

Platform Admin Authority
  = taxonomy/global administrative lifecycle

operations.manage_discovery
  = tenant-authorized discovery configuration

request_engine_discovery
  = narrow NOLOGIN/NOBYPASSRLS runtime grant role

Booking
  = authoritative Reservation/capacity commitment
```

Cross-tenant discovery MUST NOT receive `request_engine_admin`, generic RLS bypass, a normal tenant application SessionFactory, or arbitrary table authority.

`request_engine_discovery` may execute only the protected search/handoff functions required by F2. It receives no generic tenant table `SELECT/INSERT/UPDATE/DELETE` authority.

Platform taxonomy administration and its authority-event provenance are admin-only surfaces. `request_engine_app`, `request_engine_worker` and `request_engine_discovery` MUST NOT gain EXECUTE on the taxonomy create/retire functions or SELECT on `service_classification_authority_events` through later schema/default-privilege evolution.

Knowledge of a UUID, GlobalIdentity or SharedCapacityIdentity never grants discovery or tenant authority.

## 3. Explicit publication

Operational existence is not discovery authorization:

```text
exists operationally != published for cross-tenant discovery
```

A result is eligible only while all required authority state is current:

```text
active ServiceClassification
+ active Offering -> classification mapping
+ active/effective DiscoveryPublication
+ active Organization / Offering / Location
+ current bookable OfferingVersion
+ valid F1 contextual commercial supply
```

`DiscoveryPublication` is explicit, tenant-authorized, revocable and auditable. It references operational truth; it does not copy schedule, price or capacity.

One publication row has immutable provenance scope:

```text
Organization
Offering
Location
Resource/null scope
effective interval
provider_visibility
```

Visibility or scope changes require revoke + new publication. Revocation is monotonic.

Broad and resource-specific publications for the same Organization + Offering + Location MUST NOT overlap in time. PostgreSQL serializes that rule. Different resource-specific publications may coexist when otherwise valid.

`provider_visibility=public` without a concrete `resource_id` is semantically invalid input. The HTTP/control-plane boundary MUST reject it as a validation error before persistence; the PostgreSQL CHECK remains mandatory defense in depth and MUST NOT be weakened to make the API accept the invalid combination.

Revoked, inactive, expired, unmapped or unpublished supply is invisible to discovery.

## 4. Canonical service classification

`ServiceClassification` is platform taxonomy, not tenant-owned mutable vocabulary.

Tenant Offering mapping is explicit through `OfferingServiceClassification`.

Mapping replacement is monotonic provenance:

```text
lock Offering
revoke previous mapping
insert replacement mapping
append audit
```

The active mapping is at most one per Organization + Offering. Concurrent first-mapping attempts serialize through the Offering lock; the final durable state contains one active mapping and rejected contenders leave no partial durable effect.

Platform taxonomy lifecycle is available only through narrow `request_admin` functions. Create/retire actions require authority reference + reason and append immutable `service_classification_authority_events`. Tenant runtime may perform only narrow active-key lookup; it cannot enumerate or administer platform taxonomy. Exact-head evidence MUST prove the final deployed ACLs, not only the grants present when the functions were originally created.

## 5. Public Resource profile and provider visibility

F2 defines the minimal provider identity required by the original product north star:

```text
ResourcePublicProfile
  Resource
  public display name
  optional public role/title/specialty label
  optional public profile image/reference
  active
  revision
```

This profile is a deliberate public projection. It MUST NOT expose:

```text
GlobalIdentity
SharedCapacityIdentity
private Resource fields
capacity ownership internals
assignment identifiers
private contact details
```

Tenant operators configure its lifecycle through semantic operational commands:

```text
SetResourcePublicProfile
PUT /v1/operations/discovery/resources/{resource_id}/public-profile

DeactivateResourcePublicProfile
POST /v1/operations/discovery/resources/{resource_id}/public-profile/deactivate

operations.manage_discovery
```

Both operations are tenant-scoped, authority-checked, idempotent, optimistic-revision-aware and audited. Deactivation is an explicit revisioned state transition to `active=false`. A later `SetResourcePublicProfile` is the explicit update/reactivation path and advances revision again; the system MUST NOT silently resurrect a profile through discovery reads.

`provider_visibility=hidden` emits no concrete provider identity.

`provider_visibility=public` is valid only for a resource-specific publication and emits the provider projection only when an active `ResourcePublicProfile` exists. A missing or inactive public profile fails closed by making that public-provider candidate ineligible rather than falling back to private Resource fields.

## 6. Public Location projection

F1 Location remains the source of truth. F2 does not duplicate address data.

The approved public Location projection contains:

```text
location_key
display_name
address_line1?
address_line2?
locality?
administrative_area?
postal_code?
country_code?
```

Coordinates are used to compute distance but raw coordinates do not need to be returned by the initial F2 response.

Public contacts are not part of the initial F2 response. They may be added later only by an explicit publication/projection policy.

## 7. Public discovery response and data minimization

The public response contains only:

```text
organization_key
organization_display_name
offering_key
offering_display_name
location_key
location_display_name
location_address
provider?                  # only when explicitly public
distance_meters
start_at
end_at
planned_duration_minutes
amount
currency
option_id                  # discoopt_v1 opaque handoff
```

The following relational/internal identifiers MUST NOT cross the public F2 transport boundary merely for implementation convenience:

```text
organization_id
offering_id
offering_version_id
location_id
resource_id
assignment_id
GlobalIdentity
SharedCapacityIdentity
```

Those identifiers may remain server-side where required for joins, freshness fences and Booking commitment.

Public keys are the initial public identity contract. UUID knowledge never grants authority.

## 8. Geospatial contract

Search accepts:

```text
origin latitude/longitude
radius_meters
window_start/window_end
limit
```

The protected SQL function independently validates the search contract; HTTP validation alone is insufficient for a SECURITY DEFINER surface.

Distance uses the F2 great-circle calculation and clamps floating-point intermediate state before `sqrt/asin`.

Eligibility is inclusive:

```text
distance_meters <= radius_meters
```

Tests MUST attack inside, exact-boundary and first-outside behavior.

## 9. Availability, batching and ordering

F2 reuses Booking/F1 availability through `PublishedSlotReader`; it does not implement another scheduler.

The public Discovery process MUST cross into authoritative Booking availability through a remote process boundary. For one accepted F2 search, all candidate-specific `PublishedSlotQuery` observations MUST be sent through the batch contract rather than one HTTP request per candidate.

Current batch shape:

```text
Discovery
  <= 200 accepted candidates
  -> one find_published_slots_batch(...)
  -> one authenticated internal HTTP batch request
Booking availability gateway
  -> validate 1..200 query items
  -> evaluate each exact publication/mapping/version scope
  -> shared bounded concurrency across simultaneous batches
  -> aligned slot group for each input query
```

The remote decoder MUST fail closed if the batch payload is malformed or if the number of returned result groups does not equal the number of submitted queries. Result-group order is part of the internal contract so a slot group cannot silently bind to a different Discovery candidate.

Batching MUST NOT weaken the authority/freshness fence. Every batch item still revalidates its exact tenant Publication id/revision, Mapping id/revision, current/latest bookable OfferingVersion, Location and Resource/null scope before invoking tenant-local Booking availability.

The Booking gateway MUST bound database work across the gateway instance rather than granting each simultaneous search an independent concurrency budget. The current implementation uses a shared semaphore with a default ceiling of eight availability reads; the exact tuning value may evolve, but unbounded fan-out is not permitted.

F2 emits only slots with deterministic:

```text
Location
configuration fingerprint
planned duration
amount
currency
```

Global ordering is applied only after all accepted candidate result groups are flattened and filtered:

```text
1. earliest appointment start
2. distance_meters
3. stable Organization/Location/Offering/Resource/Publication tie-breakers
```

The implementation evaluates every eligible candidate up to 200. Candidate 201 produces explicit `discovery_search_too_broad` rather than silently truncating before global ranking.

Batching removes `O(N)` internal HTTP round trips but does not make database cost independent of candidate count. A future grouped/database-native availability implementation is permitted if it preserves the same tenant authority, publication/mapping/latest-version freshness, F1 Booking truth, complete global ordering, failure semantics and bounded resource usage.

## 10. Opaque discovery-to-booking handoff

Public options use:

```text
discoopt_v1.<cryptographically-random-secret>
```

Only the hash is stored. Server-side `DiscoveryBookingHandoff` retains the concrete internal selection and observed provenance:

```text
Organization
Publication id + revision
Mapping id + revision
OfferingVersion
Location
Resource selection
start/end
commercial/configuration observations
expiry
consumed Reservation provenance
```

The public token MUST NOT serialize Resource, assignment, shared-capacity or global-identity identifiers.

## 11. Commitment-time freshness

A discovery option is advisory until Booking commits it.

Within the authoritative Booking transaction, the system revalidates:

```text
Publication still active/current revision
Mapping still active/current revision
OfferingVersion still current/bookable
F1 Location schedule and exceptions
F1 Resource-at-Location assignment
F1 Resource/assignment availability exceptions
F1 contextual price/duration terms
capacity/shared-capacity ownership
normal subject/Booking authority
```

A stale option writes no Reservation, CapacityClaim, commercial commitment or other partial business outcome.

This fence MUST protect changes that occur after discovery and before Booking, including schedule closure, contextual terms change, assignment retirement, publication revocation, mapping replacement and newer OfferingVersion creation.

## 12. Consumption and idempotency

Fresh handoffs are short-lived and single-new-mutation-use.

```text
same HTTP command + same Idempotency-Key
  -> safe semantic replay of the committed Reservation

same consumed discoopt_v1 + different new mutation
  -> rejected
  -> no second Reservation or CapacityClaim
```

All tenant discovery configuration commands require `Idempotency-Key` and must reject conflicting reuse without a second durable effect/audit.

## 13. Operational command inventory

F2 tenant control-plane operations are:

```text
MapOfferingToServiceClassification
RevokeOfferingServiceClassification
SetResourcePublicProfile
DeactivateResourcePublicProfile
PublishDiscoverySupply
RevokeDiscoveryPublication
```

Current HTTP surface:

```text
PUT  /v1/operations/discovery/offerings/{offering_id}/classification
POST /v1/operations/discovery/offerings/{offering_id}/classification/revoke
PUT  /v1/operations/discovery/resources/{resource_id}/public-profile
POST /v1/operations/discovery/resources/{resource_id}/public-profile/deactivate
POST /v1/operations/discovery/publications
POST /v1/operations/discovery/publications/{publication_id}/revoke
```

All require `operations.manage_discovery`, tenant opacity, idempotency and durable audit semantics.

Foreign and nonexistent targets MUST be semantically opaque. Rejected operations MUST leave authoritative state unchanged.

Invalid cross-field publication intent such as `provider_visibility=public` with `resource_id=null` MUST be reported as a bounded input/semantic validation failure, not as `500 database_integrity_error`, and MUST leave no publication row.

## 14. Shared physical capacity

Discovery may expose supply from Organization A and Organization B even when both ultimately reference one hidden physical capacity root.

Discovery MUST NOT reveal that shared root.

If both tenants attempt the same physical capacity concurrently, authoritative Booking/shared-capacity serialization MUST produce at most one committed winner. The loser receives bounded opaque conflict semantics; no oversell or split ownership is allowed.

## 15. Migration posture

F2 is pre-production and is consolidated as one production Alembic revision:

```text
0004_geospatial_cross_tenant_discovery
```

Its development SQL-bearing steps remain under `migrations/f2_steps/` as implementation provenance executed by the consolidated revision. They are not separately deployed production migrations.

Released V3 `0001` and integrated F1 `0002/0003` remain unchanged.

Final F2 migration state MUST reassert the narrow taxonomy function and authority-event ACLs required by this contract so later grants/default privileges cannot make a previously narrow object broad at the actual deployed head.

## 16. Current guarantee inventory

The durable F2 guarantees are recorded in `docs/testing/current-guarantees.toml`, including:

```text
INV-DISCOVERY-PUBLICATION-001
INV-DISCOVERY-HANDOFF-001
INV-DISCOVERY-CONCURRENCY-001
```

Representative surviving proofs are mapped in `docs/testing/current-proof-map.toml`.

Removing/renaming tests is allowed only if the required evidence classes for these guarantees remain represented. The guarantee is frozen; incidental filenames are not.

## 17. Required merge evidence / Definition of Done

F2 is not merge-ready merely because general CI is green. Exact-head evidence MUST demonstrate the feature-specific contract.

The current-product gate MUST execute the F2 PostgreSQL proof ownership set, including candidate/handoff fences, privileges, public projection, publication concurrency, exact radius behavior and taxonomy lifecycle. A test file that exists but is not executed is not merge evidence.

Required proof includes at least:

```text
cross-tenant search sees only explicitly published supply
revoked/unpublished supply is invisible
public projection contains approved where/provider fields only
production-like HTTP discovery returns public provider + address and books that option
hidden provider leaks no Resource identity
public provider requires explicit profile + public publication
public + resource_id=null -> validation failure, not 500, with no durable mutation
ResourcePublicProfile set/deactivate lifecycle is revisioned, idempotent and audited
request_engine_discovery is NOLOGIN/NOBYPASSRLS and narrow privilege only
request_engine_app cannot execute cross-tenant candidate authority
platform taxonomy create/retire authority + immutable audit
final deployed taxonomy function/authority-event ACLs exclude app/worker/discovery runtime roles
mapping lifecycle and revoke command
publication lifecycle and revoke command
operations.manage_discovery authority failure leaves no partial state
idempotent replay has one durable effect/audit
conflicting replay is rejected without mutation
foreign and nonexistent mutation targets are opaque
mapping concurrent-first race: winner/loser/final state
broad-vs-resource-specific publication race: winner/loser/final state
inclusive geo boundary: inside/exact/outside
complete global ordering and deterministic tie-break
201st candidate -> explicit too-broad failure
multiple candidates -> one remote availability batch request
batch response cardinality mismatch -> fail closed
simultaneous batches -> shared bounded Booking availability concurrency
Publication stale fence
Mapping stale fence
OfferingVersion stale fence
F1 schedule stale through discoopt_v1
F1 contextual terms stale through discoopt_v1
F1 assignment stale through discoopt_v1
safe consumed-handoff idempotent replay
same consumed handoff + new mutation rejected
cross-tenant Discovery -> Booking -> Reservation happy path
shared physical capacity race across tenants: exactly one commitment
rejected operations inspect final durable state, not response code alone
```

The exact-head CI run used for merge readiness must run the repository's current quality, migration, PostgreSQL, integration and E2E gates. Previous-head green runs are provenance only.

## 18. Explicit non-goals

F2 does not add:

```text
a universal recommendation/ranking engine
a second scheduler or capacity ledger
live queue/ETA prediction (F3/F4)
a CRM/CMS/EHR
a global open tenant catalog
public shared-capacity/global-identity disclosure
a natural-language taxonomy mutation API
```

Natural-language service resolution and deeper grouped/database-native availability are legitimate follow-up improvements, but they are not allowed to weaken canonical classification, publication, privacy, bounded resource usage or commitment-time revalidation semantics.
