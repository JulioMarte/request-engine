# Request Engine V3 release gates

Status: Phase 6 release gate registry.

This file records release proof, not design intent. Canonical semantics remain in the owning V3 docs and ADRs.

The generated evidence manifest distinguishes a **valid candidate evidence bundle** from a
**release-ready baseline**. Artifact presence, hashes, semantic PASS results,
JUnit outcomes and source/tree binding can make candidate evidence `VALID`; the release
remains `NOT_READY` until every gate below is `PASS`. CI must never describe
artifact completeness as complete V3 release evidence.

## Status semantics

- `PASS`: current-branch executable evidence satisfies the gate.
- `PARTIAL`: useful implementation/tests exist, but release-level proof is incomplete or has not been executed for this baseline.
- `MISSING`: no release-level proof artifact exists yet.
- `BLOCKED`: proof cannot proceed because a known correctness defect blocks it.

At the Phase 6A baseline, no gate was promoted to `PASS` merely because CI configuration existed. The first complete Phase 6 execution baseline is CI run `#433` on commit `13a6d57495c12c0a497aa265d81a30ca00ee0e05`.

## Executed evidence

CI `#433` establishes the current release-proof baseline for G01-G04:

- Ruff lint passed;
- Ruff formatting passed;
- Pyright passed;
- all architecture tests passed;
- all module unit tests passed;
- the PostgreSQL 18 repeated-bootstrap proof passed;
- the V3 candidate applied cleanly;
- the schema fingerprint generated successfully;
- the blocking catalog audit passed;
- all current V3 PostgreSQL invariant/race/vertical tests passed;
- the candidate release-proof artifact uploaded successfully.

The same release cycle discovered and fixed a real deny-by-default defect before that green baseline: application functions still inherited PostgreSQL's default `PUBLIC EXECUTE`. Candidate migration `021-release-privilege-hardening.sql` and dedicated DB tests now enforce the intended boundary.

Phase 6I adversarial tenant work is additionally green in CI `#462` on commit `63d2d5004cd74800cb41d08f293e6aa5523f0a70`. That run executed 124 PostgreSQL/integration tests and added direct `request_engine_app` RLS proof, cross-tenant/nonexistent identifier equivalence, HTTP Booking/Request/Queue/Waitlist attacks, operator-override tenant binding, and a real Request submit versus Representation revocation race. This evidence intentionally does not promote G06 because the HTTP application harness still does not execute with a production login granted only `request_engine_app`, and protected worker/admin/function surfaces plus the remaining subject-scoped material-command races still need complete adversarial coverage.

## Gate matrix

| Gate | Release claim | Status | Existing evidence | Required proof before PASS | Primary phase |
|---|---|---|---|---|---|
| G01 | Static quality | PASS | CI #433: Ruff lint/format and Pyright all green | Keep mandatory in final release CI | 6A/6P |
| G02 | Architecture boundaries | PASS | CI #433: complete `tests/architecture` suite green | Keep mandatory in final release CI | 6A/6P |
| G03 | Unit/domain logic | PASS | CI #433: complete `tests/modules` suite green | Keep mandatory in final release CI | 6A/6P |
| G04 | Fresh PostgreSQL bootstrap | PASS | CI #433: dedicated PostgreSQL 18 repeated clean candidate bootstrap passed | Preserve proof until final bootstrap is replaced by `0001_initial` in 6O | 6B |
| G05 | Schema integrity | PARTIAL | fingerprint/catalog audit green in CI #433; current DB/vertical suite green | Complete critical constraint/invariant and race proof | 6B/6C/6D |
| G06 | Tenant isolation | PARTIAL | CI #462: direct app-role RLS/fail-closed tests plus adversarial Booking/Request/Queue/Waitlist HTTP coverage, foreign-vs-nonexistent checks, tenant-bound operator override, and authority/revocation evidence | Run application verticals with true least-privileged runtime login; complete worker/admin/function-surface attacks and remaining subject-scoped material-command races | 6I |
| G07 | Booking vertical | PARTIAL | `v3_booking_core`, `v3_booking_commitments`, first vertical | Release appointment flow including lifecycle communications and completion | 6K |
| G08 | Slot recovery | PARTIAL | `v3_slot_offer_recovery` | Full accept/decline/expiry/candidate race matrix and recovery vertical | 6D/6K |
| G09 | Worker claim race | PARTIAL | DB worker runtime and integration worker runtime suites | Deterministic multi-worker ownership proof at increasing concurrency | 6F |
| G10 | Worker crash recovery | PARTIAL | expired-lease, fencing and worker runtime tests | Claim-crash-reclaim plus crash-after-side-effect proof | 6F |
| G11 | Idempotency | PARTIAL | idempotency contract tests and candidate support | Command coverage plus timeout-after-commit retry proof | 6E |
| G12 | Optimistic concurrency | PARTIAL | Request/booking/queue revision architecture tests | Real concurrent writer proof for every mutable public aggregate requiring revisions | 6E |
| G13 | Provider events | PARTIAL | ProviderEvent platform code, dead-letter migration and worker routing | duplicate/out-of-order/late/unknown/crash processing matrix | 6J |
| G14 | Runtime privilege model | PARTIAL | catalog audit now passes after 021 removes implicit PUBLIC function execution | Negative DDL/BYPASSRLS/SET ROLE and SECURITY DEFINER tests as runtime roles | 6I |
| G15 | Query-plan/index proof | MISSING | worker contract explicitly requires production-scale fairness benchmark | Representative datasets plus stored `EXPLAIN (ANALYZE, BUFFERS)` evidence and index decisions | 6H |
| G16 | API contract freeze | PARTIAL | Phase 5 capability/OpenAPI architecture tests and product API contract | Stable OpenAPI snapshot, error matrix and capability consistency gate | 6G/6P |
| G17 | Migration equivalence | MISSING | candidate chain exists; `migrations/versions` has no initial release migration | candidate fingerprint equals `0001_initial` fingerprint and same suite behavior | 6M/6N |
| G18 | Adversarial/failure proof | MISSING | individual race/fencing tests exist but no release adversarial gate | Replay, temporal, deadlock and deterministic failure-injection suite | 6L |
| G19 | Fresh release environment | PARTIAL | PostgreSQL 18 candidate service starts from an empty CI service | Final release bootstrap from only `0001_initial` plus full suite | 6O |
| G20 | Reproducible release artifact | MISSING | candidate fingerprint/audit artifacts now exist, but no final V3 release manifest | Release manifest, schema/OpenAPI fingerprints, frozen config and tagged candidate | 6Q/6R/6S |

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its proof artifact. If a proof is later weakened, removed, skipped, or no longer runs in release CI, the gate must return to `PARTIAL` or `BLOCKED`.

## Candidate evidence versus release readiness

The Phase 6 candidate manifest validates the contents of every required CI artifact;
file presence alone is not success. Its `VALID` state is deliberately scoped to the
candidate CI artifact set and does not promote unfinished gates. Overall
`release_status` remains `NOT_READY` until every G01-G20 row above is `PASS`.

The required V3 candidate GitHub check also fails explicitly when any prerequisite
job fails, is cancelled or is skipped. `v3-test-isolation.md` owns the executable
isolation, evidence and aggregate-gate contract.

## Blocking severity

- `P0`: can violate tenant isolation, authoritative state, capacity correctness, idempotency, fencing, durable intent or release reproducibility. V3 cannot freeze.
- `P1`: can cause serious operational failure, starvation, unsafe privileges, unacceptable hot-path behavior or an unstable public contract. V3 cannot freeze without explicit resolution.
- `P2`: release packaging/operational completeness that must finish before 6S but does not imply an already-known domain correctness defect.

## Phase 6A exit condition

6A is complete: the registry, freeze scope, canonical invariant inventory, race matrix and baseline findings are versioned and are structurally checked by the architecture suite. Phase 6B is also proven for the candidate bootstrap path. Phase 6C tooling is green and now feeds the later 6N candidate-versus-initial equivalence proof.
