# Request Engine V3 — current release roadmap

Status: **active operational roadmap for Phase 6 V3 Freeze & Release Proof**.

Repository reference points:

- integration branch: `development`;
- frozen post-G19 candidate source: `4311200a8a9d8dfa18340c0eba5dff0cfdb47803`;
- G17 implementation head proven by canonical CI: `f3c93fed8f66b438d1729d113e6f568d5dcb3497`;
- G17 registry-promotion head proven by canonical CI: `443d3aaa9047f5e76c0bc4d7741ce0dd69e22778`;
- PostgreSQL target: PostgreSQL 18;
- release status: `NOT_READY` because G20 is still `MISSING`.

Commit identities above are provenance checkpoints, not a claim that `development` will forever equal those SHAs. Executable evidence is authoritative only for the exact commit/tree that produced it. `v3-release-gates.md` is the canonical gate registry; this roadmap defines current ordering and release discipline.

Historical Phase 6 planning/rebaseline documents remain useful design history, but they do not override this roadmap or the executable gate registry.

## 1. Current gate state

| Gate range | State | Meaning |
|---|---:|---|
| G01–G16 | PASS | executable proof and registry closure exist; canonical reruns continue to protect them on the release branch |
| G17 | PASS | the frozen candidate and reviewed `0001_initial` are structurally, behaviorally and runtime-equivalent with explicit source/tested provenance |
| G18 | PASS | unified attack/race/crash/retry/order/mutation evidence is mandatory and semantically validated |
| G19 | PASS | fresh PostgreSQL 18 bootstrap and production-style runtime role proof are mandatory and semantically validated |
| G20 | MISSING | no final exact-head release proof has yet promoted all G01–G20 to one `READY` evidence set |

`release_status` remains `NOT_READY` until G20 closes on the exact final candidate.

## 2. Frozen candidate and G17 closure

The V3 candidate was frozen only after G18 and G19 passed. The freeze locks the exact 43-file candidate migration inventory, the post-G19 source commit/tree, migration Git blobs, the candidate apply script and the canonical schema-fingerprint tool. Any executable blocker fix after freeze must identify and rerun the evidence it invalidates.

G17 is now closed by an independent two-construction proof:

1. database A is created from `template0` and built from the complete frozen 43-file candidate chain;
2. database B is created independently from `template0` and built through `alembic upgrade head` using the reviewed `0001_initial` baseline;
3. both databases are fingerprinted with the canonical PostgreSQL 18 catalog fingerprint;
4. the same canonical V3 PostgreSQL selector is executed independently against both databases;
5. the initial path is provisioned with production-shaped app/worker/admin runtime identities;
6. a machine-readable G17 artifact binds baseline digest, structural proof, behavioral inventory, runtime proof, candidate freeze and exact source/tested provenance;
7. an independent semantic validator rejects malformed, stale or ambiguous PASS artifacts.

The reviewed baseline SQL is fixed at SHA-256:

`502c98fcce5b5480a3e8f34804ce3a61495e679811a3ac6d0be4872107c34c88`

The canonical structural fingerprint for both construction paths is:

`8345eec114eb4af2184c0796debece536e27d7fb4851f77811b2721df1afd877`

The canonical behavioral proof executes **466 tests on each path**, with zero failures/errors/skips and identical sorted test inventories. The test-inventory SHA-256 is:

`39601a26ac608d86b86e8338ccfbbbe32d9c1d4b86769f6a5ab4230b45118b4d`

Canonical CI #1224 (`32275821530`) proved the implementation on source head `f3c93fed8f66b438d1729d113e6f568d5dcb3497`; artifact `9374338903` has digest `sha256:0fe74eb5190915afea983a29d623eb715651544565da75b9ad7678de1f2dce23`.

Canonical CI #1225 (`32282849691`) then proved the G17 registry promotion on source head `443d3aaa9047f5e76c0bc4d7741ce0dd69e22778`. Every required job passed. Artifact `9376847945` has digest `sha256:8ad888768e6aa430598d485d8d91cb8a93245ba6590405d2aef6f2c688354373` and records:

- source head `443d3aaa9047f5e76c0bc4d7741ce0dd69e22778`;
- tested merge checkout `6c9647703447b255b9d8dc463655583840ad9f4b`;
- tree `d938b0e4a0ca2fc9b2c049a5a7193cf28c43a22c`;
- `working_tree_dirty: false`;
- `evidence_status: VALID`;
- G01–G19 `PASS`;
- G20 `MISSING`;
- `release_status: NOT_READY`.

The G17 artifact schema explicitly separates `source_head_sha` from `tested_sha`. The candidate freeze is tied to the tested checkout, preventing a PR merge-ref from being mislabeled as the source branch head.

After V3 ships, the released `0001_initial` becomes immutable migration history. Later schema changes must be append-only migrations.

## 3. What remains proven on the frozen release line

The canonical release pipeline continues to regenerate the evidence needed for the already-closed gates, including:

- candidate ordering and repeated clean bootstrap;
- V2 design-history preservation;
- Python quality, typing, security, dependencies and architecture fitness;
- V3-I01..V3-I66 invariant ownership and tenant/RLS isolation;
- Booking lifecycle and released-slot recovery;
- worker leasing/fencing, crash recovery and idempotency;
- ProviderEvent and Communications reconciliation;
- runtime privilege closure;
- representative-cardinality query-plan/index proof;
- public API/OpenAPI/capability/error freeze;
- R01–R29 adversarial/race/failure evidence;
- fresh production-like bootstrap with distinct app/worker/admin runtime identities.

G17 did not weaken or bypass any of these proofs. CI #1225 reran the canonical release pipeline after G17 registry promotion and all required jobs remained green.

## 4. Current execution order

The remaining work is intentionally narrow:

```text
merge G17 PR #70 into development
        ↓
create a dedicated G20 branch from post-G17 development
        ↓
implement independent exact-head final-release proof + validator
        ↓
canonical CI produces one VALID, complete, clean G01–G20 evidence set
        ↓
G20 PASS / release_status READY
        ↓
development → main
        ↓
verify promoted commit/tree
        ↓
tag/release only the proven tree
```

G20 must not be mixed into the G17 branch. The repository integration discipline requires one coherent gate per branch, and G20 must prove the post-G17 `development` candidate rather than inheriting PR #70's historical merge checkout as final release authority.

## 5. G20 — final exact-head release proof

G20 is the last gate and the only point at which `release_status` may become `READY`.

A simple edit from `G20=MISSING` to `G20=PASS` is **not** sufficient. G20 needs an independent machine-readable proof and semantic validator so release readiness cannot become a registry tautology.

The final proof must bind at least:

- exact source head, tested checkout and Git tree identities;
- expected integration base identity for the final release candidate;
- clean working-tree status;
- PostgreSQL and Python/runtime environment;
- frozen candidate migration-set identity;
- canonical schema fingerprint;
- reviewed `0001_initial` digest and G17 equivalence artifact;
- public API/OpenAPI/capability/error fingerprints;
- invariant, race and gate registry digests;
- every mandatory evidence artifact and its digest;
- semantic validation status for every mandatory evidence family;
- G01–G20 registry state;
- zero missing artifacts and zero validation errors.

The G20 validator must independently reject at least:

- source head different from `PHASE6_HEAD_SHA`;
- tested SHA different from `PHASE6_TESTED_SHA` or the actual checkout;
- dirty tree or inconsistent tree identity;
- missing/invalid evidence artifacts;
- a G17 artifact whose source/tested provenance does not match the same final run;
- baseline/schema/API fingerprint drift;
- any non-PASS gate;
- any manifest that claims `READY` without a valid G20 proof.

Avoid recursive self-hashing: the G20 proof may bind the digests of all underlying evidence and a provisional manifest/input set, but the final manifest must not require its own digest as an input to itself.

## 6. G20 implementation sequence

On a dedicated G20 branch from post-G17 `development`:

1. add the final-release proof producer and independent validator while G20 remains `MISSING`;
2. add architecture tests that falsify stale head/tested/tree provenance, missing artifacts, fingerprint drift, non-PASS gates and lying READY claims;
3. wire production of `.phase6/v3-final-release-proof.json` after all underlying evidence exists;
4. make the final manifest semantically validate that G20 artifact as mandatory release evidence;
5. only then promote the G20 registry row to `PASS`;
6. run canonical exact-head CI and inspect the uploaded evidence bundle, not just job status;
7. accept `release_status: READY` only if the final manifest is `VALID`, complete, clean and all G01–G20 gates are PASS on that exact source/tested/tree identity.

If implementing the G20 proof changes any executable release input, the affected earlier gates must be regenerated. A documentation/validator-only change does not excuse a failed canonical rerun.

## 7. Promotion discipline

The final promotion sequence is:

1. exact-head canonical CI on the final G20 candidate;
2. inspect the final evidence bundle and G20 artifact;
3. require G01–G20 `PASS`, manifest `VALID`, complete artifact set, clean tree and `release_status: READY`;
4. require branch up-to-date and review conversations resolved;
5. merge the G20 branch to `development`;
6. run/confirm authoritative release evidence on the exact `development` commit/tree that will be promoted;
7. merge `development → main` without bypassing branch/ruleset requirements;
8. verify the resulting `main` commit/tree identity;
9. tag/release only the commit whose release evidence is authoritative, rerunning evidence if promotion creates a different executable tree.

A green historical workflow is never sufficient for a different commit/tree.

## 8. Explicit non-goals during closure

Until V3 is released, do not add unrelated product breadth. In particular, Phase 6 must not grow Request Engine into a CRM/ERP/accounting/PSP/PBX, universal workflow engine, workforce optimizer, GPS/delivery platform, generic agent framework, advanced payment domain or generalized capacity-pool/federation product.

Correctness fixes exposed by release evidence are allowed. New feature scope that changes the target must be deferred unless the release guarantee cannot be made correct without a narrowly scoped fix.

## 9. Definition of done

V3 is release-ready only when all of the following are true together:

- G01–G20 are `PASS`;
- `V3-I01..V3-I66` remain reconciled to executable evidence;
- every release-critical R01–R29 race is `PASS` with deterministic evidence;
- final `0001_initial` remains structurally, behaviorally and runtime-equivalent to the frozen candidate;
- fresh production-like bootstrap passes with real runtime roles and app/worker paths;
- public API/capability/error freeze remains unchanged or intentionally versioned;
- representative query plans remain valid on the final schema;
- no P0/P1 release blocker remains;
- exact-head evidence is `VALID`, complete and clean;
- the independent G20 proof is valid for the same source/tested/tree identity;
- `release_status` is `READY` for the exact tree promoted to `main`.
