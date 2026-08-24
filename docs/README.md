# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files point here rather than duplicating the contracts.

## 1. Evolution policy

Request Engine is still pre-customer and pre-production. Released V3 remains reproducible historical/release provenance, but it is not a ceiling on the current product architecture.

Normative evolution policy:

- `architecture/pre-production-evolution-policy.md`

Core rule:

```text
freeze the evidence, not the future
```

New accepted post-V3 contracts may intentionally supersede historical structural assumptions when the affected invariants are dispositioned and replaced with equal-or-stronger adversarial proof.

## 2. Current product line

Current post-V3 progression:

```text
released V3
  -> F1 Operational Profile / Contextual Supply
  -> F2 Geospatial Cross-Tenant Discovery
  -> F3 Live Service Operations [next]
```

F1 and F2 are implemented/integrated product architecture. F2 was proven at exact feature head `647bf19ba7b0f716a472aa1a2e3ca2caae81e1c7` by canonical CI #2035 and merged through PR #77 into `development` as `06efd25067515cf5b4c8c03bc06551de28ad081a` on 2026-08-24.

F3 is the next roadmap feature and must branch from the then-current `development`. F4-F6 remain later roadmap work.

## 3. Current F1 contracts

F1 is authoritative for Organization/Location operational truth, public contacts, Location hours/exceptions, Resource-at-Location assignment, Resource/assignment availability exceptions, contextual schedule/price/duration, Reservation commercial provenance and the `aptopt_v2` contextual booking contract.

Read:

1. `v3/15-operational-profile-contextual-supply-contract.md` — normative F1 post-V3 contract.
2. `v3/13-operational-profile-contextual-supply-plan.md` — F1 implementation/closure plan and proof matrix.
3. `v3/16-operational-profile-contextual-supply-clarifications.md` — historical adversarial-review provenance; it no longer overrides F1.
4. `adr/0012-contextual-resource-location-supply.md` — durable rationale for contextual Resource-at-Location supply.

## 4. Current F2 contracts

F2 is authoritative for explicit cross-tenant discovery publication, platform service classification, geospatial search, minimal public provider identity, public Location address projection, `discoopt_v1`, discovery-to-Booking freshness fences and cross-tenant discovery privilege boundaries.

Read in this order:

1. `v3/24-geospatial-cross-tenant-discovery-contract.md` — **sole normative F2 product/architecture contract**.
2. `v3/22-geospatial-cross-tenant-discovery-plan.md` — implementation/closure plan and phased proof intent.
3. `v3/23-geospatial-cross-tenant-discovery-phase-a-inventory.md` — Phase A disposition/inventory provenance.
4. `v3/25-geospatial-cross-tenant-discovery-hardening.md` — **historical adversarial-review provenance only**; it never overrides document 24.
5. `adr/0011-cross-tenant-shared-capacity.md` — shared-capacity identity/serialization rationale that F2 must not leak publicly.

F2 currently provides:

```text
canonical ServiceClassification mapping
explicit DiscoveryPublication/revocation
ResourcePublicProfile for deliberately public providers
Location public address projection from F1 truth
geo-radius cross-tenant search
deterministic price/duration via F1 Booking availability
opaque discoopt_v1 handoff
commitment-time Publication/Mapping/OfferingVersion/F1 freshness fences
shared-physical-capacity safety across tenants
```

The F2 tenant control-plane operations are:

```text
MapOfferingToServiceClassification
RevokeOfferingServiceClassification
SetResourcePublicProfile
PublishDiscoverySupply
RevokeDiscoveryPublication
```

All require `operations.manage_discovery`, idempotency, tenant opacity and audit semantics.

## 5. Product roadmap

`v3/14-operational-intelligence-roadmap.md` is the accepted direction for F1-F6.

Current status:

```text
F1  implemented/integrated foundation
F2  implemented/integrated discovery capability
F3  next: Live Service Operations
F4  future: Live Capacity Projection
F5  future: Operational Recovery + Communications
F6  future: Operational Copilot
```

The roadmap is product direction. Each new feature must branch from current `development`, reconcile its own normative contract and earn exact-head merge evidence independently.

## 6. Testing and guarantee governance

Canonical testing/governance documents:

- `testing/repository-governance-contract.md` — normative HARD / CONTROLLED / FLEXIBLE / HISTORICAL policy.
- `testing/README.md` — testing architecture entry point.
- `testing/current-guarantees.toml` — normative machine-readable guarantee inventory.
- `testing/current-proof-map.toml` — representative proof mapping; filenames are not constitutional.
- `testing/test-architecture-migration.md` — restructuring/disposition ledger.

F2 adds durable guarantees including:

```text
INV-DISCOVERY-PUBLICATION-001
INV-DISCOVERY-HANDOFF-001
INV-DISCOVERY-CONCURRENCY-001
```

CI #2035 is the authoritative exact-head merge evidence for the F2 feature head that was integrated by PR #77. That evidence is now historical provenance for F2; it must not be reused as Definition-of-Done evidence for F3 or later work.

## 7. Current precedence

For concepts explicitly owned by F2:

```text
v3/24 F2 normative contract
  >
v3/22 F2 implementation/closure plan
  >
v3/14 product roadmap
  >
F1 / released V3 contracts where F2 explicitly extends their behavior
```

Document 25 is provenance and has no higher-precedence role.

For F1 concepts not changed by F2:

```text
v3/15 F1 normative contract
  >
v3/13 F1 plan
  >
released V3 baseline sections explicitly superseded by F1
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

## 8. Released V3 provenance

Request Engine V3 completed Phase 6 — V3 Freeze & Release Proof.

Canonical release state:

- G01-G20: PASS;
- frozen V3 candidate: complete;
- reviewed Alembic `0001_initial`: proven equivalent to the frozen candidate;
- V3 promotion: merged to `main` in PR #72;
- released `main` commit: `07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc`.

Release/freeze evidence lives under `docs/release/`, including:

- `release/v3-release-gates.md`
- `release/v3-current-release-roadmap.md`
- `release/v3-candidate-freeze.json`
- `release/v3-freeze-scope.md`
- `release/v3-race-matrix.md`
- `release/v3-invariant-matrix.md`
- `release/v3-invariant-proof-registry.json`
- `release/v3-public-api-contract-freeze.md`

These are historical/release provenance. Current post-V3 product contracts may deliberately evolve beyond them while preserving the evidence discipline.

## 9. PostgreSQL executable surfaces

Executable SQL does not live in `docs/`.

Production migration history begins at:

```text
migrations/versions/0001_initial.py
```

Released V3 baseline history is immutable. F1 occupies current production revisions `0002/0003`. F2 is consolidated into one pre-production production-line revision:

```text
migrations/versions/0004_geospatial_cross_tenant_discovery.py
```

F2 development SQL-bearing steps are retained under `migrations/f2_steps/` and executed by the consolidated revision; they are provenance, not separately deployed production revisions.

Frozen V3 candidate SQL remains under `migrations/sql/v3_candidate/`. Historical V2 design-chain SQL remains under `migrations/sql/design_chain/`.

See `migrations/README.md` before changing SQL.

## 10. Architecture and connection surfaces

The semantic dependency direction remains:

```text
entrypoint / adapter
       ↓
application command/query
       ↓
domain rules + explicit ports
       ↑
database/provider adapters
```

Physical organization is module-first according to `09-python-module-architecture.md`. Cross-module access uses published contracts according to `13-connection-surfaces.md`; process entrypoints compose modules rather than reaching into persistence internals.

Architecture fitness functions are safety/drift detectors, not a ban on intentional evolution under a newer accepted contract.

## 11. Documentation policy

Durable domain/schema contracts belong under `docs/v3/` (or a successor versioned contract area). Durable rationale belongs in `docs/adr/`. Release proof belongs under `docs/release/`. Testing/repository governance belongs under `docs/testing/`.

Temporary hardening/amendment documents may be created during adversarial review. Once their closed decisions are folded into the owning normative contract, they must be demoted to provenance so the repository does not accumulate contradictory precedence chains.

Everything under `legacy/` is historical and non-authoritative unless an explicit task asks to inspect it.

The domain/transaction contracts have precedence over implementation convenience. SQL and Python implement accepted contracts; they must not silently redefine them.
