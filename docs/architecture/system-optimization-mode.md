# Request Engine — System Optimization Mode

Status: **normative for `cohesion/system-optimization` and for later integration work explicitly continuing this pre-production optimization phase.**

This policy narrows and operationalizes `pre-production-evolution-policy.md` for the current cohesion work. The permanent evolution model is `continuous-evolution-policy.md`. This mode may grant additional pre-production freedom, but it does not replace that permanent model and does not weaken Request Engine correctness guarantees.

## 1. Objective

The current task is to make Request Engine describe and implement one coherent present-day system before the first production/customer compatibility obligations exist.

The repository may therefore remove release-era scaffolding, consolidate unreleased schema history, change internal architecture, rename historical concepts and simplify connection surfaces when doing so reduces accidental complexity and produces a clearer current product.

The governing rules are:

```text
freeze guarantees, not accidental repository shape
immutable history, evolvable future
```

## 2. What is mutable during this phase

While Request Engine has no customer-owned production data and no externally committed compatibility contract, the following are **CONTROLLED but mutable**:

- current PostgreSQL schema shape through new migrations;
- internal module ownership and approved dependency edges;
- private Python package/file layout;
- non-public DTOs and internal contracts;
- current test organization and filenames;
- release-era CI/tooling that protects no current obligation;
- historical feature/release naming such as V2/V3/F1-F7 when it no longer improves navigation;
- pre-production HTTP/tool contracts that have no external compatibility commitment, after explicit contract disposition.

Mutable does not mean casually editable. A change must still identify ownership, affected guarantees, compatibility consequences and replacement evidence.

The accepted `0001_initial` baseline is now **history**, not part of the mutable surface for ordinary changes. Product evolution appends `0002+` rather than rewriting the accepted baseline.

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

The PostgreSQL effective-schema audit and pre-production rebaseline are complete.

Canonical migration authority is now:

```text
migrations/versions/0001_initial.py
migrations/baseline/
```

The accepted baseline was derived from the audited effective model, reproduced on independent PostgreSQL 18 clusters, promoted to a single Alembic root and re-proved by the normal current-product CI after the historical chain was removed.

From this point forward:

1. `0001_initial` and `migrations/baseline/` are immutable accepted history;
2. ordinary schema evolution appends `0002+` revisions from the current single head;
3. current-product CI follows the repository head dynamically;
4. baseline-integrity CI separately proves that accepted `0001` still installs from a clean PostgreSQL 18 cluster;
5. no current guardrail may require `HEAD == 0001` forever;
6. historical V2/V3 migration scaffolding is not current schema authority;
7. schema changes that require old/new representations to coexist follow the expand → migrate → contract model defined by `continuous-evolution-policy.md`.

The retained `migrations/sql/design_chain/` surface is historical V2 evidence still required by a repository status context; it is explicitly not the current product schema source.

A future destructive rebaseline is possible only as another dedicated architecture operation while the product remains pre-production. It would require a fresh effective-schema audit, object disposition and independent clean-cluster reproduction proof. It must not be smuggled into ordinary feature or cleanup work.

Once customer-owned production data or an external compatibility promise exists, pre-production destructive freedom expires automatically. Continuous schema evolution continues through appended migrations, but data/consumer compatibility, migration safety and rollout/recovery obligations become mandatory under `continuous-evolution-policy.md`.

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

Deleting a test because it fails is prohibited. Removing obsolete evidence is valid only when the protected guarantee is intentionally retired or mapped to surviving equal-or-stronger evidence.

Feature/release prefixes in test paths (`v3_`, `f1_`, `f2_`, etc.) are not normative. The long-term target is organization by current capability/guarantee where that improves navigation.

A new architecture fitness function must answer what risk it protects and what a legitimate future change must prove before evolving it. Exact schema/module/file/endpoint inventories belong to historical evidence unless that exact inventory is itself a present compatibility obligation.

## 6. Maintainability and cohesion

LOC, McCabe complexity, file count, fan-in and fan-out are review evidence, not architecture verdicts.

No agent may make metrics green by:

- splitting cohesive files mechanically;
- creating forwarding wrappers or one-function modules;
- hiding dependencies behind service locators or runtime imports;
- moving business logic into `platform`, `shared`, `common` or generic utility buckets;
- duplicating logic to avoid an explicit dependency;
- proliferating interfaces/factories without a real substitution or ownership boundary.

A large cohesive file may be healthier than a fragmented package. A high-fan-out module may be correct when it explicitly owns orchestration. The question is whether ownership and reasoning locality improve.

## 7. Authority during optimization

Two different questions have different owners and must not be conflated.

### 7.1 What must remain semantically true?

For product behavior, authority, transactions, privacy, capacity and other business guarantees:

```text
current-guarantees.toml
+ owning current capability/domain contract
+ accepted ADR where it defines durable rationale
```

These sources define the behavior/invariants that a redesign must preserve or explicitly supersede with equal-or-stronger proof.

### 7.2 What repository/schema/module shape may change?

For whether an existing pre-production shape may be reorganized or consolidated:

```text
continuous-evolution-policy.md
+ system-optimization-mode.md
+ repository-governance-contract.md
+ pre-production-evolution-policy.md
```

These sources govern evolution authority. An older/current capability contract may describe the structure that implemented its semantics at a checkpoint; that structural description does **not** become an eternal freeze merely because the semantic contract remains valid.

When changing a structure described by an otherwise-current capability contract:

1. identify which statements are semantic guarantees versus implementation/architecture shape;
2. preserve or explicitly disposition the semantic statements;
3. update the current capability/ownership/architecture docs so they no longer describe the superseded shape as current;
4. adapt/replace executable proof in the same coherent change.

No document gets to weaken a HARD guarantee by calling a change “optimization”. No historical structural statement gets to block an otherwise valid controlled redesign solely because it was once release-proven.

## 8. Documentation rule

Historical documents may remain historically accurate. Current maps, READMEs, AGENTS files, CI contracts and migration READMEs must describe the present system and must not issue instructions that assume V3 is still an active candidate freeze or that the completed rebaseline is still pending.

Current indexes should route readers to authority instead of duplicating chronological feature status. If two current normative documents disagree, treat the contradiction as a repository defect and reconcile the semantic owner/evolution authority explicitly.

The permanent evolution policy must remain discoverable from current documentation/agent maps. A phase-specific policy may add stricter obligations but must not silently replace it with a structural freeze.

## 9. Exit condition

This mode ends when the broader cohesion/tooling audit is complete and the owner declares the repository ready to leave the temporary optimization phase. **Ending optimization mode is not the creation of another architecture freeze.** The repository then continues under `continuous-evolution-policy.md`, current guarantees, capability contracts and repository governance.

The database rebaseline itself is **not** an open exit condition anymore; it is complete. Before first production deployment, Request Engine still needs:

- one current architecture and ownership map;
- current CI derived from current guarantees rather than release archaeology;
- no known contradictory current agent/instruction/document authority;
- no mandatory V2/V3 release machinery without a real compatibility/provenance requirement;
- release/deployment automation appropriate to the production environment;
- explicit operational handling for migrations, deprecations, progressive rollout and recovery as required by the permanent evolution policy.

There should be no future blanket “freeze Request Engine” step. Production readiness may freeze **specific historical artifacts and published obligations**, while current architecture continues to evolve through controlled changes. Any future policy using the word `freeze` must name exactly what compatibility obligation is being frozen and must not silently convert heuristic maintainability signals or incidental repository shape into permanent architecture law.
