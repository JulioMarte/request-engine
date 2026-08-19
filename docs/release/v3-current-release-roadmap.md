# Request Engine V3 — current release roadmap

Status: **active operational roadmap for Phase 6 V3 Freeze & Release Proof**.

Repository reference points for this roadmap:

- integration branch: `development`;
- last implementation-bearing gate closure before documentation reconciliation: `3281075bdc5e19997a3ba8120fa6a275e7ee5ab1` (PR #65, G16 public API contract freeze);
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
| G18 | MISSING | existing attack/race/crash/retry/order/mutation evidence has not yet been composed into one mandatory unified release proof |
| G19 | PARTIAL | strong bootstrap/runtime-role evidence exists, but the final fresh production-like app+worker release bootstrap is not closed |
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

The invariant registry being complete does **not** imply that every broader release-race row is already `PASS`: invariant ownership and race-matrix closure are separate proof dimensions. G18 must reconcile both without silently promoting a race from related invariant evidence.

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

## 3. Current execution order

The remaining work must proceed in this dependency order:

```text
G18 unified adversarial/failure proof
        ↓
G19 fresh production-like bootstrap
        ↓
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

This ordering is intentional. Generating `0001_initial` before G18/G19 would freeze a candidate that has not yet survived the complete release-level failure envelope or the final production-like bootstrap.

## 4. G18 — unified adversarial/failure suite

G18 is the **next active gate**.

The repository already contains substantial adversarial evidence. The missing requirement is a single release-proof family that proves coverage is complete, mandatory and machine-readable instead of inferred from scattered tests.

### 4.1 Required families

The unified proof must include at minimum:

1. **Attack/security**
   - cross-tenant reads/writes;
   - foreign Party/Resource/Reservation/Queue/Waitlist references;
   - missing tenant context;
   - privilege escalation / forbidden role transitions;
   - opaque authorization/reference behavior.
2. **Race/concurrency**
   - every release-critical row in `v3-race-matrix.md` mapped to deterministic executable evidence;
   - independent PostgreSQL sessions and deliberate barriers where DB serialization is the guarantee;
   - final state and cardinality assertions, not exception-only assertions.
3. **Crash/recovery**
   - crash before/after authoritative commit;
   - crash after durable claim;
   - external success before local finalization;
   - lease loss during I/O;
   - process death / reclaim / stale-worker fencing.
4. **Retry/idempotency**
   - same key + same payload replay;
   - same key + different fingerprint rejection;
   - post-commit response loss;
   - retryable/non-retryable provider outcomes;
   - durable work retry/dead behavior.
5. **Order independence**
   - release tests do not depend on execution order or leaked database/process state.
6. **Mutation probes**
   - representative dangerous weakenings of tenant checks, revision checks, fencing, terminal-state protection or relational invariants are killed by the release suite.

### 4.2 Race-matrix debt that G18 must resolve

As of this documentation audit, the canonical table in `v3-race-matrix.md` still marks these rows `PARTIAL`:

- R01 — acquire capacity vs acquire same capacity;
- R02 — confirm Hold vs wall-clock expiry/expiry cleanup;
- R09 — CallNext vs CallNext;
- R25 — cross-tenant shared-root commitment vs commitment;
- R26 — direct Booking vs cross-tenant Hold/SlotOffer;
- R27 — reschedule vs foreign shared-capacity commitment;
- R28 — binding activation/revocation vs live claim creation;
- R29 — inverse multi-Resource/multi-shared-root acquisition including simultaneous reschedules.

This is **not** permission to assume those races are defective, nor permission to promote them because related invariants are `PASS`. G18 must inspect the current executable tests and do one of two things per row:

1. prove the exact race claim is already completely covered and promote the row with explicit evidence; or
2. add/fix the missing deterministic proof and only then promote it.

Until that reconciliation happens, G18 cannot claim a complete race family.

### 4.3 G18 artifact

Add one mandatory machine-readable artifact, e.g. `.phase6/v3-adversarial-failure-proof.json`, containing:

- overall status;
- family status and inventory;
- mapped test/proof owners;
- expected versus observed counts;
- missing evidence;
- failures;
- environment/source metadata.

`build_v3_evidence_manifest.py` must reject a missing, malformed or non-PASS G18 artifact.

### 4.4 G18 exit condition

G18 may move to `PASS` only when one exact head has:

- every required adversarial family PASS;
- every release-critical race row either PASS with explicit current evidence or explicitly removed from release scope by a normative contract change (not by test convenience);
- zero unmapped release-critical race/proof obligations;
- zero validation errors;
- canonical CI green;
- complete clean-tree candidate evidence;
- the unified G18 artifact semantically validated by the release manifest.

A failing G18 test is evidence of a product/release defect until demonstrated otherwise. Do not weaken invariants or remove adversarial coverage merely to make the gate green.

## 5. G19 — fresh production-like bootstrap

G19 follows G18.

The current repository already has strong clean PostgreSQL bootstrap and runtime-role tests, which is why G19 is `PARTIAL`, not `MISSING`. G02's repeated candidate-construction proof is necessary but not sufficient for G19. What is still absent is the final release-shaped construction and runtime exercise.

The G19 proof must start from an empty PostgreSQL 18 environment and demonstrate:

- migration/bootstrap authority creates the database objects and runtime roles;
- real LOGINs for app, worker and trusted admin have the intended flags and no accidental authority;
- the application starts using the app-role session path and executes representative public verticals;
- the worker starts with distinct worker control and domain application session factories;
- ScheduledAction, OutboxMessage and ProviderEvent work can be claimed and processed under production-style roles;
- restart/crash/reclaim behavior works in the fresh environment;
- no test/bootstrap-only superuser privilege leaks into the runtime path;
- the release suite can run against the freshly constructed environment.

G19 must emit a mandatory machine-readable production-bootstrap artifact and the release manifest must validate it.

## 6. Candidate freeze

Only after G18 and G19 pass should the V3 candidate be considered frozen for baseline construction.

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
