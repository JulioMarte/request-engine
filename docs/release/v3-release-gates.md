# Request Engine V3 release gates

Status: Phase 6 release gate registry.

This file records release proof, not design intent. Canonical semantics remain in the owning V3 docs and ADRs.

## Status semantics

- `PASS`: current-branch executable evidence satisfies the gate.
- `PARTIAL`: useful implementation/tests exist, but release-level proof is incomplete or has not been executed for this baseline.
- `MISSING`: no release-level proof artifact exists yet.
- `BLOCKED`: proof cannot proceed because a known correctness defect blocks it.

At the Phase 6A baseline, no gate is promoted to `PASS` merely because CI configuration exists. Commit `5f05c14cf559b29f936262b2be991631b01801ac` has no workflow run attached to this Phase 6 branch baseline.

## Gate matrix

| Gate | Release claim | Baseline status | Existing evidence | Required proof before PASS | Primary phase |
|---|---|---|---|---|---|
| G01 | Static quality | PARTIAL | `python-quality` config runs Ruff lint/format and Pyright | Green current-branch run | 6A/6P |
| G02 | Architecture boundaries | PARTIAL | `tests/architecture` and architecture CI step | Green current-branch architecture suite | 6A/6P |
| G03 | Unit/domain logic | PARTIAL | `tests/modules` and module CI step | Green current-branch unit suite with no unexplained skips | 6A/6P |
| G04 | Fresh PostgreSQL bootstrap | PARTIAL | PostgreSQL 18 candidate CI applies `apply_v3_candidate.sh` | Destructive empty-DB bootstrap repeated independently with catalog assertions | 6B |
| G05 | Schema integrity | PARTIAL | `tests/db/test_v3_candidate.py`, contract convergence and platform DB tests | Catalog audit plus complete critical constraint/invariant proof | 6B/6C/6D |
| G06 | Tenant isolation | PARTIAL | tenant authority DB tests and HTTP authority tests | Cross-tenant adversarial RLS/FK/function coverage for all sensitive surfaces | 6I |
| G07 | Booking vertical | PARTIAL | `v3_booking_core`, `v3_booking_commitments`, first vertical | Release appointment flow including lifecycle communications and completion | 6K |
| G08 | Slot recovery | PARTIAL | `v3_slot_offer_recovery` | Full accept/decline/expiry/candidate race matrix and recovery vertical | 6D/6K |
| G09 | Worker claim race | PARTIAL | DB worker runtime and integration worker runtime suites | Deterministic multi-worker ownership proof at increasing concurrency | 6F |
| G10 | Worker crash recovery | PARTIAL | expired-lease, fencing and worker runtime tests | Claim-crash-reclaim plus crash-after-side-effect proof | 6F |
| G11 | Idempotency | PARTIAL | idempotency contract tests and candidate support | Command coverage plus timeout-after-commit retry proof | 6E |
| G12 | Optimistic concurrency | PARTIAL | Request/booking/queue revision architecture tests | Real concurrent writer proof for every mutable public aggregate requiring revisions | 6E |
| G13 | Provider events | PARTIAL | ProviderEvent platform code, dead-letter migration and worker routing | duplicate/out-of-order/late/unknown/crash processing matrix | 6J |
| G14 | Runtime privilege model | PARTIAL | schema roles, RLS design and worker role contract | Negative DDL/BYPASSRLS/SET ROLE and SECURITY DEFINER tests as runtime roles | 6I |
| G15 | Query-plan/index proof | MISSING | worker contract explicitly requires production-scale fairness benchmark | Representative datasets plus stored `EXPLAIN (ANALYZE, BUFFERS)` evidence and index decisions | 6H |
| G16 | API contract freeze | PARTIAL | Phase 5 capability/OpenAPI architecture tests and product API contract | Stable OpenAPI snapshot, error matrix and capability consistency gate | 6G/6P |
| G17 | Migration equivalence | MISSING | candidate chain exists; `migrations/versions` has no initial release migration | candidate fingerprint equals `0001_initial` fingerprint and same suite behavior | 6M/6N |
| G18 | Adversarial/failure proof | MISSING | individual race/fencing tests exist but no release adversarial gate | Replay, temporal, deadlock and deterministic failure-injection suite | 6L |
| G19 | Fresh release environment | PARTIAL | PostgreSQL 18 candidate service starts from an empty CI service | Final release bootstrap from only `0001_initial` plus full suite | 6O |
| G20 | Reproducible release artifact | MISSING | no V3 release manifest/fingerprints yet | Release manifest, schema/OpenAPI fingerprints, frozen config and tagged candidate | 6Q/6R/6S |

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its proof artifact. If a proof is later weakened, removed, skipped, or no longer runs in release CI, the gate must return to `PARTIAL` or `BLOCKED`.

## Blocking severity

- `P0`: can violate tenant isolation, authoritative state, capacity correctness, idempotency, fencing, durable intent or release reproducibility. V3 cannot freeze.
- `P1`: can cause serious operational failure, starvation, unsafe privileges, unacceptable hot-path behavior or an unstable public contract. V3 cannot freeze without explicit resolution.
- `P2`: release packaging/operational completeness that must finish before 6S but does not imply an already-known domain correctness defect.

## Phase 6A exit condition

6A is complete when this registry, the freeze scope, the canonical invariant inventory, the race matrix and the baseline findings are versioned and structurally checked by the architecture suite. Gate promotion begins with fresh executable evidence after that baseline.