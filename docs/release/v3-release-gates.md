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

At the Phase 6A baseline, no gate was promoted to `PASS` merely because CI configuration existed. The first complete Phase 6 execution baseline was CI run `#433` on commit `13a6d57495c12c0a497aa265d81a30ca00ee0e05`.

## Executed evidence

CI `#433` established the original release-proof baseline for G01-G04:

- Ruff lint passed;
- Ruff formatting passed;
- Pyright passed;
- all architecture tests passed;
- all module unit tests passed;
- the PostgreSQL 18 repeated-bootstrap proof passed;
- the V3 candidate applied cleanly;
- the schema fingerprint generated successfully;
- the blocking catalog audit passed;
- all then-current V3 PostgreSQL invariant/race/vertical tests passed;
- the candidate release-proof artifact uploaded successfully.

The same release cycle discovered and fixed a real deny-by-default defect before that green baseline: application functions still inherited PostgreSQL's default `PUBLIC EXECUTE`. Candidate migration `021-release-privilege-hardening.sql` and dedicated DB tests enforce the intended boundary.

Phase 6I adversarial tenant work was strengthened in CI `#462` on commit `63d2d5004cd74800cb41d08f293e6aa5523f0a70` with direct `request_engine_app` RLS proof, cross-tenant/nonexistent identifier equivalence, HTTP Booking/Request/Queue/Waitlist attacks, operator-override tenant binding, and a real Request submit versus Representation revocation race.

### Post-feature integration rebaseline

After Production Worker Assembly, ReservationAccess/Delivery and Cross-Tenant Shared Capacity were integrated, PR #52 exact-head CI `#847` (`31983843624`) passed on head `31b2d51ccdb6e5ee9fa8b2c7f004359cc764048b`. The merge commit on `development`, `a5d6221e6cb3fd69a340dd0cccbe493ef7179c29`, has the same Git tree `e36eb2e717bc6e28927b2d444f148807cfa8ee52` as that proven head.

The CI #847 `v3-candidate-release-proof` artifact reports:

- `evidence_status: VALID`;
- `release_status: NOT_READY`;
- `artifact_set_complete: true`;
- clean tested working tree and zero manifest validation errors;
- 340 collected release tests across 78 expected files;
- reverse-order execution: 340 passed;
- concurrency stability: 3/3 rounds passed, each with 47 PostgreSQL/concurrency tests;
- schema fingerprint, catalog audit, mutation probes, candidate initial-equivalence artifact, test-quality artifact and worker query-plan artifact present.

The artifact intentionally preserves the gate statuses below. A valid candidate evidence bundle is not a release-ready V3 baseline. `docs/release/v3-post-merge-rebaseline.md` records the current repository point and ordered closure work.

### Deterministic race closure

The current race-closure change set adds release-level interleaving tests for R08, R17, R18, R19 and R22 using production-style `request_engine_app` logins for authoritative domain transactions and the worker login where ScheduledAction claiming is technical worker work. The tests deliberately overlap real PostgreSQL transactions or, for R19, simulate a transport failure only after the real ASGI command has completed. They assert final state/cardinality rather than merely checking for exceptions.

This closes the `TO VERIFY`/`MISSING` classification of those individual races, but it does **not** promote their owning gates to `PASS`. G08 still needs the final complete recovery vertical; G11 still needs lost-response/idempotency coverage across the frozen sensitive-command inventory; G13 still needs the wider provider event disorder/late/unknown/crash matrix; and G18 still lacks the unified release adversarial artifact.

## Gate matrix

| Gate | Release claim | Status | Existing evidence | Required proof before PASS | Primary phase |
|---|---|---|---|---|---|
| G01 | Static quality | PASS | CI #847: canonical Python quality job green on the integrated tree | Keep mandatory in final release CI | 6A/6P |
| G02 | Architecture boundaries | PASS | CI #847: complete architecture fitness suite green on the integrated tree | Keep mandatory in final release CI | 6A/6P |
| G03 | Unit/domain logic | PASS | CI #847: complete module/unit suite green on the integrated tree | Keep mandatory in final release CI | 6A/6P |
| G04 | Fresh PostgreSQL bootstrap | PASS | CI #847: dedicated PostgreSQL 18 repeated clean candidate bootstrap passed | Preserve proof until final bootstrap is replaced by `0001_initial` in 6O | 6B |
| G05 | Schema integrity | PARTIAL | CI #847 fingerprint/catalog audit, current DB/vertical suite, mutation probes and expanded cross-tenant/SlotOffer integrity tests are green; race closure adds deterministic source-event/provider/reminder/idempotency interleavings | Complete every critical invariant proof and execute the final release baseline after the candidate stops changing | 6B/6C/6D |
| G06 | Tenant isolation | PARTIAL | Real least-privileged app LOGIN proof exists in E2E/integration; direct RLS/fail-closed DB tests, foreign-vs-nonexistent controls, HTTP Booking/Request/Queue/Waitlist attacks and authority races are collected by CI #847 | Close the remaining protected execution-surface attack inventory and every material subject-authority/revocation race required by the frozen contract; rerun on the final release baseline | 6I |
| G07 | Booking vertical | PARTIAL | `v3_booking_core`, `v3_booking_commitments`, Reservation lifecycle, ReservationAccess/Delivery and adversarial E2E journeys run in the current candidate suite | Demonstrate the frozen release appointment journey end to end, including required lifecycle communications/completion semantics, under the final release gate | 6K |
| G08 | Slot recovery | PARTIAL | SlotOffer terminal races plus R08 duplicate released-slot consumers now prove one source-event Opportunity/Hold/Offer chain under concurrent app transactions | Run the complete frozen recovery vertical and final candidate race suite after remaining correctness work stops changing the flow | 6D/6K |
| G09 | Worker claim race | PARTIAL | DB/integration worker runtime suites, production worker assembly, worker soak/fuzz tests and claim fencing are in CI #847 | Deterministic multi-worker ownership/fairness proof at representative increasing concurrency/backlog | 6F |
| G10 | Worker crash recovery | PARTIAL | expired-lease, stale-finalization, process crash recovery, communication fencing and poison/replay evidence exist | Complete claim-crash-reclaim and external-side-effect-success / local-finalization-crash release proof across relevant work families | 6F |
| G11 | Idempotency | PARTIAL | idempotency contract/error tests and PostgreSQL primitives plus R19 committed Booking/response-loss/same-key HTTP replay with one Reservation/claim/outbox effect | Extend lost-response-after-commit proof across the frozen sensitive network-retryable command inventory and rerun on the final baseline | 6E |
| G12 | Optimistic concurrency | PARTIAL | Request/booking/queue revision contracts plus real Reservation cancel-vs-reschedule revision race exist | Real concurrent writer proof for every mutable public aggregate requiring revisions | 6E |
| G13 | Provider events | PARTIAL | simultaneous R17 ProviderEvent ingestion proves one provider identity and payload conflict; R18 proves ProviderEventRouter → Booking semantic-command ordering against business cancellation; terminal stale-worker/dead-letter support also exists | Complete duplicate/out-of-order/late/unknown/crash processing matrix and final provider-event vertical | 6J |
| G14 | Runtime privilege model | PARTIAL | Real app/worker/admin LOGIN tests inspect role flags, table/function ACLs and deny forbidden `SET ROLE`; catalog audit and private shared-capacity privilege tests are green | Complete the explicit negative DDL/BYPASSRLS/remaining SECURITY DEFINER execution matrix for every runtime role on the final baseline | 6I |
| G15 | Query-plan/index proof | MISSING | CI #847 contains a worker query-plan artifact proving `provider_events_due_idx` for one provider-event due query; this is intentionally insufficient for the gate | Representative production-like datasets plus stored `EXPLAIN (ANALYZE, BUFFERS)` evidence for all release hot paths and explicit final index decisions | 6H |
| G16 | API contract freeze | PARTIAL | Phase 5 capability/OpenAPI architecture tests plus current E2E public-surface contract tests exist | Stable OpenAPI snapshot, machine-readable error matrix and capability consistency gate after correctness changes stop moving public semantics | 6G/6P |
| G17 | Migration equivalence | MISSING | Candidate chain and candidate-side `0001_initial.candidate.sql`/initial-equivalence artifacts exist; no blessed release initial migration exists | Candidate fingerprint equals final `0001_initial` fingerprint and the same behavioral suite passes against both | 6M/6N |
| G18 | Adversarial/failure proof | MISSING | Individual race/fencing/chaos/soak/mutation tests now include the formerly missing R08/R17/R18/R19/R22 proofs, but no complete release adversarial gate closes the registered failure inventory | Unified replay, temporal, deadlock, deterministic failure-injection and release-critical race suite with explicit coverage mapping | 6L |
| G19 | Fresh release environment | PARTIAL | PostgreSQL 18 candidate and repeated-bootstrap jobs start from empty CI databases | Final release environment bootstraps using only `0001_initial`, production-style runtime roles/config and then passes the complete release suite | 6O |
| G20 | Reproducible release artifact | MISSING | Candidate evidence manifest is versioned, hash-bound and VALID, but its own `release_status` is `NOT_READY` and it is not the final V3 artifact | Final release manifest with schema/OpenAPI/config/runtime fingerprints, all G01-G20 PASS, frozen candidate identity and release soak result | 6Q/6R/6S |

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its proof artifact. If a proof is later weakened, removed, skipped, or no longer runs in release CI, the gate must return to `PARTIAL` or `BLOCKED`.

A previous feature-head artifact may justify reconciling what evidence exists when its Git tree is identical to the integrated tree, but it is not the final promotion artifact for `development -> main`. Final release proof must be regenerated against the frozen release candidate identity after all release-affecting changes are complete.

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

The original Phase 6A inventory and post-feature rebaseline are complete. The deterministic race-closure change set removes the remaining `TO VERIFY`/`MISSING` classifications for R08/R17/R18/R19/R22 while deliberately leaving their broader owning gates incomplete. The next correctness work is command-family idempotency/optimistic-concurrency closure, followed by remaining privilege, vertical, worker/provider and performance/release-construction gates. `0001_initial` and final index freeze remain blocked.
