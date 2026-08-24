# Request Engine — F2 Geospatial Cross-Tenant Discovery Plan

Status: **implementation/closure plan** for `feature/geospatial-cross-tenant-discovery`; architecture and closure work are implemented, and merge readiness is determined only by the required CI checks on the current PR head.

This plan records how F2 is delivered against the current post-F1 architecture. The normative behavior is owned by `24-geospatial-cross-tenant-discovery-contract.md`. If this plan and document 24 conflict, document 24 wins.

## 1. Mission

F2 allows a platform-facing caller to discover concrete, currently valid, explicitly published operational supply across multiple Organizations without generic cross-tenant read authority.

Representative answer:

```text
Dr. A
Clinic X
public address
2.1 km
5:00 PM
DOP 3,500 / 45 min
opaque discoopt_v1
```

The user/application chooses. F2 is an explicit publication projection over F1/Booking truth, not a second scheduler, capacity ledger or autonomous recommendation engine.

## 2. Authoritative references

1. `24-geospatial-cross-tenant-discovery-contract.md` — normative F2 contract.
2. `15-operational-profile-contextual-supply-contract.md` — F1 operational/contextual truth reused by F2.
3. `14-operational-intelligence-roadmap.md` — product direction/status across F1-F6.
4. ADR 0011 / `12-cross-tenant-shared-capacity-design.md` — hidden cross-tenant shared-capacity serialization.
5. `architecture/pre-production-evolution-policy.md` — current evolution/evidence policy.
6. `testing/current-guarantees.toml` — normative current guarantee inventory.
7. `testing/current-proof-map.toml` — representative proof mapping.

Precedence:

```text
24 F2 normative contract
  >
22 F2 implementation/closure plan
  >
14 roadmap
  >
F1/V3 where F2 explicitly extends behavior
```

Document 25 is historical review provenance only.

## 3. Phase A — current-state inventory

Status: **closed**.

`23-geospatial-cross-tenant-discovery-current-state-inventory.md` records the pre-F2 old -> new disposition.

Key outcomes:

```text
REUSE Organization tenant boundary
REUSE F1 Location address/coordinates/hours
REUSE F1 Resource-at-Location/contextual supply
REUSE Booking availability and commitment
REUSE shared-capacity serialization without public identity leakage
NEW ServiceClassification
NEW OfferingServiceClassification
NEW DiscoveryPublication
NEW dedicated request_engine_discovery runtime authority
NEW opaque DiscoveryBookingHandoff / discoopt_v1
NEW minimal ResourcePublicProfile for deliberately public providers
```

## 4. Phase B — normative contract

Status: **closed**.

Document 24 defines:

- explicit publication;
- canonical service classification;
- public provider profile lifecycle and visibility semantics;
- public Location address projection;
- approved public DTO/data minimization;
- geospatial boundary semantics;
- global ordering;
- dedicated discovery runtime authority;
- opaque handoff;
- commitment-time freshness;
- configuration command inventory;
- shared-capacity safety;
- required adversarial evidence.

Natural-language service resolution is explicitly separated from the canonical transaction boundary.

## 5. Phase C — schema and privilege model

Status: **closed in implementation; current-head migration proof is part of the merge gate**.

F2 production schema is consolidated under:

```text
migrations/versions/0004_geospatial_cross_tenant_discovery.py
```

The development SQL-bearing steps are retained under `migrations/f2_steps/` and executed by that consolidated revision.

Core persisted concepts:

```text
ServiceClassification
ServiceClassificationAuthorityEvent
OfferingServiceClassification
DiscoveryPublication
ResourcePublicProfile
DiscoveryBookingHandoff
```

Privilege rules:

```text
request_engine_discovery
  NOLOGIN
  NOBYPASSRLS
  narrow EXECUTE only

request_engine_app / request_engine_worker / request_engine_discovery
  no platform taxonomy administration
  no read authority over taxonomy authority-event provenance

request_engine_app
  no global taxonomy enumeration
  no cross-tenant candidate authority

request_engine_admin
  narrow platform taxonomy lifecycle and authority provenance
```

The consolidated F2 head reasserts taxonomy function/table ACLs so the deployed final state, rather than only the original object-creation point, proves least privilege.

## 6. Phase D — tenant discovery control plane

Status: **closed in implementation; current-head E2E proof is part of the merge gate**.

Supported semantic operations:

```text
MapOfferingToServiceClassification
RevokeOfferingServiceClassification
SetResourcePublicProfile
DeactivateResourcePublicProfile
PublishDiscoverySupply
RevokeDiscoveryPublication
```

HTTP surface:

```text
PUT  /v1/operations/discovery/offerings/{offering_id}/classification
POST /v1/operations/discovery/offerings/{offering_id}/classification/revoke
PUT  /v1/operations/discovery/resources/{resource_id}/public-profile
POST /v1/operations/discovery/resources/{resource_id}/public-profile/deactivate
POST /v1/operations/discovery/publications
POST /v1/operations/discovery/publications/{publication_id}/revoke
```

All require:

```text
operations.manage_discovery
Idempotency-Key
explicit authority_party_id
foreign/nonexistent target opacity
bounded stale/revision semantics
audit
no partial durable state on rejection
```

`ResourcePublicProfile` now has an explicit deactivate lifecycle. Deactivation is revisioned, idempotent and audited; setting the profile again is the explicit reactivation/update path.

A publication request with `provider_visibility=public` and no `resource_id` is rejected at the semantic/API boundary with HTTP 422 and no durable publication. The PostgreSQL CHECK remains in place as defense in depth.

F2-specific E2E proofs exercise these semantics directly; generic Organization/Location tests are not counted as F2 authority/idempotency evidence.

## 7. Phase E — public cross-tenant discovery

Status: **closed in implementation; current-head proof is part of the merge gate**.

Search uses:

```text
canonical classification key
origin lat/long
radius_meters
window
bounded result limit
```

The public response is minimized to public keys/display projections, approved Location address, optional public provider projection, objective distance, appointment/commercial facts and `discoopt_v1`.

Internal relational UUIDs remain server-side for joins/freshness but are not emitted by the public DTO.

`provider_visibility=public` has visible product semantics: it requires resource-specific publication plus an active `ResourcePublicProfile` and emits only approved public provider fields.

The production-like cross-tenant E2E journey proves the complete north-star chain in one flow: two Organizations are discoverable, the public provider and public Location address are returned through the real discovery HTTP endpoint, internal UUIDs remain absent, and the selected `discoopt_v1` commits the expected Reservation/capacity/commercial provenance.

Availability evaluation is batched across the process boundary. `search_published_supply()` prepares all accepted candidate observations and invokes one `PublishedSlotReader.find_published_slots_batch(...)`; the remote adapter emits one internal HTTP request containing up to the same 200-candidate safety bound. Booking still evaluates every item under authoritative tenant context.

## 8. Phase F — Booking handoff and freshness

Status: **closed in implementation; current-head proof is part of the merge gate**.

`discoopt_v1` is opaque. Server-side handoff state records the exact internal selection/provenance.

Booking revalidates in the authoritative transaction:

```text
Publication
Mapping
current OfferingVersion
F1 Location schedule/exceptions
F1 assignment/availability
F1 contextual price/duration
capacity/shared capacity
normal Booking/subject authority
```

Direct F2 tests attack post-discovery changes to schedule, contextual terms and assignment before Booking.

Consumption semantics are also directly proven:

```text
same command + same Idempotency-Key -> safe replay
same consumed option + different mutation -> rejected, no second commitment
```

## 9. Phase G — adversarial concurrency

Status: **closed in test design/implementation; current-head execution is part of the merge gate**.

Required races include:

```text
concurrent first mapping
  -> one accepted active mapping
  -> loser conflict
  -> one durable audit effect

broad vs resource-specific publication
  -> synchronized PostgreSQL race
  -> exactly one committed publication
  -> rejected loser leaves no partial row

cross-tenant shared physical capacity
  -> both discover
  -> concurrent Booking
  -> exactly one Reservation/claim winner
  -> loser learns no shared root
```

Availability batching has a separate operational concurrency fence: one Booking gateway instance owns a shared bounded semaphore, so concurrent discovery requests do not each receive an independent database-concurrency budget.

## 10. Phase H — boundary and negative proofs

Status: **closed in test implementation; all F2 PostgreSQL proofs are owned by the current-product gate**.

Feature-specific evidence covers:

```text
request_engine_discovery least privilege
request_engine_app cross-tenant function denial
taxonomy admin lifecycle + immutable audit + final-head ACLs
revoked publication invisibility
hidden provider privacy
public provider/address projection
public DTO UUID minimization
invalid public publication rejected as 422 with no mutation
public profile set/deactivate lifecycle and audit
inclusive radius inside/exact/outside
201st candidate too-broad failure
one remote availability batch for multiple candidates
malformed/misaligned batch response rejected
bounded availability concurrency shared across simultaneous batches
Publication stale fence
Mapping stale fence
OfferingVersion stale fence
F1 schedule/terms/assignment stale through discoopt_v1
foreign/unknown operation opacity
conflicting idempotency replay
rejected operation durable-state inspection
```

`scripts/ci/run_current_product.sh` runs `tests/db/test_f2_*.py`, so public projection, publication concurrency, exact radius boundary, taxonomy lifecycle and future F2 DB proofs matching that ownership convention cannot silently exist outside the exact-head current-product gate.

## 11. Phase I — guarantee inventory

Status: **closed**.

F2 durable guarantees are represented in `docs/testing/current-guarantees.toml`:

```text
INV-DISCOVERY-PUBLICATION-001
INV-DISCOVERY-HANDOFF-001
INV-DISCOVERY-CONCURRENCY-001
```

Representative F2 proofs are mapped in `docs/testing/current-proof-map.toml`, including public projection, handoff freshness/consumption, configuration races, authority/idempotency, privileges and shared-capacity race evidence.

## 12. Phase J — documentation reconciliation

Status: **closed in branch content; governance tests remain part of the current-head CI gate**.

Reconciled documents include:

- `docs/README.md` — F2 is active/current, not future-only;
- roadmap 14 — F1 implemented, F2 implemented on PR #77, F3-F6 future;
- contract 24 — sole normative F2 contract;
- hardening 25 — historical provenance, no precedence contradiction;
- this plan — current closure state;
- Discovery module README — batching/process-boundary behavior;
- command inventory — includes mapping revoke plus public Resource profile set/deactivate lifecycle.

## 13. Availability batching implemented; residual performance debt

The original per-candidate remote fan-out is closed.

Current shape:

```text
Discovery search
  -> <= 200 accepted candidates
  -> one PublishedSlotReader batch call
  -> one internal HTTP request
  -> Booking gateway
  -> shared process-wide bounded concurrency (default 8 reads)
  -> publication-fenced tenant-local Booking availability
  -> aligned result groups
  -> unchanged global sort
```

This removes `O(N)` internal HTTP round trips and prevents one search, or many simultaneous searches, from opening an unbounded number of availability reads.

It deliberately does **not** collapse all candidate availability into one cross-tenant SQL query. Each candidate still passes the existing publication/mapping/latest-version fence and normal tenant-local Booking availability path. That residual per-candidate database work is preferable to weakening RLS/authority boundaries merely for speed.

A future grouped/database-native optimization may reduce database round trips further only if it proves the same:

```text
discovery authority boundary
F1 Booking truth
publication/mapping/latest-version freshness
eligibility
complete global ordering
stale handoff semantics
bounded resource consumption
```

The endpoint can now be described as having bounded batched remote availability, but not as having constant-cost availability independent of candidate count.

## 14. Definition of Done

PR #77 is merge-ready only when the current branch head has fresh successful evidence for the repository's required gates and the F2-specific proofs listed by contract 24.

Checklist:

```text
[implemented] original product can answer where + with whom when provider is public
[implemented] explicit publication + revoke
[implemented] canonical classification + mapping/revoke
[implemented] public provider profile set/deactivate lifecycle
[implemented] invalid public publication fails as semantic/API validation, not database 500
[implemented] public Location address projection
[implemented] data-minimized public DTO
[implemented] dedicated discovery runtime role
[implemented] final-head taxonomy authority ACL hardening
[implemented] opaque discoopt_v1
[implemented] stale-safe Booking handoff
[implemented] shared-capacity safety
[implemented] one remote availability batch per discovery search
[implemented] batch request is bounded to the F2 candidate ceiling
[implemented] Booking availability concurrency is shared/bounded across simultaneous batches
[implemented] F2-specific authority/idempotency/opacity tests
[implemented] all tests/db/test_f2_*.py are in the current-product CI gate
[implemented] mapping/publication race tests
[implemented] exact geo boundary test
[implemented] production-like provider + address + discovery + Booking E2E
[implemented] schedule/terms/assignment stale tests
[implemented] consumed handoff replay/new-mutation proof
[implemented] taxonomy lifecycle/audit/final ACL proof
[implemented] current guarantee inventory + proof map
[implemented] README/roadmap/contract/hardening reconciliation
[current-head gate] merge only when the GitHub CI checks for the actual PR head are green
```

A green run from an earlier SHA is provenance only and does not close merge readiness. This document deliberately does not hard-code a SHA or workflow run: changing closure documentation creates a new head, so the authoritative merge evidence is the GitHub check suite attached to the actual PR head.