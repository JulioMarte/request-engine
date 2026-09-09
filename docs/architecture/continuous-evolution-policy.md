# Request Engine — Continuous Evolution Policy

Status: **normative permanent evolution policy**.

This policy defines how Request Engine changes safely without repeating the V3 mistake of turning a proven checkpoint into a permanent product-shape freeze.

It applies during pre-production and remains the default evolution model after production begins. Phase-specific policy may become stricter, but may not silently replace this model with structural immobility.

## 1. Governing principle

```text
immutable history, evolvable future
```

Request Engine protects:

- semantic guarantees;
- customer-owned data and durable provenance;
- explicitly published compatibility commitments;
- reproducible migration/release history;
- security, authority, transaction and concurrency boundaries;
- the ability to move safely from one supported state to the next.

Request Engine does **not** protect accidental repository shape merely because that shape once passed CI.

A release, migration, schema fingerprint, module graph, file layout, endpoint inventory or test allowlist proves a checkpoint. It does not become a constitutional ceiling on future architecture unless a current normative contract explicitly makes that exact shape a supported compatibility obligation.

The V3 freeze is retained as a historical lesson: proving a state was useful; requiring the future to remain structurally identical to that state was not.

## 2. The two kinds of immutability

### 2.1 Historical immutability

Applied/released history is immutable evidence.

Examples:

- accepted Alembic revisions;
- released build artifacts;
- release manifests;
- historical schema/role fingerprints;
- accepted ADRs as records of the decision at that time;
- production audit/provenance facts.

Do not rewrite historical artifacts to make current development easier.

### 2.2 Architectural immutability

Current architecture is **not** immutable merely because its history is.

Current schema, module ownership, APIs, commands, read contracts, transaction protocols and internal layout may evolve through the governance process appropriate to their classification:

```text
HARD        preserve or replace with equal-or-stronger safety
CONTROLLED  may evolve through an explicit current contract decision
FLEXIBLE    may evolve freely inside HARD/CONTROLLED boundaries
HISTORICAL  remains pinned to the historical checkpoint it documents
```

The repository must never infer:

```text
historical artifact is immutable
therefore
current product shape must remain identical to it
```

## 3. Default change model

Prefer small, independently understandable changes that keep the repository deployable and the current product provable.

For every non-trivial change, classify it before implementation:

### A. Additive compatible change

Examples: new optional field, new table, new read contract, new capability that does not invalidate existing consumers.

Default action: append, prove, ship.

### B. Internal breaking change with no external compatibility obligation

Examples: private module boundary redesign, private DTO replacement, pre-production capability reshaping.

Default action: explicitly disposition the old contract, migrate all in-repository consumers in one coherent change or through parallel change when safer, update current docs and proof.

### C. Published/external contract change

Examples: customer/API/tool/provider contract consumed independently of the deployment.

Default action: preserve compatibility during a documented migration window, version when simultaneous compatibility cannot be expressed safely, and remove the old surface only after its retirement criteria are satisfied.

### D. Persistent-data/schema change

Default action: append a migration and use the database evolution rules in this document. Never rewrite an already accepted/applied migration.

### E. High-risk operational change

Examples: authorization topology, capacity serialization, worker fencing, destructive data transformation, large backfill, provider protocol or cross-cutting rollout behavior.

Default action: smaller steps, stronger falsification evidence, explicit rollout/mitigation plan and progressive exposure when production exists.

## 4. PostgreSQL evolution contract

### 4.1 Migration history

The accepted `0001_initial` and `migrations/baseline/` are immutable migration history.

Ordinary schema evolution:

1. starts from the single current Alembic head;
2. appends a new revision (`0002+`, then subsequent revisions);
3. never edits an already accepted/applied revision;
4. leaves the repository capable of building a clean database through `alembic upgrade head`;
5. preserves a single unambiguous current migration head unless a deliberate reviewed merge revision resolves parallel history.

`0001` is not the current schema ceiling. It is the oldest accepted step in the current lineage.

### 4.2 Expand → migrate → contract

When a schema change cannot safely happen atomically across all consumers, use parallel change:

```text
EXPAND
add the new representation while the old representation still works

MIGRATE
move code/data/readers/writers to the new representation and verify convergence

CONTRACT
remove the old representation only after no supported consumer depends on it
```

Examples include column/table renames, representation changes, function signature changes and published read/command surfaces.

Do not emulate a rename with an immediate drop-and-recreate when old and new application versions may overlap.

### 4.3 Backfills

Production-scale or potentially long-running backfills must be:

- explicit rather than hidden inside request-path code;
- resumable or safely restartable;
- idempotent, checkpointed or otherwise duplicate-safe;
- bounded in transaction size when a large transaction would create unacceptable lock/WAL/recovery risk;
- observable;
- separated from destructive cleanup when practical;
- verified before the old representation is removed.

A migration that changes schema and transforms a trivial bounded amount of data may remain atomic when that is demonstrably safer. Do not cargo-cult a separate backfill for tiny deterministic transformations.

### 4.4 Constraints and indexes

Prefer introducing integrity as early as safely possible, while choosing PostgreSQL mechanisms appropriate to production lock/availability risk.

For large production tables, consider staged validation (`NOT VALID` followed by `VALIDATE CONSTRAINT`) when supported and useful. For production index creation where blocking is unacceptable, consider PostgreSQL concurrent index construction with the required migration transaction handling.

These are tools, not mandatory rituals. The PR must explain the lock/availability consequence of the chosen DDL.

### 4.5 Destructive operations

A destructive schema operation (`DROP`, incompatible type rewrite, destructive merge/split, irreversible data transform) must identify:

```text
supported consumers
migration state
rollback/roll-forward consequence
data/provenance consequence
backup/recovery assumption
proof that old data is no longer required
```

After customer-owned production data exists, destructive rebaseline is not normal evolution. A rebaseline would require an explicit production data migration/export-import/cutover strategy and cannot be justified only by repository cleanliness.

## 5. Application/API evolution

### 5.1 Published versus private surfaces

Compatibility burden attaches to **published consumers**, not to every Python symbol that happens to exist.

For every changed surface determine whether it is:

- private implementation;
- in-repository module contract;
- deployed internal contract with independently deployed consumers;
- customer/public contract;
- historical-only contract.

Do not force versioning onto private implementation details. Do not treat a public contract as private because changing it is inconvenient.

### 5.2 Compatibility window

Once independently deployed or external consumers exist, the default is that a newly deployed producer/schema must tolerate the supported old consumer during the rollout/migration window, and a newly deployed consumer must tolerate the supported old producer/schema where deployment order requires it.

This is deployment compatibility, not eternal backward compatibility.

### 5.3 Deprecation and removal

A published surface may be retired only when its current owner records:

```text
replacement
consumer population or discovery method
migration/deprecation start
removal criterion
observability proving the criterion
compatibility consequence
```

Calendar time may be part of the removal criterion, but time alone is not proof that consumers migrated.

## 6. Deployment and release safety

Production release engineering should optimize for both velocity and reliability.

Default principles:

- builds/releases are reproducible from version-controlled inputs;
- CI and deployment procedures are automated where practical;
- changes are small enough to understand and mitigate;
- risky changes are progressively exposed when production traffic/capacity allows it;
- monitoring determines whether rollout continues;
- mitigation is prepared before rollout, not invented during failure;
- feature/configuration switches may decouple deployment from activation when they materially reduce risk;
- database changes prefer roll-forward-safe evolution because application rollback cannot undo committed customer data safely.

Rollback remains useful for code/configuration when the data/schema compatibility window permits it. Never promise rollback for a migration whose persisted effects are not actually reversible.

## 7. CI and architecture fitness rules

CI must protect **properties and transition safety**, not eternal snapshots.

Good durable gates answer questions such as:

- Is tenant isolation still enforced?
- Is there exactly one current Alembic head?
- Can a clean supported database upgrade to current head?
- Does accepted historical baseline still reproduce?
- Are cross-module boundaries explicit and acyclic?
- Does a contested mutation serialize correctly?
- Does every current guarantee have executable evidence?
- Did an incompatible published change provide a migration/versioning decision?

Bad permanent gates answer only:

- Is the head still `0001`?
- Is the module list byte-for-byte identical to a past release?
- Are there exactly N endpoints/files/tests forever?
- Does current schema have the same fingerprint as a historical release?
- Did a historical allowlist remain unchanged despite an accepted new architecture?

Exact shape/fingerprint assertions are legitimate **historical provenance tests** when pinned to the historical artifact they describe.

## 8. Architecture-change protocol

A HARD or CONTROLLED change is valid when the PR can answer:

```text
CURRENT RULE
What is authoritative before this change?

CHANGE DRIVER
Why is evolution required?

NEW CONTRACT
What becomes authoritative?

INVARIANT DISPOSITION
What is preserved, strengthened, replaced or deliberately retired?

COMPATIBILITY
Which consumers/data/releases must coexist and for how long/under what criterion?

MIGRATION
How does the system move from old to new without an unsafe intermediate state?

FAILURE / MITIGATION
What can go wrong during migration or rollout and how is it contained?

PROOF
What executable evidence would falsify the new design?

DOCUMENTATION
Which current owner docs/ADRs/instructions are updated?
```

The answer may be short for a small CONTROLLED change. The classification determines rigor; ceremony must not become another freeze mechanism.

## 9. What must never be used as a substitute for design

Do not protect Request Engine by accumulating permanent ratchets around incidental state.

Specifically avoid:

- frozen migration-head numbers;
- frozen endpoint/module/file inventories without a present compatibility reason;
- duplicated historical CI lanes on current head;
- exact architecture snapshots treated as HARD without a semantic risk;
- allowlists that can only grow and can never be deliberately redesigned;
- tests whose only failure reason is that a legitimate new capability exists;
- mandatory manual approval for routine low-risk evolution when automated evidence is stronger;
- feature flags that become permanent dead branches;
- compatibility shims with no owner/removal criterion.

Every compatibility mechanism creates debt. Give it an owner and retirement condition.

## 10. Production transition trigger

The repository moves from greenfield compatibility freedom to production compatibility obligations when **either** becomes true:

1. Request Engine stores customer-owned production data that must survive upgrades; or
2. an external/independently deployed consumer has been promised a supported contract.

No release label or version number is required to trigger this. Reality triggers it.

At that point:

- destructive changes require data/consumer migration plans;
- deployment overlap becomes an explicit compatibility concern;
- public contract deprecation/removal must be observable and controlled;
- migration rollback/roll-forward assumptions must reflect persisted production data;
- progressive rollout and operational mitigation become part of release evidence for high-risk changes.

## 11. Rebaseline policy

Before production, a destructive rebaseline remains possible as an exceptional repository-architecture operation when it removes substantial accidental history and the effective model has been independently audited and reproduced.

After production data exists, **do not use rebaseline as a cleanup technique**. Schema lineage continues through migrations. Any extraordinary lineage replacement is a production migration project with explicit data transfer/cutover/recovery semantics.

This prevents both failure modes:

```text
freeze forever because history exists
```

and

```text
rewrite history whenever current shape becomes inconvenient
```

## 12. External engineering references

This policy is aligned with established evolutionary/release practices:

- Google SRE, *Release Engineering* — reproducible, automated release processes and high release velocity with controlled safety;
- Google SRE Workbook, *Canarying Releases* — small automated releases, progressive exposure and observable rollout decisions;
- Martin Fowler / Danilo Sato, *Parallel Change* — expand, migrate, contract for backward-incompatible interface evolution;
- Martin Fowler / Pramod Sadalage, *Evolutionary Database Design* — version-controlled database artifacts and migration-driven database evolution.

These references provide engineering rationale. This repository policy remains the normative Request Engine contract.
