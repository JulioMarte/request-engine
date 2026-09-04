# Request Engine — System Optimization Mode

Status: **normative for `cohesion/system-optimization` and for any later integration work explicitly continuing this pre-production optimization phase.**

This policy narrows and operationalizes `pre-production-evolution-policy.md` for the current cohesion/rebaseline work. It does not weaken Request Engine correctness guarantees.

## 1. Objective

The current task is to make Request Engine describe and implement one coherent present-day system before the first production/customer compatibility freeze.

The repository may therefore remove release-era scaffolding, consolidate unreleased schema history, change internal architecture, rename historical concepts and simplify connection surfaces when doing so reduces accidental complexity and produces a clearer current product.

The governing rule is:

```text
freeze guarantees, not accidental repository shape
```

## 2. What is mutable during this phase

While Request Engine has no customer-owned production data and no externally committed compatibility contract, the following are **CONTROLLED but mutable**:

- current PostgreSQL schema shape;
- Alembic revision structure after an explicit rebaseline decision;
- internal module ownership and approved dependency edges;
- private Python package/file layout;
- non-public DTOs and internal contracts;
- current test organization and filenames;
- release-era CI/tooling that protects no current obligation;
- historical feature/release naming such as V2/V3/F1-F7 when it no longer improves navigation;
- pre-production HTTP/tool contracts that have no external compatibility commitment, after explicit contract disposition.

Mutable does not mean casually editable. A change must still identify ownership, affected guarantees, compatibility consequences and replacement evidence.

## 3. What remains hard

The following remain HARD unless an explicit replacement architecture provides equal-or-stronger safety and proof:

- tenant isolation and foreign-row opacity;
- explicit principal/party/representation authority;
- transactional atomicity;
- single authoritative capacity ownership;
- idempotency for externally retryable commands;
- durable provenance and historical business facts where the product relies on them;
- worker crash/retry/fencing safety;
- outbox/asynchronous consequence durability;
- least-privilege PostgreSQL roles, RLS and callable/write authority;
- timezone, DST and half-open interval semantics;
- deterministic contested-state/concurrency loser semantics;
- bounded failure/retry behavior;
- clear module ownership, published connection surfaces and an acyclic dependency graph.

`docs/testing/current-guarantees.toml` is the canonical semantic guarantee inventory during this phase.

## 4. Database posture

The current Alembic line and released V3 artifacts are evidence of how the repository reached its present schema. They are **not a permanent design ceiling** during system optimization.

Until the database audit is complete:

- do not casually rewrite `0001_initial` or later revisions;
- ordinary schema changes should continue to use the current head unless the work item is explicitly a rebaseline;
- do not append new SQL to `migrations/sql/v3_candidate` as if it were the active product schema;
- do not modify historical V2/V3 artifacts merely to silence current-product tests.

A repository rebaseline is permitted only as a dedicated, reviewed change after the current schema has been audited. A valid rebaseline must:

1. define the intended current schema from domain ownership and guarantees, not merely dump the existing database blindly;
2. disposition every table/function/constraint/index/role/RLS policy that is removed or changed;
3. preserve or strengthen all applicable entries in `current-guarantees.toml`;
4. prove fresh bootstrap to exactly one Alembic head on PostgreSQL 18;
5. run current-product invariant, security, race and E2E evidence against that head;
6. explicitly record what historical migration/release machinery becomes Git/tag/release provenance instead of active repository machinery.

Once customer-owned production data or an external compatibility promise exists, this freedom expires and a production migration/versioning policy becomes mandatory.

## 5. CI and test posture

Current CI protects current guarantees. Historical release machinery must not remain mandatory merely because it once existed.

Tests are classified by protected intent:

```text
KEEP        protects a current guarantee
ADAPT       guarantee survives; implementation/contract changed
REPLACE     stronger/current proof supersedes obsolete structure
REMOVE      redundant or protects a deliberately retired promise
HISTORICAL  release provenance only; not a current-product gate
```

Deleting a test because it fails is prohibited. Removing obsolete evidence is valid only when the protected guarantee is either intentionally retired or mapped to surviving equal-or-stronger evidence.

Feature/release prefixes in test paths (`v3_`, `f1_`, `f2_`, etc.) are not normative. The long-term target is organization by current capability/guarantee where that improves navigation.

## 6. Maintainability and cohesion

LOC, McCabe complexity, file count, fan-in and fan-out are review evidence, not architecture verdicts.

No agent may make metrics green by:

- splitting cohesive files mechanically;
- creating forwarding wrappers or one-function modules;
- hiding dependencies behind service locators or runtime imports;
- moving business logic into `platform`, `shared`, `common` or generic utility buckets;
- duplicating logic to avoid an explicit dependency;
- proliferating interfaces/factories without a real substitution or ownership boundary.

A large cohesive file may be healthier than a fragmented package. A high-fan-out module may be correct when it explicitly owns orchestration. The question is always whether ownership and reasoning locality improve.

## 7. Documentation precedence during optimization

For current optimization/rebaseline decisions:

```text
current accepted capability/domain contract
  > current-guarantees.toml for protected semantics
  > system-optimization-mode.md for evolution freedom
  > current ownership/connection-surface documents
  > historical V3/F1-F7 plans and release evidence
```

Historical documents may remain historically accurate. Current maps, AGENTS files, CI contracts and migration READMEs must describe the present system and must not issue instructions that assume V3 is still an active candidate freeze.

## 8. Exit condition

This mode ends when the repository has completed the cohesion/schema/tooling audit and the owner explicitly chooses a new production freeze.

Before that freeze, Request Engine must have:

- one current architecture and ownership map;
- one coherent current schema baseline/migration policy;
- current CI derived from current guarantees rather than release archaeology;
- no known contradictory agent instructions;
- no mandatory V2/V3 release machinery without a real compatibility/provenance requirement;
- an explicit production evolution, API compatibility and data-migration policy.
