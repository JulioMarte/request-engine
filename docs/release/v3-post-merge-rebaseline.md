# V3 post-merge release rebaseline

> **Historical snapshot — do not use this file as the current Phase 6 execution plan.**
>
> This document records the repository state immediately after the earlier Production Worker Assembly, ReservationAccess/Delivery and Cross-Tenant Shared Capacity integrations. Its commit IDs, gate statuses and remaining-work list are intentionally preserved as historical evidence.
>
> The current operational roadmap is `v3-current-release-roadmap.md`; the canonical current gate registry is `v3-release-gates.md`.
>
> As of `development@3281075bdc5e19997a3ba8120fa6a275e7ee5ab1`, the historical backlog below has materially advanced: **G01–G16 are PASS, G17 is MISSING, G18 is MISSING, G19 is PARTIAL and G20 is MISSING**. The current order is G18 → G19 → candidate freeze → G17 → affected proof reruns → G20. Do not execute the old ordering below as if it were current.

Status at the time of this snapshot: active Phase 6 release-proof baseline after integration of Production Worker Assembly, ReservationAccess/Delivery and Cross-Tenant Shared Capacity.

## Repository point at this historical snapshot

- integration branch: `development`
- development commit: `a5d6221e6cb3fd69a340dd0cccbe493ef7179c29`
- development tree: `e36eb2e717bc6e28927b2d444f148807cfa8ee52`
- cross-tenant feature head merged by PR #52: `31b2d51ccdb6e5ee9fa8b2c7f004359cc764048b`
- exact-head CI used as integration evidence: run `#847` (`31983843624`)
- PostgreSQL release target: PostgreSQL 18
- Python CI target: Python 3.13

The merge commit and the exact feature head have the same Git tree. Therefore the code integrated into `development` at that time was byte-for-byte the tree exercised by the final PR CI. The candidate evidence in this document is scoped to that historical PR/head identity and must not be treated as final release-candidate proof.

## Integrated capability baseline at this historical snapshot

The then-current `development` baseline included:

- capability-first V3 domain/API contract;
- tenant Party authority and Representation checks;
- Booking, CapacityHold and CapacityClaim semantics;
- Reservation lifecycle and attendance;
- FIFO Queue, Waitlist, SlotOpportunity and SlotOffer recovery;
- durable CommunicationTask/Delivery, ReminderPlan and ProviderEvent handling;
- production worker assembly with worker/app transaction separation, bounded concurrency, lease fencing, poison handling and crash recovery;
- ReservationAccess/Delivery materialization with provider lookup-before-provision recovery and fenced publication;
- accepted ADR 0011 cross-tenant shared-capacity serialization for explicitly bound `exclusive` Resources, preserving tenant-local Resource and CapacityClaim ownership.

This rebaseline did not expand product scope. In particular, it did not introduce identity-resolution/deduplication, PartyIdentityLink, contact-routing/consent expansion, PartyRelationship semantics, communications fallback/acknowledgement orchestration, provider federation, federated booking, generalized shared unit capacity or CapacityPool.

## Exact-head evidence consumed at this historical snapshot

The final PR #52 candidate artifact `v3-candidate-release-proof` was complete and reported:

- `evidence_status: VALID`;
- `release_status: NOT_READY`;
- `artifact_set_complete: true`;
- clean working tree and zero manifest validation errors;
- 340 collected release tests from 78 expected files;
- reverse-order proof: 340 passed;
- concurrency stability: 3/3 rounds passed, each running 47 PostgreSQL/concurrency tests;
- schema fingerprint, catalog audit, mutation probes, initial-equivalence candidate artifact, test-quality artifact and worker query-plan artifact present.

The manifest intentionally retained the gate state that existed at that time:

- PASS: G01-G04;
- PARTIAL: G05-G14, G16, G19;
- MISSING: G15, G17, G18, G20.

Those statuses are historical. They must not be copied into current release reporting.

The post-merge reconciliation also inspected the previously ambiguous race inventory. R03, R05, R06 and R15 then had concrete overlapping PostgreSQL evidence and were recorded as `PARTIAL`, not `TO VERIFY`.

## Historical release-proof debt after feature integration

The following sections preserve the backlog as understood at the time. Much of this work has since been completed and promoted through G05–G16. Consult `v3-current-release-roadmap.md` before acting on any item below.

### P0 correctness / security proof

1. Finish critical deterministic race coverage still marked `TO VERIFY` or `MISSING` in `v3-race-matrix.md`:
   - R08 Reservation cancellation vs duplicate SlotOpportunity creation;
   - R17 ProviderEvent duplicate ingestion vs duplicate ingestion;
   - R18 provider callback semantic command vs business cancellation;
   - R19 committed command / lost response vs idempotent retry;
   - R22 ReminderPlan cancellation vs occurrence materialization.
2. Complete timeout-after-commit idempotency proof for material commands, not only duplicate-request behavior while both responses are observed.
3. Complete real concurrent-writer proof for mutable public aggregates governed by revisions.
4. Complete the remaining runtime-role isolation inventory. Real least-privileged app/worker/admin LOGIN evidence already exists; the open work is the explicit negative DDL/BYPASSRLS/remaining SECURITY DEFINER execution matrix and final-baseline rerun.
5. Finish subject-authority revocation races for the material command families not yet covered by deterministic barriers.

### P1 operational / contract proof

1. Finish Booking and Slot Recovery as release-level end-to-end vertical gates, including lifecycle communications and the remaining recovery-coordination race inventory.
2. Prove worker ownership/crash recovery under increasing concurrency and the external-side-effect-success / local-finalization-crash window.
3. Complete ProviderEvent duplicate/out-of-order/late/unknown/crash processing evidence.
4. Produce representative hot-path `EXPLAIN (ANALYZE, BUFFERS)` evidence before index freeze. G15 remains MISSING until this exists.
5. Freeze the public OpenAPI/error/capability contract only after correctness work stops changing public semantics.

### P2 release construction / reproducibility

1. Keep `0001_initial` blocked until correctness, concurrency, security, worker, API and query-plan gates are complete.
2. Build candidate-versus-`0001_initial` structural and behavioral equivalence for G17.
3. Prove a fresh release environment using only the final release migration path for G19.
4. Produce the reproducible V3 release manifest/artifact for G20.

## Historical phase ordering from this snapshot

The ordering below is retained only to explain how Phase 6 evolved. It is **superseded** by `v3-current-release-roadmap.md`.

1. rebaseline and reconcile proof inventory;
2. close remaining missing/TO VERIFY deterministic races;
3. close idempotency and optimistic-concurrency proof;
4. close the remaining tenant/runtime privilege proof;
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

The current order differs because G05–G16 have since been closed and because we explicitly require G18 and G19 before blessing the final initial baseline.

## Evidence discipline retained from this snapshot

These rules remain valid:

- A gate is not promoted because implementation appears correct; it requires executable current-candidate evidence.
- Race tests use independent PostgreSQL sessions/connections with deliberate barriers and assert both final cardinality and final state.
- Database-owned invariants require database-level proof; mocks do not satisfy lock/RLS/fencing guarantees.
- Query/index claims require stored representative plans rather than intuition.
- The current candidate chain remains construction history until candidate-versus-initial equivalence passes.
- No new product feature should move the release target while Phase 6 proof closure is active unless a failing release guarantee requires a narrowly scoped correctness change.

## Historical exit condition

This rebaseline snapshot completed its purpose when the repository point after PR #52 was recorded and the proof inventory was reinterpreted against the integrated feature baseline. It is no longer the active execution document.
