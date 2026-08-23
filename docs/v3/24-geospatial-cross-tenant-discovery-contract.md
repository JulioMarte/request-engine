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

Platform taxonomy lifecycle is available only through narrow `request_admin` functions. Create/retire actions require authority reference + reason and append immutable `service_classification_authority_events`. Tenant runtime may perform only narrow active-key lookup; it cannot enumerate or administer platform taxonomy.

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

Tenant operators configure it through the semantic operational command:

```text
SetResourcePublicProfile
PUT /v1/operations/discovery/resources/{resource_id}/public-profile
operations.manage_discovery
```

The operation is tenant-scoped, authority-checked, idempotent, optimistic-revision-aware and audited.

`provider_visibility=hidden` emits no concrete provider identity.

`provider_visibility=public` is valid only for a resource-specific publication and emits the provider projection only when an active `ResourcePublicProfile` exists. A missing public profile fails closed by making that public-provider candidate ineligible rather than falling back to private Resource fields.

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

## 9. Availability and ordering

F2 reuses Booking/F1 availability through `PublishedSlotReader`; it does not implement another scheduler.

F2 emits only slots with deterministic:

```text
Location
configuration fingerprint
planned duration
amount
currency
```

Global ordering is:

```text
1. earliest appointment start
2. distance_meters
3. stable Organization/Location/Offering/Resource/Publication tie-breakers
```

The current safe implementation evaluates every eligible candidate up to 200. Candidate 201 produces explicit `discovery_search_too_broad` rather than silently truncating before global ranking.

The current per-candidate HTTP slot evaluation is correctness-first. A future `BatchPublishedSlotReader` is permitted and desirable for latency, but it MUST preserve the same authority boundary, eligibility and global ordering semantics. Performance batching is not part of F2 merge correctness.

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
PublishDiscoverySupply
RevokeDiscoveryPublication
```

Current HTTP surface:

```text
PUT  /v1/operations/discovery/offerings/{offering_id}/classification
POST /v1/operations/discovery/offerings/{offering_id}/classification/revoke
PUT  /v1/operations/discovery/resources/{resource_id}/public-profile
POST /v1/operations/discovery/publications
POST /v1/operations/discovery/publications/{publication_id}/revoke
```

All require `operations.manage_discovery`, tenant opacity, idempotency and durable audit semantics.

Foreign and nonexistent targets MUST be semantically opaque. Rejected operations MUST leave authoritative state unchanged.

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

Required proof includes at least:

```text
cross-tenant search sees only explicitly published supply
revoked/unpublished supply is invisible
public projection contains approved where/provider fields only
hidden provider leaks no Resource identity
public provider requires explicit profile + public publication
request_engine_discovery is NOLOGIN/NOBYPASSRLS and narrow privilege only
request_engine_app cannot execute cross-tenant candidate authority
platform taxonomy create/retire authority + immutable audit
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

Natural-language service resolution and batch availability are legitimate follow-up improvements, but they are not allowed to weaken canonical classification, publication, privacy or commitment-time revalidation semantics.
