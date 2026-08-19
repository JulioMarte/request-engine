# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## V3 transition status

Request Engine is in **Phase 6 — V3 Freeze & Release Proof** on the clean capability-first V3 candidate.

The current operational release roadmap is `release/v3-current-release-roadmap.md`. The canonical gate registry is `release/v3-release-gates.md`. When an older transition/rebaseline document conflicts with those files about current status or execution order, the current roadmap and gate registry win.

At `development@3281075bdc5e19997a3ba8120fa6a275e7ee5ab1`, G01–G16 are integrated `PASS`; G17 is `MISSING`, G18 is `MISSING`, G19 is `PARTIAL`, G20 is `MISSING`, and global V3 remains `NOT_READY`. The active order is G18 unified adversarial/failure proof → G19 fresh production-like bootstrap → candidate freeze → G17 final `0001_initial` equivalence → affected frozen-proof reruns → G20 final exact-head manifest.

The V3 product thesis is followed by concrete capability and pre-SQL transaction contracts under `docs/v3/`, and those contracts drive the executable clean PostgreSQL 18 candidate under `migrations/sql/v3_candidate/`.

The historical V2 PostgreSQL design chain remains useful as executable design history, but it is **not** a schema to freeze or extend. The active candidate remains pre-baseline until the remaining release gates close; it must not become `0001_initial` merely because G01–G16 are green.

When V3 and V2 conflict about product scope, Request semantics, baseline concepts, cardinality, transaction protocol, lock order, invariant ownership or whether a concept belongs in the first schema, V3 wins. Proven V2 safety patterns remain useful only where the corresponding V3 promise survives.

## Authoritative documents

Use this precedence when rules overlap:

1. `11-capability-first-v3.md` — product thesis, baseline capabilities and explicit V2 reductions.
2. `v3/01-capability-contracts.md` — public/application capability semantics for agents, forms, apps and integrations.
3. `v3/02-pre-sql-contract.md` — V3 entities/cardinalities, serialization roots, lock ordering, transaction protocols, invariants and race matrix.
4. `07-database-access-contract.md` — Python ↔ PostgreSQL boundary where not superseded by V3.
5. `09-python-module-architecture.md` — physical Python repository/module rules.
6. `13-connection-surfaces.md` — mandatory contracts between transport, modules, PostgreSQL, workers and providers.
7. `10-module-ownership-map.md` — module ownership.
8. `14-architecture-fitness-functions.md` — executable dependency/surface policy enforced by architecture tests.
9. `00-product-definition.md`, `01-architecture-v2.md`, `02-pre-sql-domain-contract.md` — V2 source material only where it does not conflict with V3.

Current Phase 6 release execution documents:

- `release/v3-current-release-roadmap.md` — current repository point, implemented proof and remaining execution path;
- `release/v3-release-gates.md` — canonical G01–G20 status registry;
- `release/v3-freeze-scope.md` — scope, evidence discipline and freeze rules;
- `release/v3-race-matrix.md` — release-critical race inventory;
- `release/v3-invariant-matrix.md` and `release/v3-invariant-proof-registry.json` — V3-I01..V3-I66 proof registry;
- `release/v3-public-api-contract-freeze.md` — G16 frozen public surface.

Transition/history support documents:

- `12-v3-transition-plan.md` — architectural migration/reduction plan; useful history, not the current Phase 6 execution order;
- `release/v3-post-merge-rebaseline.md` — historical rebaseline after the earlier feature integrations; its old gate statuses are not current;
- `v3/sql-disposition.md` — V2 SQL disposition inventory;
- `migrations/README.md` — active V3 candidate ownership, apply order and baseline-freeze gate.

Phase 6 executable release-proof contracts live under `release/`. In particular, `release/v3-test-isolation.md` owns disposable PostgreSQL test isolation, scratch database cleanup, evidence-manifest semantics and required CI-gate aggregation.

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

The older numbered canonical documents are retained during transition because design history and invariant references still point to them. Do not perform cosmetic bulk moves while V3 is stabilizing.

New V3 domain/schema contracts belong under `docs/v3/`. Durable rationale belongs in `adr/`. Current release execution belongs under `docs/release/` and must distinguish active status from historical evidence.

## PostgreSQL executable surfaces

Executable SQL does not live in `docs/`.

### Active V3 candidate

The active clean pre-baseline candidate is under:

```text
migrations/sql/v3_candidate/
```

It is installed by:

```bash
bash scripts/db/apply_v3_candidate.sh
```

CI installs it into a clean PostgreSQL 18 database and runs PostgreSQL-backed invariant/race/RLS tests. It is **not** yet production migration history. Do not create or bless the final `0001_initial` until G18 and G19 close and the candidate is explicitly frozen according to `release/v3-current-release-roadmap.md`.

### Historical V2 design chain

The historical V2.6→V2.10 chain remains under:

```text
migrations/sql/design_chain/
```

Those files are pre-production design history, not permanent Alembic history and not the active candidate. CI validates them separately so useful historical SQL does not silently rot.

See `migrations/README.md` before changing SQL.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless explicitly requested.
