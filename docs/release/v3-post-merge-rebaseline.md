# V3 post-merge release rebaseline

Status: active Phase 6 release-proof baseline after integration of Production Worker Assembly, ReservationAccess/Delivery and Cross-Tenant Shared Capacity.

## Repository point

- integration branch: `development`
- development commit: `a5d6221e6cb3fd69a340dd0cccbe493ef7179c29`
- development tree: `e36eb2e717bc6e28927b2d444f148807cfa8ee52`
- cross-tenant feature head merged by PR #52: `31b2d51ccdb6e5ee9fa8b2c7f004359cc764048b`
- exact-head CI used as integration evidence: run `#847` (`31983843624`)
- PostgreSQL release target: PostgreSQL 18
- Python CI target: Python 3.13

The merge commit and the exact feature head have the same Git tree. Therefore the code integrated into `development` is byte-for-byte the tree exercised by the final PR CI. The existing candidate evidence is still scoped to the PR/head identity, however, and must not be treated as the final release-candidate proof for a later `development -> main` promotion.

## Integrated capability baseline

The current `development` baseline includes:

- capability-first V3 domain/API contract;
- tenant Party authority and Representation checks;
- Booking, CapacityHold and CapacityClaim semantics;
- Reservation lifecycle and attendance;
- FIFO Queue, Waitlist, SlotOpportunity and SlotOffer recovery;
- durable CommunicationTask/Delivery, ReminderPlan and ProviderEvent handling;
- production worker assembly with worker/app transaction separation, bounded concurrency, lease fencing, poison handling and crash recovery;
- ReservationAccess/Delivery materialization with provider lookup-before-provision recovery and fenced publication;
- accepted ADR 0011 cross-tenant shared-capacity serialization for explicitly bound `exclusive` Resources, preserving tenant-local Resource and CapacityClaim ownership.

This rebaseline does not expand product scope. In particular, it does not introduce identity-resolution/deduplication, PartyIdentityLink, contact-routing/consent expansion, PartyRelationship semantics, communications fallback/acknowledgement orchestration, provider federation, federated booking, generalized shared unit capacity or CapacityPool.

## Exact-head evidence consumed

The final PR #52 candidate artifact `v3-candidate-release-proof` is complete and reports:

- `evidence_status: VALID`;
- `release_status: NOT_READY`;
- `artifact_set_complete: true`;
- clean working tree and zero manifest validation errors;
- 340 collected release tests from 78 expected files;
- reverse-order proof: 340 passed;
- concurrency stability: 3/3 rounds passed, each running 47 PostgreSQL/concurrency tests;
- schema fingerprint, catalog audit, mutation probes, initial-equivalence candidate artifact, test-quality artifact and worker query-plan artifact present.

The manifest intentionally retains the current release gate state:

- PASS: G01-G04;
- PARTIAL: G05-G14, G16, G19;
- MISSING: G15, G17, G18, G20.

This document preserves those statuses. Artifact completeness is not release readiness.

## Release-proof debt after feature integration

### P0 correctness / security proof

1. Finish critical deterministic race coverage still marked `TO VERIFY` or `MISSING` in `v3-race-matrix.md`:
   - R03 Reservation cancel vs reschedule;
   - R05 SlotOffer accept vs decline;
   - R06 SlotOffer decline vs expire;
   - R08 Reservation cancellation vs duplicate SlotOpportunity creation;
   - R15 ScheduledAction cancellation vs claim;
   - R17 ProviderEvent duplicate ingestion vs duplicate ingestion;
   - R18 provider callback semantic command vs business cancellation;
   - R19 committed command / lost response vs idempotent retry;
   - R22 ReminderPlan cancellation vs occurrence materialization.
2. Complete timeout-after-commit idempotency proof for material commands, not only duplicate-request behavior while both responses are observed.
3. Complete real concurrent-writer proof for mutable public aggregates governed by revisions.
4. Complete runtime-role isolation using true least-privileged production-style logins and negative worker/admin/SECURITY DEFINER surface tests.
5. Finish subject-authority revocation races for the material command families not yet covered by deterministic barriers.

### P1 operational / contract proof

1. Finish Booking and Slot Recovery as release-level end-to-end vertical gates, including lifecycle communications and all SlotOffer terminal race families.
2. Prove worker ownership/crash recovery under increasing concurrency and the external-side-effect-success / local-finalization-crash window.
3. Complete ProviderEvent duplicate/out-of-order/late/unknown/crash processing evidence.
4. Produce representative hot-path `EXPLAIN (ANALYZE, BUFFERS)` evidence before index freeze. G15 remains MISSING until this exists.
5. Freeze the public OpenAPI/error/capability contract only after correctness work stops changing public semantics.

### P2 release construction / reproducibility

1. Keep `0001_initial` blocked until correctness, concurrency, security, worker, API and query-plan gates are complete.
2. Build candidate-versus-`0001_initial` structural and behavioral equivalence for G17.
3. Prove a fresh release environment using only the final release migration path for G19.
4. Produce the reproducible V3 release manifest/artifact for G20.

## Phase ordering from this baseline

The canonical execution order from this point is:

1. rebaseline and reconcile proof inventory (this document);
2. close missing/TO VERIFY deterministic races;
3. close idempotency and optimistic-concurrency proof;
4. close tenant/runtime privilege proof;
5. close Booking/Slot Recovery vertical proof;
6. close worker and provider failure/recovery proof;
7. measure query plans and decide final indexes;
8. run the unified adversarial/failure release gate;
9. freeze OpenAPI/error contract;
10. freeze the proven candidate;
11. construct `0001_initial` and prove equivalence;
12. prove fresh release bootstrap and runtime roles;
13. generate reproducible release artifact/manifest and perform the release soak;
14. promote `development -> main` only when G01-G20 are PASS and no P0/P1 blockers remain.

## Evidence discipline

- A gate is not promoted because implementation appears correct; it requires executable current-candidate evidence.
- Race tests use independent PostgreSQL sessions/connections with deliberate barriers and assert both final cardinality and final state.
- Database-owned invariants require database-level proof; mocks do not satisfy lock/RLS/fencing guarantees.
- Query/index claims require stored representative plans rather than intuition.
- The current candidate chain remains construction history until candidate-versus-initial equivalence passes.
- No new product feature should move the release target while Phase 6 proof closure is active unless a failing release guarantee requires a narrowly scoped correctness change.

## Exit condition for this rebaseline phase

This rebaseline is complete when:

- this repository point is recorded from the post-#52 `development` tree;
- gate/invariant/race registries are interpreted against the current integrated baseline rather than historical pre-merge assumptions;
- no status is promoted without proof;
- the next executable work is the deterministic closure of R03/R05/R06/R08/R15/R17/R18/R19/R22;
- subsequent feature development is explicitly deferred until the V3 release baseline is stable enough that new scope will not continuously invalidate fingerprints, migration equivalence and release evidence.
