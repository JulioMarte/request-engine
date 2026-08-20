# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## Active post-V3 feature branch

On `feature/operational-profile-contextual-supply`, the released V3 baseline remains immutable provenance, but F1 introduces an explicit post-V3 normative delta.

Read these branch-specific documents before implementing this feature:

1. `v3/16-operational-profile-contextual-supply-clarifications.md` — **highest-precedence F1 clarification on the specifically named points**. It corrects the second adversarial-audit findings: commercial Offering identity vs live workload classification, Location-level schedule exceptions, Resource-wide vs Resource-at-Location exceptions, Organization-as-independent-practice semantics, Organization-level public operational contacts, F2 canonical service classification, and F3 interruption authority direction.
2. `v3/15-operational-profile-contextual-supply-contract.md` — **normative F1 post-V3 delta** except where explicitly superseded by `v3/16`. It defines Organization operational defaults, Location/contact/geospatial truth, Resource-at-Location assignment, contextual schedule/price/duration, Reservation commercial provenance, authorization, races and backward compatibility.
3. `v3/13-operational-profile-contextual-supply-plan.md` — active F1 design/implementation plan, phases, test matrix and Definition of Done. Where `v3/16` clarifies a named point, the clarification wins until the main contract/plan are consolidated before merge.
4. `v3/14-operational-intelligence-roadmap.md` — complete accepted product/design direction for F1–F6. Only F1 is implementation scope of this branch; F2–F6 are preserved future direction. `v3/16` records the additional mandatory F2/F3 design questions found during adversarial review.
5. `adr/0012-contextual-resource-location-supply.md` — durable rationale for introducing Resource-at-Location/contextual booking supply while retaining Resource/CapacityClaim as the capacity model.

Precedence on this branch:

```text
v3/16 clarification, but only for the sections/concepts it explicitly names
  >
v3/15 F1 normative post-V3 contract
  >
v3/13 F1 implementation plan / v3/14 future roadmap as applicable
  >
released V3 baseline contracts for F1 concepts explicitly superseded by v3/15
```

For concepts explicitly named by `v3/15-operational-profile-contextual-supply-contract.md`, that post-V3 contract supersedes the corresponding released-baseline sections of `v3/01-capability-contracts.md`, `v3/02-pre-sql-contract.md` and `10-module-ownership-map.md` on this feature branch. Unrelated V3 rules remain authoritative.

`v3/16` is intentionally an amendment after a second adversarial audit. Before F1 is declared merge-ready, its closed clarifications should be consolidated into the main F1 contract so normal readers do not need a permanent amendment chain. Until then, `v3/16` is normative for the points it explicitly supersedes.

This precedence avoids rewriting released V3 history while giving the feature one unambiguous current contract.

## Current V3 status

Request Engine V3 has completed **Phase 6 — V3 Freeze & Release Proof**.

Canonical release state:

- G01–G20: `PASS`;
- frozen V3 candidate: complete;
- reviewed Alembic `0001_initial`: complete and proven structurally, behaviorally and runtime-equivalent to the frozen candidate;
- release evidence: `VALID` / `READY` for the proven promotion candidate;
- V3 promotion: merged from `development` to `main` in PR #72;
- released `main` commit: `07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc`;
- released tree: `4243840442d9b03d731c67ac514b46b1ee7dea7f`;
- current integration line: post-V3-baseline development.

The final promotion proof for PR #72 recorded source `development@9e58368e4ff593c8537c07de09defaec198d2b55`, tested merge candidate `0d1beea7c527fb5c3fc4bf37db29b04bf0a2d65f`, all G01–G20 `PASS`, `evidence_status: VALID`, `release_status: READY`, and preserved G17 equivalence. PR #73, already integrated into that development source, corrected shallow-CI freeze ancestry so release topology proves the frozen source is an ancestor of the exact tested checkout rather than incorrectly requiring an older `main` base to contain the freeze.

`release/v3-release-gates.md` remains the canonical G01–G20 registry. `release/v3-current-release-roadmap.md` is now a release-closure/provenance document rather than an unfinished execution plan. Older transition/rebaseline documents remain useful history but do not override current post-baseline status.

The historical V2 PostgreSQL design chain remains useful as executable design history. The frozen V3 candidate remains release provenance and an equivalence reference. Neither is the mutable production migration line. Production schema history begins at `migrations/versions/0001_initial.py` and evolves append-only from there.

When V3 and V2 conflict about product scope, Request semantics, baseline concepts, cardinality, transaction protocol, lock order, invariant ownership or whether a concept belongs in the baseline, V3 wins. Proven V2 safety patterns remain useful only where the corresponding V3 promise survives.

## Authoritative documents

Outside a branch-specific post-V3 delta, use this precedence when rules overlap:

1. `11-capability-first-v3.md` — product thesis, baseline capabilities and explicit V2 reductions.
2. `v3/01-capability-contracts.md` — public/application capability semantics for agents, forms, apps and integrations.
3. `v3/02-pre-sql-contract.md` — V3 entities/cardinalities, serialization roots, lock ordering, transaction protocols, invariants and race matrix.
4. `07-database-access-contract.md` — Python ↔ PostgreSQL boundary where not superseded by V3.
5. `09-python-module-architecture.md` — physical Python repository/module rules.
6. `13-connection-surfaces.md` — mandatory contracts between transport, modules, PostgreSQL, workers and providers.
7. `10-module-ownership-map.md` — module ownership.
8. `14-architecture-fitness-functions.md` — executable dependency/surface policy enforced by architecture tests.
9. `00-product-definition.md`, `01-architecture-v2.md`, `02-pre-sql-domain-contract.md` — V2 source material only where it does not conflict with V3.

A post-V3 feature contract may explicitly supersede named sections of this baseline precedence without rewriting released history. Such a delta must be indexed above, scoped precisely and accompanied by append-only schema evolution.

Release/freeze provenance documents:

- `release/v3-release-gates.md` — canonical G01–G20 closure registry;
- `release/v3-current-release-roadmap.md` — Phase 6 closure, G17/G20 provenance and release promotion record;
- `release/v3-candidate-freeze.json` — frozen candidate identity/provenance;
- `release/v3-freeze-scope.md` — evidence discipline and freeze rules;
- `release/v3-race-matrix.md` — release-critical race inventory;
- `release/v3-invariant-matrix.md` and `release/v3-invariant-proof-registry.json` — V3-I01..V3-I66 proof registry;
- `release/v3-public-api-contract-freeze.md` — G16 frozen public surface.

Transition/history support documents:

- `12-v3-transition-plan.md` — architectural migration/reduction history, not current execution state;
- `release/v3-post-merge-rebaseline.md` — historical rebaseline from earlier feature integration;
- `v3/sql-disposition.md` — historical V2→V3 SQL disposition inventory;
- earlier Phase 6 planning documents — release-proof history, not present-tense work queues.

The domain/transaction contracts have precedence over implementation convenience. SQL implements accepted contracts; it must not silently redefine them.

## Architecture Decision Records

`adr/` records durable rationale for hard-to-reverse architectural decisions. ADRs explain why the architecture exists; they do not replace the detailed normative contracts above.

Current accepted decisions include:

- modular monolith instead of premature microservices;
- smart PostgreSQL with Python-owned command orchestration;
- module-first Python physical organization;
- repository documentation as the canonical knowledge system for coding agents;
- capability-first product core instead of a universal workflow/domain model;
- durable transactional communications and scheduling separated from provider delivery;
- the minimal V3 booking/capacity model;
- PostgreSQL RLS as tenant defense-in-depth with narrow cross-tenant worker claim surfaces.

Post-V3 proposed ADRs may remain `Proposed` until implementation/evidence proves the decision. Do not call an ADR accepted merely because a feature branch documents it.

See `adr/README.md`.

## Physical layout clarification

The semantic dependency direction remains:

```text
entrypoint/adapter
      ↓
application command/query
      ↓
domain rules + explicit ports
      ↑
database/provider adapters
```

Physical organization is module-first according to `09-python-module-architecture.md`. Business transport is module-owned, while process entrypoints compose published module surfaces rather than reaching into module persistence/provider internals.

Every boundary crossing is also an explicit connection surface according to `13-connection-surfaces.md`:

```text
BOX A
  |
 |-|
  |
BOX B
```

The connector must define ownership, contract, trust/tenant context, transaction semantics and failure/retry behavior where applicable. `14-architecture-fitness-functions.md` converts high-value structural rules into CI failures so these surfaces cannot be bypassed silently. This remains one modular monolith and does not imply microservice boundaries.

## Documentation organization policy

The older numbered canonical documents are retained because design history and invariant references still point to them. Do not perform cosmetic bulk moves that erase provenance or make historical references ambiguous.

New durable domain/schema contracts belong under `docs/v3/` or a successor versioned contract area. Durable rationale belongs in `adr/`. Release-proof history and evidence contracts belong under `docs/release/` and must clearly distinguish historical checkpoints from current status.

Post-release features should prefer an explicit post-V3 delta contract when preserving the released baseline text provides clearer provenance than rewriting the old baseline as though the feature had always existed. The delta must state exactly what it supersedes.

Temporary clarification/amendment documents are allowed after adversarial review when they prevent an incorrect implementation from proceeding. They must declare narrow precedence and should be consolidated into the owning normative contract before merge rather than becoming a permanent maze of layered documents.

## PostgreSQL executable surfaces

Executable SQL does not live in `docs/`.

### Production migration history

The production migration line begins at:

```text
migrations/versions/0001_initial.py
```

That baseline was reviewed and proven equivalent to the frozen V3 candidate by G17. It is immutable release history. Post-release schema changes must be represented by new append-only Alembic revisions; do not edit `0001_initial` to make a later feature fit.

### Frozen V3 candidate provenance

The frozen release candidate remains under:

```text
migrations/sql/v3_candidate/
```

It is retained as the source/provenance side of the V3 freeze and equivalence proof. It is no longer the normal mutable schema-development surface. Do not append post-release product migrations there or reinterpret the frozen candidate as current production history.

### Historical V2 design chain

The historical V2.6→V2.10 chain remains under:

```text
migrations/sql/design_chain/
```

Those files are executable design history, not production Alembic history and not the active post-release migration path. CI may continue validating them independently so useful historical SQL does not silently rot.

See `migrations/README.md` before changing SQL.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless explicitly requested.