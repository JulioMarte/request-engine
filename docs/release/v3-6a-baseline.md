# Phase 6A baseline — V3 release proof

Status: **historical recorded baseline for Phase 6A**.

> This file is a point-in-time inventory from the start of Phase 6. Its gate statuses, invariant count, CI shape and "next executable step" are historical evidence only. For current execution use `v3-current-release-roadmap.md` and `v3-release-gates.md`. In particular, the current invariant registry extends through `V3-I66`, G01–G16 are integrated PASS, and G18—not 6B—is the next active implementation gate.

## Repository point

- branch: `phase-6-v3-freeze-release-proof`
- comparison base: `development`
- baseline commit: `5f05c14cf559b29f936262b2be991631b01801ac`
- branch delta at Phase 6 start: identical to `development`
- PostgreSQL release target already used by CI: PostgreSQL 18
- Python CI target: Python 3.13

No workflow run is attached to this Phase 6 branch baseline commit. Existing CI configuration is therefore inventory evidence, not a current Phase 6 PASS result.

## Candidate construction inventory

At this historical baseline, the V3 candidate contained 20 ordered SQL increments:

```text
001-foundation.sql
002-schema.sql
003-integrity.sql
004-worker-primitives.sql
005-read-access.sql
006-capacity-hardening.sql
007-contract-convergence.sql
008-tenant-party-authority.sql
009-party-authority-resolution.sql
010-party-authority-linearization.sql
011-idempotency-error-contract.sql
012-waitlist-foundation.sql
013-slot-offer-recovery.sql
014-reservation-lifecycle.sql
015-worker-runtime-hardening.sql
016-provider-event-dead-letter.sql
017-expired-lease-finalization-fence.sql
018-retry-finalization-fence.sql
019-trusted-execution-provenance.sql
020-durable-correlation.sql
```

`migrations/versions/` contained no V3 release initial migration. That was correct for 6A: migration collapse remained blocked until proof phases completed.

The historical V2/design chain remained separate under `migrations/sql/design_chain/`.

## CI inventory

At this historical baseline, `.github/workflows/ci.yml` had three jobs:

1. `python-quality`: Ruff lint, Ruff format, Pyright, architecture tests and module tests.
2. `postgres-v2-history`: applies the historical design chain on PostgreSQL 18.
3. `postgres-v3-candidate`: starts PostgreSQL 18 from a clean service, applies the V3 candidate, then runs DB and V3 integration suites.

The V3 candidate job included:

```text
tests/db
tests/integration/v3_first_vertical
tests/integration/v3_booking_core
tests/integration/v3_booking_commitments
tests/integration/v3_slot_offer_recovery
tests/integration/v3_reservation_lifecycle
tests/integration/v3_worker_runtime
```

This was a strong candidate baseline, but it was not yet a release proof because it did not independently prove deterministic repeated bootstrap, schema fingerprint equivalence, final runtime privilege negatives, representative query plans, candidate-versus-initial equivalence, or final release artifact reproducibility.

## Existing proof families at the 6A snapshot

The repository already contained useful evidence for work that the Phase 6 plan originally treated as future work:

- worker lease expiry and stale-finalization fencing;
- communication fencing;
- trusted execution provenance;
- ProviderEvent dead-letter infrastructure;
- retry/finalization fences;
- durable correlation;
- capability/OpenAPI architecture fitness tests;
- Request and booking/queue revision contract tests;
- idempotency error contract tests;
- tenant/Party authority tests;
- SlotOffer recovery and Reservation lifecycle verticals.

Phase 6 was required to extend these proofs rather than duplicate them under new names.

## Release blockers discovered at inventory level

The following bullets describe the historical 6A gap analysis. Many have since been closed and must not be read as current backlog.

### P0

- No deterministic repeated fresh-bootstrap/fingerprint proof existed yet.
- No release artifact mapped the then-current `V3-I01..V3-I61` vocabulary to completed executable evidence yet. The canonical registry later expanded to `V3-I01..V3-I66` and G05 is now PASS.
- Critical race evidence existed in several suites but was not complete against the release race matrix.
- Runtime-role and SECURITY DEFINER behavior still needed a complete adversarial privilege gate.
- Idempotency lacked a release-level timeout-after-commit retry matrix across sensitive commands.
- `0001_initial` did not exist and was required to remain blocked until the candidate was proven.

### P1

- Tenant-fair worker claiming was contractually defined but still required production-scale backlog benchmarking before freeze.
- Hot-path `EXPLAIN (ANALYZE, BUFFERS)` evidence and final index decisions did not yet exist as release artifacts.
- The API had Phase 5 OpenAPI fitness tests, but no final V3 snapshot/error-matrix freeze artifact yet.
- Full product flows were spread across vertical suites rather than one explicit release-vertical gate.
- CI still contained the V2 history job in the main release workflow and had not been reorganized for final V3 release gates.

### P2

- Candidate migration collapse, equivalence proof and final bootstrap were intentionally pending.
- Production configuration/runbooks, release manifest and soak-test evidence were pending.

## 6A decisions

1. `PASS` means executed current-branch evidence, not presence of code.
2. Canonical invariant semantics remain owned by `docs/v3/02-pre-sql-contract.md`.
3. Phase 6 release docs are proof inventories and must not create new product semantics.
4. Candidate SQL remained untouched during 6A.
5. `0001_initial` remained blocked.
6. Index freeze remained blocked until measured query-plan work.
7. New correctness fixes had to start from a failing proof and preserve the canonical owner boundary.

## Historical next step

The next step from the 6A snapshot was 6B: build a destructive, repeatable PostgreSQL 18 bootstrap proof and catalog assertion surface. That work is now complete and backs G02. The current next step is defined only by `v3-current-release-roadmap.md` and `v3-release-gates.md`.
