# Request Engine V3 — release closure and post-baseline roadmap

Status: **V3 Freeze & Release Proof complete; V3 baseline promoted to `main`; active development is post-baseline.**

Repository/release reference points:

- integration branch: `development`;
- frozen post-G19 candidate source: `4311200a8a9d8dfa18340c0eba5dff0cfdb47803`;
- post-G17 `development` base used for G20 work: `489c43d4bed0060540099746a47d9abf653de300`;
- final pre-promotion `development` source: `9e58368e4ff593c8537c07de09defaec198d2b55`;
- tested PR #72 promotion checkout: `0d1beea7c527fb5c3fc4bf37db29b04bf0a2d65f`;
- released `main` merge commit: `07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc`;
- released tree: `4243840442d9b03d731c67ac514b46b1ee7dea7f`;
- PostgreSQL target for V3 release proof: PostgreSQL 18.

PR #72 promoted the integrated V3 baseline from `development` to `main`. Its exact promotion evidence recorded G01–G20 `PASS`, `evidence_status: VALID`, `release_status: READY`, a clean tested checkout, the complete frozen candidate, zero validation errors, zero test-quality errors/warnings, and preserved G17 structural/behavioral/runtime equivalence.

`docs/release/v3-release-gates.md` remains the canonical gate registry. Historical Phase 6 planning/rebaseline documents remain useful design history, but they do not override this closure record, the gate registry, the frozen baseline, or executable evidence.

## 1. Final Phase 6 gate state

| Gate range | State | Meaning |
|---|---:|---|
| G01–G16 | PASS | candidate, architecture, invariants, security, runtime, performance and public-contract proof closed |
| G17 | PASS | frozen candidate and reviewed `0001_initial` are structurally, behaviorally and runtime-equivalent with explicit provenance |
| G18 | PASS | unified attack/race/crash/retry/order/mutation suite is mandatory and semantically validated |
| G19 | PASS | fresh PostgreSQL 18 bootstrap and production-style runtime-role proof are mandatory and semantically validated |
| G20 | PASS | independent exact-head final-release proof and validator bind the full evidence set and require `READY` |

**Phase 6 has no remaining release gate.** Future work is ordinary post-baseline product/architecture evolution subject to the same correctness, privilege, concurrency and evidence discipline.

## 2. Frozen candidate and `0001_initial`

The V3 candidate was frozen after G18 and G19. The freeze locks the 43-file candidate migration inventory, frozen source commit/tree, migration Git blobs, candidate apply script and canonical schema-fingerprint tool.

G17 independently constructs two PostgreSQL 18 databases:

1. database A from the complete frozen candidate chain;
2. database B through `alembic upgrade head` using the reviewed `0001_initial` baseline.

Both construction paths retained identical canonical structure and the same behavioral/runtime contract.

Reviewed baseline SQL SHA-256:

`502c98fcce5b5480a3e8f34804ce3a61495e679811a3ac6d0be4872107c34c88`

Canonical structural fingerprint:

`8345eec114eb4af2184c0796debece536e27d7fb4851f77811b2721df1afd877`

Canonical G17 behavioral proof: **466 tests on each construction path**, zero failures/errors/skips, with identical sorted test inventory SHA-256:

`39601a26ac608d86b86e8338ccfbbbe32d9c1d4b86769f6a5ab4230b45118b4d`

After release, `migrations/versions/0001_initial.py` is immutable production migration history. Future schema changes are append-only Alembic revisions. `migrations/sql/v3_candidate/` remains frozen release provenance rather than the normal post-release migration surface.

## 3. G20 closure

G20 deliberately avoids a registry tautology. The release pipeline is ordered as:

```text
underlying G01–G19 evidence
        ↓
preflight manifest (structurally NOT_READY)
        ↓
independent G20 proof
        ↓
independent G20 semantic validator
        ↓
final manifest
        ↓
READY only when evidence is VALID, G20 is valid, and G01–G20 are PASS
```

The G20 proof binds at least:

- source head, integration base, tested checkout and Git tree identities;
- clean working-tree state;
- PostgreSQL/Python runtime contract;
- frozen migration-set identity;
- schema and public API fingerprints;
- reviewed `0001_initial` digest and G17 equivalence;
- invariant/race/gate registry digests;
- every mandatory evidence artifact and its digest;
- semantic validation status for the mandatory evidence set;
- canonical test inventory;
- test-quality summary cross-checked against the actual quality artifact;
- all G01–G20 gate statuses.

The independent validator requires the exact G20 criteria inventory, rejects missing criteria or lying `PASS` payloads, and rejects any test-quality warning. Concurrency evidence used as release proof must observe real PostgreSQL overlap; scheduler-delay sleeps are not accepted as the synchronization mechanism for release-critical races.

## 4. Provenance checkpoints

CI #1235 (`32292875575`) on source head `921020052833628bf1061aaa25ecd595ba2d0439` was the first complete G20 READY checkpoint before final documentation/promotion reconciliation. It remains historical provenance, not authority for later commits.

The later promotion sequence corrected the release topology and produced the final `development → main` proof. PR #73 fixed a real proof-model defect: shallow-CI ancestry must prove that the frozen source is an ancestor of the **exact tested checkout**, not require an older `main` base to contain a freeze that occurred later on `development`.

PR #72 then tested promotion from:

- source `development@9e58368e4ff593c8537c07de09defaec198d2b55`;
- base `main@6f2d4c2b0d95ca5a881ae261f3f29d6897aea5c6`;
- tested merge candidate `0d1beea7c527fb5c3fc4bf37db29b04bf0a2d65f`;
- tested tree `4243840442d9b03d731c67ac514b46b1ee7dea7f`.

Its inspected release bundle recorded:

- candidate freeze `PASS` using tested-checkout ancestry;
- all 43 frozen migrations present;
- G01–G20 `PASS`;
- G20 12/12 required criteria true;
- `evidence_status: VALID`;
- `release_status: READY` / `release_ready: true`;
- complete artifact set;
- no missing artifacts or validation errors;
- test quality `PASS`, zero errors and zero warnings;
- G17 `PASS` with 466/466 behavioral tests on both construction paths.

PR #72 merged to `main` as `07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc`, whose tree is the same tested tree `4243840442d9b03d731c67ac514b46b1ee7dea7f`. That exact-tree identity is important: the merge produced the tree already proven by the promotion candidate rather than introducing an unproven executable tree.

## 5. Post-release development model

There is no longer a “finish Phase 6” queue. The normal flow is now:

```text
new requirement / correctness fix
        ↓
canonical contract / ADR update when semantics change
        ↓
implementation on current development
        ↓
new append-only migration if schema changes
        ↓
focused invariant/race/security/runtime proof
        ↓
repository CI / integration evidence
        ↓
merge to development
```

A future release promotion to `main` must again follow the repository's exact-tree evidence and branch rules. Historical V3 READY evidence must never be used to bless later changed code automatically.

## 6. Post-baseline migration discipline

From this point forward:

1. `0001_initial` is immutable;
2. the 43-file V3 candidate is frozen provenance;
3. production schema evolution occurs through new append-only Alembic revisions;
4. fresh bootstrap to head and supported upgrade paths must both be tested;
5. affected V3 invariants/races/privilege contracts remain regression obligations;
6. a later feature must not rewrite V3 history simply because no external production deployment happened to depend on the old development workflow;
7. any deliberate future re-baseline requires an explicit architectural/release decision rather than an informal cleanup.

## 7. Product-scope discipline after V3

V3 release closure does not expand Request Engine into a CRM/ERP/accounting/PSP/PBX, universal workflow engine, workforce optimizer, GPS/delivery platform, generic agent framework, advanced payment domain or generalized federation product.

New breadth must still be justified through a concrete capability and owner boundary. Existing deferred/incubating modules remain constrained until an accepted requirement activates them.

## 8. Definition of done — historical Phase 6

Phase 6 Freeze & Release Proof is complete because one exact V3 candidate achieved all of the following together:

- G01–G20 `PASS`;
- `V3-I01..V3-I66` reconciled to executable evidence;
- every release-critical R01–R29 race `PASS` with deterministic evidence;
- final `0001_initial` structurally, behaviorally and runtime-equivalent to the frozen candidate;
- production-like bootstrap through real app/worker/admin runtime roles;
- frozen public API/capability/error contract;
- representative query-plan evidence;
- no P0/P1 blocker in the release proof;
- exact-head evidence `VALID`, complete and clean;
- independent G20 proof valid for the same source/tested/tree identity;
- zero test-quality errors and warnings;
- final manifest `READY`;
- tested release tree promoted to `main`.

The repository should now describe V3 as a **released baseline**, not as a pre-baseline candidate waiting for `0001_initial` or promotion.
