# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files point here rather than duplicating contracts.

## 1. Evolution policy

Request Engine is still pre-customer and pre-production. Released V3 remains reproducible historical/release provenance, but it is not a ceiling on the current product architecture.

Normative evolution policy:

- `architecture/pre-production-evolution-policy.md`

Core rule:

```text
freeze the evidence, not the future
```

New accepted post-V3 contracts may intentionally supersede historical structural assumptions when affected invariants are dispositioned and replaced with equal-or-stronger adversarial proof.

## 2. Current product line

Current post-V3 progression:

```text
released V3
  -> F1 Operational Profile / Contextual Supply
  -> F2 Geospatial Cross-Tenant Discovery
  -> F3 Live Service Operations
  -> F4 Live Capacity Projection [active]
```

F1-F3 are implemented predecessor architecture. The active feature scope is:

```text
feature/live-capacity-projection
```

F5-F6 remain roadmap work and must branch from the then-current `development` after their predecessor contracts/evidence are integrated.

## 3. Current F1 contracts

F1 is authoritative for Organization/Location operational truth, public contacts, Location hours/exceptions, Resource-at-Location assignment, Resource/assignment availability exceptions, contextual schedule/price/duration, Reservation commercial provenance and the contextual booking contract.

Read:

1. `v3/15-operational-profile-contextual-supply-contract.md` — normative F1 post-V3 contract.
2. `v3/13-operational-profile-contextual-supply-plan.md` — F1 implementation/closure plan and proof matrix.
3. `v3/16-operational-profile-contextual-supply-clarifications.md` — historical adversarial-review provenance.
4. `adr/0012-contextual-resource-location-supply.md` — durable contextual Resource-at-Location rationale.

## 4. Current F2 contracts

F2 owns explicit cross-tenant discovery publication, platform service classification, geospatial search, minimal public provider identity, public Location projection, opaque discovery handoff and discovery-to-Booking freshness/privilege boundaries.

Primary documents:

1. `v3/24-geospatial-cross-tenant-discovery-contract.md` — normative F2 contract.
2. `v3/22-geospatial-cross-tenant-discovery-plan.md` — implementation/closure provenance.
3. `v3/23-geospatial-cross-tenant-discovery-phase-a-inventory.md` — Phase A disposition provenance.
4. `v3/25-geospatial-cross-tenant-discovery-hardening.md` — historical adversarial-review provenance.
5. `adr/0011-cross-tenant-shared-capacity.md` — shared-capacity identity/serialization rationale.

Booking remains commitment authority after discovery.

## 5. Current F3 contracts

F3 activates live service operations while preserving:

```text
Reservation    = planning/commitment truth
QueueEntry     = arrival/wait/call truth
ServiceSession = actual execution truth
```

Read:

1. `v3/26-live-service-operations-contract.md` — normative F3 contract.
2. `v3/27-live-service-operations-current-state-inventory.md` — integrated old→new/evidence inventory.
3. `v3/28-live-service-operations-integration-amendment.md` — explicit amendment of older V3 baseline statements.
4. `10-module-ownership-map.md` — current Queue/Delivery ownership.

F3 provides expected vs actual workload facts, ServiceSession execution, interruptions, ResourceActivity and DB-authoritative operational timestamps. It intentionally does not own ETA/capacity prediction.

The supported F3 migration line ends at `0006_f3_historical_fact_hardening`; older text claiming all F3 behavior ended at `0005` is superseded by the reconciled current contract/inventory and migration README.

## 6. Active F4 contracts

F4 is the active implementation scope.

Read in this order:

1. `v3/29-live-capacity-projection-contract.md` — **normative F4 target contract**.
2. `v3/30-live-capacity-projection-current-state-inventory.md` — F4 old→new implementation disposition.
3. `v3/14-operational-intelligence-roadmap.md` — cross-feature product sequencing/boundaries.
4. F1/F3 contracts above for authoritative predecessor facts.

F4 core rule:

```text
live capacity projection
=
remaining workload
projected over
remaining effective operational time
```

F4 keeps distinct:

```text
scheduled_capacity
live_intake_capacity
```

and remains advisory. It does not become CapacityClaim authority, does not persist ETA/queue position as authoritative counters, and does not silently mutate planning/workload policy from observed history.

The initial contract deliberately uses an explicit ServiceQueue + Resource + Location projection scope and leaves multi-resource queue optimization outside F4.

## 7. Product roadmap

`v3/14-operational-intelligence-roadmap.md` is the accepted direction for F1-F6.

Current status:

```text
F1  implemented/integrated foundation
F2  implemented predecessor discovery
F3  implemented predecessor live operations
F4  active: Live Capacity Projection
F5  future: Operational Recovery + Communications
F6  future: Operational Copilot
```

The roadmap is product direction. `v3/29` defines F4 normative implementation semantics.

## 8. Testing and guarantee governance

Canonical testing/governance documents:

- `testing/repository-governance-contract.md`
- `testing/README.md`
- `testing/current-guarantees.toml`
- `testing/current-proof-map.toml`
- `testing/test-architecture-migration.md`

A green general CI run is not, by itself, proof that a feature Definition of Done is complete. Exact-head merge readiness must include feature-specific evidence required by the current guarantee inventory and owning contract.

F4 must add durable guarantees/proofs for projection separation, workload provenance, temporal consistency, Reservation/Queue/ServiceSession deduplication and staff/customer/tenant privacy before closure.

## 9. Current precedence

For F4 projection concepts:

```text
v3/29 F4 normative contract
  >
v3/30 F4 implementation inventory
  >
v3/14 product roadmap
  >
F1/F3 contracts only where F4 consumes their facts
```

F4 does not supersede Booking/Queue/Delivery ownership of their authoritative facts.

For F3 execution concepts:

```text
v3/28 F3 integration amendment + v3/26 F3 contract
  >
v3/27 explanatory inventory
  >
older V3 baseline statements that explicitly deferred execution
```

Outside post-V3 deltas, use the baseline precedence:

1. `11-capability-first-v3.md`
2. `v3/01-capability-contracts.md`
3. `v3/02-pre-sql-contract.md`
4. `07-database-access-contract.md`
5. `09-python-module-architecture.md`
6. `13-connection-surfaces.md`
7. `10-module-ownership-map.md`
8. `14-architecture-fitness-functions.md`
9. `testing/repository-governance-contract.md`
10. `architecture/pre-production-evolution-policy.md`

A newer accepted post-V3 contract may explicitly supersede named baseline rules under the pre-production evolution policy without rewriting released history.

## 10. Released V3 provenance

Request Engine V3 completed Phase 6 — V3 Freeze & Release Proof. Release/freeze evidence lives under `docs/release/` and remains historical provenance.

Current post-V3 product contracts may deliberately evolve beyond that baseline while preserving evidence discipline.

## 11. PostgreSQL executable surfaces

Executable SQL does not live in `docs/`.

Current production-facing Alembic history before F4 SQL is:

```text
0001_initial
  -> 0002_operational_profile_contextual_supply
  -> 0003_f1_runtime_acl_completion
  -> 0004_geospatial_cross_tenant_discovery
  -> 0005_live_service_operations
  -> 0006_f3_historical_fact_hardening
```

F2 development SQL-bearing steps remain under `migrations/f2_steps/` as provenance/support modules. Frozen V3 candidate SQL remains under `migrations/sql/v3_candidate/`; historical V2 design-chain SQL remains under `migrations/sql/design_chain/`.

See `migrations/README.md` before changing SQL.

## 12. Architecture and connection surfaces

Semantic dependency direction remains:

```text
entrypoint / adapter
       ↓
application command/query
       ↓
domain rules + explicit ports
       ↑
database/provider adapters
```

Physical organization is module-first according to `09-python-module-architecture.md`. Cross-module access uses published contracts according to `13-connection-surfaces.md`.

For F4 specifically, `live_capacity` consumes narrow Booking/Queue/Delivery contracts/read surfaces. It must not import those modules' adapters/application internals.

Architecture fitness functions are safety/drift detectors, not a ban on intentional evolution under a newer accepted contract.

## 13. Documentation policy

Durable domain/schema contracts belong under `docs/v3/` (or a successor versioned contract area). Durable rationale belongs in `docs/adr/`. Release proof belongs under `docs/release/`. Testing/repository governance belongs under `docs/testing/`.

Temporary hardening/amendment documents may be created during adversarial review. Once closed decisions are folded into the owning normative contract, they are provenance rather than competing specifications.

Everything under `legacy/` is historical and non-authoritative unless an explicit task asks to inspect it.

The domain/transaction contracts have precedence over implementation convenience. SQL and Python implement accepted contracts; they must not silently redefine them.
