# PostgreSQL Schema & Proof Cohesion Audit

Status: active, pre-rebaseline
Branch: `audit/postgres-schema-proof-cohesion`

## Purpose

This audit evaluates the **effective PostgreSQL model after `alembic upgrade head`**. Migration chronology is evidence only; it is not the object under review.

The rebaseline decision is blocked until the effective model answers this question:

> If Request Engine were designed today for the product it actually is, would we deliberately keep every surviving relation, column, routine, trigger, policy, role, grant, constraint and index?

Classification:

- `KEEP`: semantics and topology are justified by current product ownership and current proof.
- `RESHAPE`: semantics remain necessary, but topology/authority/naming/indexing/composition should change before rebaseline.
- `REMOVE`: no current owner, invariant, supported consumer or operational contract justifies the object.
- `NEEDS_PROOF`: insufficient evidence; blocks rebaseline.

No object is kept merely because an old migration created it or a historical V3 proof mentions it.

## Evidence hierarchy

1. Effective catalog exported from the accepted Alembic head.
2. `docs/10-module-ownership-map.md` for capability ownership.
3. Current post-V3 contracts for ownership deltas.
4. `docs/07-database-access-contract.md` for Python/PostgreSQL authority boundaries.
5. `docs/testing/current-guarantees.toml` for semantic guarantees.
6. Exact-head current-product test execution for proof.
7. Migration history only when provenance is needed to explain an otherwise-current object.

The catalog exporter must include relations/columns, constraints/indexes, routine definitions, trigger definitions, policies, view dependencies, role topology, effective grants and default ACLs. A smaller catalog cannot close this audit.

## Audit dimensions

### 1. Schema ownership

Every relation and callable routine must resolve to one current owner:

- tenancy
- catalog
- requests
- booking
- queue
- communications
- discovery
- delivery
- live_capacity
- operational_recovery
- platform
- explicit cross-capability composition boundary

`operational_copilot` owns no underlying persistence truth.

An object is a blocker when ownership is absent, conflicting, or inferred only from a migration filename.

Cross-capability FK/read composition is not automatically leakage. A write path is suspicious when a non-owner can independently mutate another capability's authoritative fact rather than compose through the owner's accepted boundary.

### 2. Data-model redundancy

Review for:

- duplicate durable representations of one authoritative fact;
- mutable shadow copies of derivable state;
- compatibility columns whose consumer no longer exists;
- persisted counters/positions/ETAs that should remain derived;
- denormalization without a measured read-path reason;
- current/history pairs that cannot explain why both must exist.

Do not collapse deliberately separate truths such as Reservation planning, QueueEntry waiting/calling and ServiceSession execution merely because they correlate in one journey.

### 3. Stored-function and trigger topology

For every routine/trigger determine:

- semantic owner;
- caller and grant path;
- whether it is integrity enforcement, a narrow atomic primitive, or duplicated application workflow;
- `SECURITY INVOKER` versus `SECURITY DEFINER` justification;
- fixed trusted `search_path` for definer routines;
- whether multiple callable paths can perform the same business mutation;
- whether trigger-side cross-capability mutation hides an ownership boundary.

`SECURITY DEFINER` is never accepted merely because it makes RLS or grants convenient.

### 4. RLS and roles

For every table determine:

- tenant-scoped, deliberately global/shared, or administrative-only;
- RLS enabled/forced state and why;
- policy count and command coverage;
- runtime roles with direct DML;
- definer/bypass-RLS paths;
- default ACL behavior for future objects.

Integrity-by-trigger does not justify advertising an unusable write privilege. Runtime ACLs should describe legitimate authority, not rely on a trigger to reject authority the role should never have received.

### 5. Constraints and indexes

Evaluate invariants and query paths, not metric symmetry.

- PK/FK/UNIQUE/CHECK/EXCLUDE must encode structural invariants where PostgreSQL can enforce them.
- Exact duplicate and dominated indexes are removal candidates.
- Missing indexes are identified from current query/locking paths, not from a rule that every FK needs its own B-tree.
- Temporal/range access is reviewed against actual `&&`, ordering and tenant/location predicates.
- Append-only/history tables still require indexes justified by bounded current reads.

### 6. Proof coverage

`docs/testing/current-guarantees.toml` is normative. `current-proof-map.toml` is review evidence, not a filename freeze.

A guarantee is proven only when its required evidence classes are supplied by tests that **executed on the exact accepted schema head**. File existence is not proof.

Historical `v3_*` names are not automatically invalid. They must be classified by semantics:

- current invariant in an old path/name -> migrate/rename when useful, but keep the proof;
- historical release/freeze/equivalence assertion -> remove from current proof authority;
- mixed file -> split current semantic proofs from archaeological assertions.

### 7. Rebaseline readiness

Rebaseline is forbidden while any material object is `NEEDS_PROOF`, any accepted `RESHAPE` is unresolved, or any current guarantee depends only on dormant/historical proof.

The final pre-rebaseline catalog must be re-exported from exact head after all accepted schema changes.

## Findings confirmed so far

### F-01 — Current-product CI does not execute `tests/db/test_v3_candidate.py`

Classification: `RESHAPE` proof topology.

The file still contains materially current database proofs, including tenant isolation and core booking/capacity invariants, but it also contains historical candidate-shape assertions such as the absence of deferred V2 tables.

The current-product runner explicitly executes selected surviving V3-named suites because of the guarantees they prove, but it does **not** execute `tests/db/test_v3_candidate.py`.

Required action:

1. map each materially current test in that file to a current guarantee;
2. verify equivalent exact-head proof already exists elsewhere;
3. move any unique current proof into a current semantic suite;
4. remove candidate/release archaeology from current authority;
5. delete the mixed file only after no guarantee loses required evidence.

### F-02 — Proof inventory and execution validation are conceptually separate

Classification: `KEEP` architecture, verify exact-head implementation.

`current-guarantees.toml` correctly names semantic guarantees rather than filenames. `current-proof-map.toml` is explicitly non-normative. The audit must preserve that distinction.

A green proof map is insufficient if mapped files were not executed. Exact-head execution evidence must remain machine-checkable.

### F-03 — Database access contract and `SECURITY DEFINER` topology require reconciliation

Classification: `NEEDS_PROOF` until the effective audit-branch catalog is generated.

The normative DB contract says `request_cmd` routines default to `SECURITY INVOKER`; any `SECURITY DEFINER` case requires a real privilege-boundary justification, safe search path, minimal grants, non-runtime owner and escalation tests.

Evidence from the later system-optimization branch shows that the effective model can contain many definer routines and required dedicated hardening. This audit branch must not inherit that conclusion by assumption: it must enumerate the exact-head routines and classify each elevated surface by owner and caller.

A count alone is not a finding. An unjustified or over-granted definer is.

### F-04 — Runtime table DML must be judged by legitimate command ownership, not by zero-direct-DML ideology

Classification: `KEEP` principle.

The DB access contract explicitly permits command-side repositories plus narrow `request_cmd` primitives. Therefore direct `request_engine_app` DML is not automatically accidental authority.

The audit instead flags:

- DML on immutable/append-only facts that no supported command legitimately uses;
- non-owner writes that bypass an accepted composition boundary;
- grants inherited only from permissive default ACLs;
- write grants whose only safety mechanism is rejection by a trigger.

### F-05 — Administrative views cannot be declared dead from Python reference count alone

Classification: `KEEP` principle.

`request_admin` is an operator/DBA surface. A health/reconciliation view may be valid with zero Python consumers. Removal requires absence of an operational contract as well as absence of code/database dependents.

### F-06 — FK/index asymmetry is a review signal, not a defect count

Classification: `KEEP` principle.

A mechanical "index every FK" rule would create redundant indexes in a schema that already uses partial unique indexes, GiST temporal access paths and purpose-built queue/capacity indexes. The audit will classify missing access paths from actual reads, locks and delete/update behavior.

## Known high-value review targets

These targets require exact-head catalog/query evidence before final classification:

1. `SECURITY DEFINER` surfaces in `request_cmd`, `request_admin` and internal helpers.
2. Default ACLs for future `request_engine` and `request_read` relations/routines.
3. Append-only facts that still expose runtime `UPDATE`/`DELETE` authority.
4. Cross-capability trigger composition at QueueEntry ↔ ServiceSession.
5. Booking/Queue composition around SlotOffer and CapacityHold.
6. Recovery freshness/revision fencing and its semantic owner.
7. Reservation temporal-window query paths and range indexing.
8. Read/admin views with no current production reference.
9. Exact/leading duplicate indexes and obsolete compatibility indexes.
10. Current guarantees whose representative proof remains only in historical V3-named files.

## Rebaseline blockers

The database is **not authorized for rebaseline** until all of the following are true:

1. Exact-head comprehensive catalog exists for this branch.
2. Every table/view/routine has an explicit current owner or documented composition owner.
3. Every trigger and elevated routine has a justified authority path.
4. RLS/global-table exceptions and runtime direct DML are explicitly classified.
5. Accepted redundant objects and ACL defects are removed/reshaped.
6. Query-path index decisions are backed by actual access semantics rather than blanket ratios.
7. Every current guarantee has exact-head executed required evidence.
8. Mixed historical/current V3 proof files are decomposed or explicitly retained for current semantics.
9. Final catalog contains no material `NEEDS_PROOF` object.
10. A fresh exact-head current-product PostgreSQL run is green after the final schema changes.

Only then should Request Engine create a new initial baseline and establish any new freeze.
