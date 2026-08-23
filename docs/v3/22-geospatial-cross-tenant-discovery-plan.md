# Request Engine — F2 Geospatial Cross-Tenant Discovery Plan

Status: **implementation/closure plan** for `feature/geospatial-cross-tenant-discovery`; architecture implemented, exact-head merge evidence remains the final closure gate.

This plan records how F2 is delivered against the current post-F1 architecture. The normative behavior is now owned by `24-geospatial-cross-tenant-discovery-contract.md`. If this plan and document 24 conflict, document 24 wins.

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

Document 24 now defines:

- explicit publication;
- canonical service classification;
- public provider profile semantics;
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

Status: **closed in implementation; exact-head migration proof required**.

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

request_engine_app
  no global taxonomy enumeration
  no cross-tenant candidate authority

request_engine_admin
  narrow platform taxonomy lifecycle
```

## 6. Phase D — tenant discovery control plane

Status: **closed in implementation; exact-head E2E proof required**.

Supported semantic operations:

```text
MapOfferingToServiceClassification
RevokeOfferingServiceClassification
SetResourcePublicProfile
PublishDiscoverySupply
RevokeDiscoveryPublication
```

HTTP surface:

```text
PUT  /v1/operations/discovery/offerings/{offering_id}/classification
POST /v1/operations/discovery/offerings/{offering_id}/classification/revoke
PUT  /v1/operations/discovery/resources/{resource_id}/public-profile
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

F2-specific E2E proofs exercise these semantics directly; generic Organization/Location tests are not counted as F2 authority/idempotency evidence.

## 7. Phase E — public cross-tenant discovery

Status: **closed in implementation; exact-head proof required**.

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

`provider_visibility=public` now has visible product semantics: it requires resource-specific publication plus an active `ResourcePublicProfile` and emits only approved public provider fields.

## 8. Phase F — Booking handoff and freshness

Status: **closed in implementation; exact-head proof required**.

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

Status: **closed in test design/implementation; exact-head execution required**.

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

## 10. Phase H — boundary and negative proofs

Status: **closed in test implementation; exact-head execution required**.

Feature-specific evidence covers:

```text
request_engine_discovery least privilege
request_engine_app cross-tenant function denial
taxonomy admin lifecycle + audit
revoked publication invisibility
hidden provider privacy
public provider/address projection
public DTO UUID minimization
inclusive radius inside/exact/outside
201st candidate too-broad failure
Publication stale fence
Mapping stale fence
OfferingVersion stale fence
F1 schedule/terms/assignment stale through discoopt_v1
foreign/unknown operation opacity
conflicting idempotency replay
rejected operation durable-state inspection
```

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

Status: **closed in branch content; exact-head governance tests required**.

Reconciled documents include:

- `docs/README.md` — F2 is active/current, not future-only;
- roadmap 14 — F1 implemented, F2 implemented on PR #77, F3-F6 future;
- contract 24 — sole normative F2 contract;
- hardening 25 — historical provenance, no precedence contradiction;
- this plan — current closure state;
- command inventory — includes mapping revoke and public Resource profile.

## 13. Performance debt intentionally not blocking F2 correctness

Current `search_published_supply()` may call `PublishedSlotReader` once per candidate and therefore can be latency-heavy near the 200-candidate bound.

Follow-up direction:

```text
BatchPublishedSlotReader
```

It is permitted only if it preserves:

```text
same discovery authority boundary
same F1 Booking truth
same eligibility
same global ordering
same stale handoff semantics
```

This is a performance follow-up, not a reason to relax F2 merge correctness.

## 14. Definition of Done

PR #77 is merge-ready only when the current branch head has fresh successful evidence for the repository's required gates and the F2-specific proofs listed by contract 24.

Checklist:

```text
[implemented] original product can answer where + with whom when provider is public
[implemented] explicit publication + revoke
[implemented] canonical classification + mapping/revoke
[implemented] public provider profile control-plane operation
[implemented] public Location address projection
[implemented] data-minimized public DTO
[implemented] dedicated discovery runtime role
[implemented] opaque discoopt_v1
[implemented] stale-safe Booking handoff
[implemented] shared-capacity safety
[implemented] F2-specific authority/idempotency/opacity tests
[implemented] mapping/publication race tests
[implemented] exact geo boundary test
[implemented] schedule/terms/assignment stale tests
[implemented] consumed handoff replay/new-mutation proof
[implemented] taxonomy lifecycle/audit proof
[implemented] current guarantee inventory + proof map
[implemented] README/roadmap/contract/hardening reconciliation
[pending evidence] exact-head CI green after all changes
```

A green run from an earlier SHA is provenance only and does not close this plan.