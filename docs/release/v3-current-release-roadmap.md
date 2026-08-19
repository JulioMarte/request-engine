# Request Engine V3 — current release roadmap

Status: **active operational roadmap for Phase 6 V3 Freeze & Release Proof**.

Repository reference points for this roadmap:

- integration branch: `development`;
- latest implementation-bearing gate closure before documentation reconciliation: `b6985be7ecd229da1c5e6aa754f12bc311af6f1e` (PR #69, G19 fresh production-like bootstrap);
- documentation reconciliation merged by PR #66: `8f0f6f1c66b8bd143e440a83bbabe04cc7d58556`;
- PostgreSQL target: PostgreSQL 18;
- release status: `NOT_READY`.

Commit identities above are provenance checkpoints, not a claim that `development` will forever equal either SHA. The branch head may advance as the remaining release gates are implemented. Current status authority is this roadmap together with `v3-release-gates.md`, and executable evidence remains authoritative only for the exact commit/tree that produced it.

Historical Phase 6 planning and rebaseline documents remain useful evidence of how the release proof evolved, but they must not override this roadmap or `v3-release-gates.md` when deciding what to execute next.

## 1. Current gate state

| Gate range | State | Meaning |
|---|---:|---|
| G01–G16 | PASS | integrated executable proof and registry closure exist for these gates; final promotion still requires exact-final-candidate regeneration where applicable |
| G17 | MISSING | final `0001_initial` has not been generated/blessed or proven equivalent |
| G18 | PASS | unified attack/race/crash/retry/order/mutation evidence is mandatory, machine-readable and semantically validated on exact-head canonical CI |
| G19 | PASS | fresh PostgreSQL 18 bootstrap, production-style runtime LOGINs, app/worker execution, crash/reclaim and canonical release suite are machine-readable and semantically validated |
| G20 | MISSING | no final exact-head release manifest with all G01–G20 PASS exists |

`release_status` must remain `NOT_READY` until every gate is `PASS` on the final release candidate.

## 2. What is already implemented and proven

The following is no longer implementation backlog for V3 unless new evidence falsifies it.

### Candidate construction and quality

- ordered PostgreSQL 18 V3 candidate chain;
- repeated clean bootstrap proof;
- separately preserved V2 design-history proof;
- Python quality, typing, security, dependency and architecture fitness checks.

### Invariant and tenant-authority closure

- `V3-I01..V3-I66` reconciled to executable owner-boundary proof;
- real `request_engine_app` LOGIN coverage;
- fail-closed tenant RLS and cross-tenant attack matrix;
- protected-function inventory and Party-authority validation;
- runtime app/worker/admin privilege closure and SECURITY DEFINER hardening.

Invariant ownership and race-matrix closure remain separate proof dimensions. G18 has now reconciled the race dimension independently rather than inferring race success from invariant `PASS` state.

### Booking and released-slot recovery

- Reservation create/cancel/reschedule/attendance/no-show lifecycle;
- capacity hold/claim correctness;
- released-slot recovery through SlotOpportunity → Waitlist → CapacityHold + SlotOffer;
- accept/decline/expiry and concurrency semantics;
- historical reschedule provenance via `old_location_id`, `old_start_at`, `old_end_at` so delayed A→B→C facts recover the slot released by the event rather than mutable later state.

### Workers and failure recovery

- ScheduledAction, OutboxMessage and ProviderEvent leasing/fencing;
- stale-token rejection, reclaim, retry, dead-letter and fairness behavior;
- process-death and lease-loss recovery;
- worker control sessions separated from domain application sessions;
- external-effect ambiguity recovered through lookup/reconciliation rather than exactly-once assumptions.

### Idempotency and optimistic concurrency

- frozen runtime mutation inventory;
- post-commit response-loss retry proof;
- same-key/different-fingerprint rejection;
- real concurrent-writer revision proof for public revision-managed aggregates.

### ProviderEvent and Communications reliability

- duplicate/reordered/ambiguous provider evidence handling;
- reconciliation-first recovery;
- retryable versus non-retryable provider outcomes;
- terminal Communications ordering so late `DELIVERED` cannot overwrite an absorbing non-retryable terminal failure for the same attempt;
- trusted ProviderEvent replay and Reminder reliability races.

### Query-plan and index evidence

Representative-cardinality `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` proof exists for:

- worker claims;
- Queue/Waitlist/SlotOffer;
- Booking availability/capacity;
- Communications;
- Reservation lifecycle;
- shared-capacity hot paths.

Indexes retained for V3 were justified by measured planner behavior. Speculative or ineffective indexes, including the rejected global range-only CapacityClaim GiST experiment, were not kept merely because they had been implemented.

### Public contract freeze

G16 freezes and proves:

- exactly 24 classified `/v1/` operations;
- exactly 34 canonical capability definitions;
- capability schema versions `[1]`;
- exactly 51 public machine error codes;
- runtime FastAPI/OpenAPI metadata consistency;
- mandatory machine-readable `.phase6/v3-public-api-contract.json` evidence;
- release-manifest validation that recomputes the embedded runtime contract fingerprint.

Final exact-head G16 evidence before integration was CI #1140 (`32206740884`) on `d3279fc5022f063779df4a48c323a53916cf8e93`, artifact `9349539679` (`sha256:274ae8e3dd47c9fdd65ae8c65cff335b43ec15c1817178b2ac40871d29520ab8`). The manifest recorded G16 `PASS`, public-contract validation `PASS`, a complete clean evidence bundle and `release_status: NOT_READY`.

### Unified adversarial/failure proof

G18 now composes the previously distributed failure evidence into one mandatory release artifact. `.phase6/v3-adversarial-failure-proof.json` covers six required families — attack/security, race/concurrency, crash/recovery, retry/idempotency, order independence and mutation probes — and the release manifest validates its exact inventories and statuses. The canonical race registry is closed independently at R01–R29 PASS.

Canonical CI #1166 (`32242214119`) passed on exact implementation head `a08ddb00b52d7405e9eb5d972a1439eee52c7190`. Artifact `v3-candidate-release-proof` `9361488628` (`sha256:1778a081977a4d92208dc37af27f2c9c6a997b15f5a607824dbf3939ac2ade16`) contains a G18 artifact with 6/6 families PASS, 29/29 races PASS, `registry_non_pass: []`, `missing_evidence: []` and `failures: []`. The same candidate run passed 463 PostgreSQL tests, three 96-test concurrency-stability rounds, 463 order-independence tests and mutation probes; the final evidence manifest is `VALID` while `release_status` remains correctly `NOT_READY`.

### Fresh production-like bootstrap

G19 now composes clean-start, PostgreSQL 18, production-style runtime role provisioning, real app/worker execution, representative HTTP/queue behavior, worker separation, crash/reclaim and the canonical release suite into mandatory machine-readable evidence. The proof uses exactly three restricted runtime LOGINs for app, worker and trusted admin authority, keeps credentials outside `.phase6/`, and validates only sanitized role metadata in the release artifact.

Canonical CI #1178 (`32250520126`) passed every required job on exact implementation head `b6985be7ecd229da1c5e6aa754f12bc311af6f1e` against `development` base `f99c3b6207448d3d307d8da6f1838efc48b6ffbd`. Artifact `v3-candidate-release-proof` `9364480065` (`sha256:7949e975ee85b09fca3c7f71fa77477d5f6339a4655cfb3423ae5dc635065442`) contains a G19 artifact with `status: PASS`, `failures: []`, empty clean-start state, PostgreSQL 18, three non-superuser runtime LOGINs with exactly one intended membership each, secrets redacted and all representative vertical/queue/worker/recovery nodes PASS. The same run passed 466/466 canonical PostgreSQL tests, all concurrency-stability rounds, order-independence, mutation probes and G18. The final manifest reports `evidence_status: VALID`; `release_status` remains correctly `NOT_READY` because G17 and G20 are unresolved.

## 3. Current execution order

The remaining work must proceed in this dependency order:

```text
freeze the candidate
        ↓
G17 final 0001_initial + structural/behavioral equivalence
        ↓
rerun any proof affected by the frozen baseline / initial reconciliation
        ↓
G20 exact-head final release manifest
        ↓
development → main
        ↓
release/tag from the proven commit
```

This ordering is intentional. G18 has closed the release-level adversarial/failure envelope and G19 has closed the fresh production-like construction/runtime envelope. Candidate freeze is therefore the next dependency. Generating `0001_initial` before the freeze checkpoint would make it ambiguous which candidate semantics the baseline is supposed to reproduce.

## 4. G18 — unified adversarial/failure suite

G18 is **PASS** on implementation head `a08ddb00b52d7405e9eb5d972a1439eee52c7190`.

### 4.1 Required families

The unified proof requires and now passes exactly six families:

1. **Attack/security** — cross-tenant isolation, foreign references, missing tenant context, privilege escalation and opaque authorization/reference behavior.
2. **Race/concurrency** — every release-critical R01–R29 row maps to deterministic executable evidence with real PostgreSQL serialization where required.
3. **Crash/recovery** — authoritative-commit boundaries, durable claims, external success before local finalization, lease loss and process-death reclaim/fencing.
4. **Retry/idempotency** — replay, fingerprint conflict, post-commit response loss, provider retry policy and durable retry/dead behavior.
5. **Order independence** — the canonical release suite passes independently of execution ordering/state leakage.
6. **Mutation probes** — representative dangerous weakenings are killed by the release proof.

### 4.2 Race-matrix closure

The former PARTIAL rows R01, R02, R09 and R25–R29 are now `PASS` in `v3-race-matrix.md`. Exact current evidence already existed for R01, R09, R25, R28 and R29. G18 added deterministic PostgreSQL proof for the genuine gaps:

- R02 — Hold confirmation blocked across authoritative wall-clock expiry is rejected without promoted Reservation/capacity consumption;
- R26 — direct Booking versus foreign SlotOffer/Hold is forced through both shared-root winner orders with exactly one capacity owner and no orphan speculative state;
- R27 — a foreign shared-capacity booking can win against a conflicting reschedule while the losing reschedule rolls back and preserves the original Reservation/claim graph.

No race was promoted from invariant status by inference. The emitted G18 artifact requires an exact R01–R29 inventory and fails if any registry row, owner or required collected node is missing/non-PASS.

### 4.3 G18 artifact and manifest contract

`scripts/release/prove_v3_adversarial_failure.py` emits `.phase6/v3-adversarial-failure-proof.json` after the canonical PostgreSQL suite, concurrency stability, order independence and mutation probes. `scripts/release/build_v3_evidence_manifest.py` makes the artifact mandatory and invokes `validate_v3_adversarial_failure_artifact.py` by explicit sibling path so both script execution and architecture-test module loading use the same validator contract.

The semantic validator rejects malformed or lying top-level PASS payloads by checking the exact six-family inventory, exact R01–R29 inventory, expected/observed cardinalities, required supporting artifact set, family/race statuses and missing/failure fields. Architecture tests protect both the validator semantics and CI/manifest wiring.

### 4.4 G18 exit evidence

CI #1166 (`32242214119`) is the exact-head closure run for implementation head `a08ddb00b52d7405e9eb5d972a1439eee52c7190`. It passed Python quality/architecture, repeated PostgreSQL 18 V3 bootstrap, observability, PostgreSQL 18 V2 history and the PostgreSQL 18 V3 candidate proof. The candidate proof recorded:

- 463/463 canonical PostgreSQL tests PASS;
- three concurrency-stability rounds of 96/96 tests PASS;
- 463/463 order-independence tests PASS;
- mutation probes PASS;
- G18 artifact 6/6 families PASS and 29/29 races PASS;
- `registry_non_pass: []`, `missing_evidence: []`, `failures: []`;
- final evidence manifest `evidence_status: VALID`;
- final `release_status: NOT_READY`, correctly reflecting unresolved G17/G19/G20 at that historical head.

Artifact `9361488628` is bound by GitHub to that head with digest `sha256:1778a081977a4d92208dc37af27f2c9c6a997b15f5a607824dbf3939ac2ade16`.

The documentation promotion that records this PASS must itself survive exact-head canonical CI before PR #68 is merge-authoritative. If later freeze/baseline work changes an executable input relevant to G18, the affected proof must be regenerated rather than inherited from this historical head.

## 5. G19 — fresh production-like bootstrap

G19 is **PASS** on implementation head `b6985be7ecd229da1c5e6aa754f12bc311af6f1e`.

The proof starts from an empty PostgreSQL 18 environment and demonstrates:

- migration/bootstrap authority creates the database objects and runtime role groups;
- exactly three real LOGINs for app, worker and trusted admin have the intended flags and exactly one intended membership each;
- the application executes representative public verticals through the app-role session path;
- the worker uses distinct worker-control and domain application session factories and identities;
- representative ScheduledAction/queue/worker work executes under production-style roles;
- restart/crash/reclaim behavior works in the fresh environment;
- credentials remain confined to ephemeral `.ci/` material and the `.phase6/` evidence contains sanitized metadata only;
- the complete canonical release suite runs successfully against the freshly constructed environment;
- nested scratch proofs strip outer runtime DSNs and role bindings, preventing cross-database contamination.

`scripts/release/prove_v3_production_like_bootstrap.py` emits `.phase6/v3-production-like-bootstrap.json`, and `validate_v3_production_like_bootstrap_artifact.py` semantically validates the exact proof contract. The canonical evidence manifest treats the artifact as mandatory rather than trusting a top-level PASS string.

CI #1178 (`32250520126`) passed every required job on exact implementation head `b6985be7ecd229da1c5e6aa754f12bc311af6f1e` against `development` base `f99c3b6207448d3d307d8da6f1838efc48b6ffbd`. The candidate run recorded 466/466 canonical PostgreSQL tests PASS, all concurrency-stability rounds PASS, order-independence PASS, mutation probes PASS and G18 PASS. The G19 artifact reports `status: PASS`, `failures: []`, clean-start emptiness, PostgreSQL 18, all three restricted runtime LOGINs and all representative HTTP/queue/worker/recovery nodes PASS. The final manifest reports `evidence_status: VALID`.

Artifact `v3-candidate-release-proof` `9364480065` is bound by GitHub to that exact head with digest `sha256:7949e975ee85b09fca3c7f71fa77477d5f6339a4655cfb3423ae5dc635065442`. `release_status` remains correctly `NOT_READY` because G17 and G20 are unresolved.

This documentation promotion must itself survive canonical exact-head CI before PR #69 becomes merge-authoritative. If candidate freeze or G17 baseline construction changes an executable release input relevant to G19, the affected proof must be regenerated rather than inherited from this historical head.

## 6. Candidate freeze

G18 and G19 now pass, so the V3 candidate can proceed to the explicit freeze checkpoint for baseline construction.

At freeze, changes to these surfaces become release-invalidating unless explicitly reviewed as blocker fixes:

- `migrations/sql/v3_candidate/` semantics;
- constraints, triggers, functions, RLS and grants;
- runtime role contract;
- public `/v1/` surface, capability registry and machine errors;
- worker lease/fencing protocols;
- representative hot-path indexes;
- release-proof registries.

A blocker fix after freeze must identify which gates/fingerprints it invalidates and rerun them. “Documentation-only” must not be used to conceal an executable release-input change.

## 7. G17 — final `0001_initial` equivalence

G17 intentionally occurs after the candidate survives G18/G19.

Required work:

1. generate the final clean V3 `0001_initial` from the frozen candidate semantics;
2. build database A from the complete candidate chain;
3. build database B from the final initial migration path;
4. compare structural catalogs including schemas, relations, columns, types, constraints, indexes, functions, triggers, policies, grants, roles, sequences, extensions and relevant views;
5. execute representative behavioral proofs against both databases, including tenant isolation, capacity/Booking, Queue/Waitlist/SlotOffer, workers, ProviderEvent/Communications and shared capacity;
6. produce deterministic fingerprints and a machine-readable equivalence artifact;
7. keep the candidate construction history until equivalence is proven.

After V3 ships, the released `0001_initial` becomes immutable history. Later schema changes use new migrations.

## 8. Final rerun after baseline construction

Structural equivalence alone is not sufficient release authority. If construction/freeze reconciliation changes any executable input, rerun the affected gates on the exact final candidate. At minimum review whether G06, G09/G10, G13, G14, G15, G16, G18 and G19 require regeneration.

The final `development → main` release proof must refer to the exact tree that is actually promoted.

## 9. G20 — final release manifest

G20 is the last gate and the only point at which `release_status` may become `READY`.

The final artifact must bind at least:

- exact source/head/tree/tested commit identities;
- PostgreSQL and Python/runtime environment;
- migration and schema fingerprints;
- final `0001_initial` equivalence fingerprint;
- public API/OpenAPI/capability/error fingerprints;
- all mandatory evidence artifacts and their digests;
- gate registry G01–G20;
- clean-tree status;
- zero missing artifacts and zero validation errors.

`release_status: READY` is valid only when G01–G20 are all `PASS` in the same final release evidence set.

## 10. Promotion discipline

The final promotion sequence is:

1. exact-head canonical CI on the final `development` candidate;
2. inspect the final evidence bundle rather than trusting green checks alone;
3. require G01–G20 `PASS`, manifest `VALID`, complete artifact set and `release_status: READY`;
4. require branch up-to-date and review conversations resolved;
5. merge `development → main` without bypassing branch/ruleset requirements;
6. verify the resulting `main` commit/tree identity;
7. tag/release only the commit whose release evidence is authoritative, rerunning evidence if the promotion creates a different executable tree.

## 11. Explicit non-goals during closure

Until V3 is released, do not add unrelated product breadth. In particular, Phase 6 should not grow Request Engine into a CRM/ERP/accounting/PSP/PBX, universal workflow engine, workforce optimizer, GPS/delivery platform, generic agent framework, advanced payment domain or generalized capacity-pool/federation product.

Correctness fixes exposed by G18/G19 are allowed. New feature scope that changes the target should be deferred until after the V3 baseline unless the release guarantee cannot be made correct without a narrowly scoped change.

## 12. Definition of done

V3 is release-ready only when all of the following are true together:

- G01–G20 are `PASS`;
- `V3-I01..V3-I66` remain reconciled to executable evidence;
- every release-critical race in `v3-race-matrix.md` is `PASS` with deterministic evidence;
- final `0001_initial` is structurally and behaviorally equivalent to the frozen candidate;
- fresh production-like bootstrap passes with real runtime roles and app/worker processes;
- public API/capability/error freeze remains unchanged or intentionally versioned;
- representative query plans remain valid on the final schema;
- no P0/P1 release blocker remains;
- the exact-head evidence manifest is `VALID`, complete and clean;
- `release_status` is `READY` for the exact tree promoted to `main`.