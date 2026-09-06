# PostgreSQL schema cohesion audit

Status: active pre-rebaseline audit

This document records the effective PostgreSQL model after `alembic upgrade head` on the system-optimization branch. It is intentionally about current product truth, not the historical shape of individual migrations. A future rebaseline remains blocked while any material object is `NEEDS_PROOF`, any accepted `RESHAPE` is unresolved, or the final effective-object ownership inventory is incomplete.

## Classification

- `KEEP`: current semantics and topology are justified.
- `RESHAPE`: current semantics are valid, but ownership, authority, naming, indexing or composition should change before rebaseline.
- `REMOVE`: no supported current consumer or invariant justifies the object.
- `NEEDS_PROOF`: evidence is insufficient; this classification blocks rebaseline.

## Effective-model evidence

The current-product lane upgrades a clean PostgreSQL 18 database to the repository's single Alembic head, then exports the effective catalog before running current proofs. The catalog includes relations and view definitions, columns, constraints, indexes, routines and definitions, triggers, RLS policies, table/column/routine grants, roles and memberships, default ACLs and view dependencies.

The last fully green catalog checkpoint available during the audit was exact head `4a4a3e20ad79cecf59132f55b8fd671023b06427` in CI #3902. Its artifact reported:

- schema catalog version 5;
- 102 relations;
- 147 routines;
- 164 triggers;
- 85 RLS policies;
- 280 indexes;
- six database roles and zero `request_engine_*` role memberships;
- 11 surviving views, no identical view definitions and no parallel version families;
- `proof-execution.json` with 258 executed test files and `gaps: []`.

That checkpoint predates later accepted cohesion changes, including `0044_remove_redundant_slot_guard`, `0047_remove_waitlist_index`, and `0048_remove_legacy_location`. The expected post-`0048` relation count is 101 because `request_engine.availability_schedules` is removed and no later migration adds a relation, but that number is an audit expectation rather than final evidence. A fresh exact-head PostgreSQL 18 catalog export is required before rebaseline.

## Resolved during this audit

### Runtime ACLs and immutable facts — RESHAPE resolved

Thirteen append-only/immutable relations retained `UPDATE` authority for `request_engine_app`. Trigger rejection protected integrity but the ACL advertised authority the runtime could not legitimately use. `0035_schema_cohesion_hardening` revokes that authority and current catalog-driven proofs require it to remain absent.

The hardening exposed synchronization code that used `SELECT ... FOR UPDATE` on immutable facts. The fix did not restore broad `UPDATE`. Serialization moved to mutable aggregate roots instead:

- OfferingVersion and booking-policy operations lock the owning mutable `offerings` row;
- contextual booking locks `offerings`, not `offering_versions`;
- recovery commercial reads do not lock immutable commitments;
- `0036_append_only_lock_roots` makes booking-terms synchronization lock `offerings` rather than `offering_versions`.

Classification: append-only facts `KEEP`; mutable aggregate roots are the synchronization authority.

### Discovery SECURITY DEFINER ownership — RESHAPE resolved

Cross-tenant Discovery legitimately needs a narrowly privileged definer, but it previously used the runtime administrative role as code owner. `0035` introduces `request_engine_discovery_definer`:

- `NOLOGIN`, `BYPASSRLS`, no role membership and no schema `CREATE` authority;
- exact relation, column-lock and callable-function authority;
- owner of the six reviewed Discovery SECURITY DEFINER routines;
- runtime app/worker/admin/discovery groups own no application-schema objects.

F2 current-product proofs exercise the cross-tenant Discovery path under this topology.

Classification: `KEEP`.

### SECURITY DEFINER and future ACL closure — RESHAPE resolved

SECURITY DEFINER routines use closed trusted search paths and PUBLIC has no callable authority on application functions. `0038_future_acl_fail_closed` also removes fail-open default relation grants that previously caused new schema-owner relations to inherit app `SELECT/INSERT/UPDATE` authority automatically. New relations and routines must receive explicit reviewed grants.

Current proofs cover PUBLIC execution, default function ACL, default relation ACL, runtime login non-escalation, schema usage, object ownership and exact Discovery-definer authority.

Classification: `KEEP`.

### Unsupported read views — REMOVE resolved

Removed unsupported views:

- `request_read.offering_summary_v1`
- `request_read.request_status_v1`
- `request_read.waitlist_status_v1`
- `request_read.service_queue_status_v1`

The first three had no current Python consumer, dependent database view or independent supported contract. `service_queue_status_v1` only duplicated Queue identity metadata already available from `service_queues`.

`service_queue_status_v2` remains because `live_service_staff_v1` depends on its richer Queue/Delivery composition.

Classification: removed wrappers `REMOVE`; `service_queue_status_v2` `KEEP`.

### Redundant indexes and Reservation temporal access — RESHAPE resolved

`service_sessions_queue_idx` duplicated the access path of an existing unique index and was removed. A catalog proof rejects future exact unique/non-unique twins.

`0041_reservation_window_index` adds:

```sql
CREATE INDEX reservations_org_during_gist
ON request_engine.reservations USING gist (organization_id, during);
```

The plan-oriented proof now exercises the tenant-scoped Day Board predicate (`organization_id = ... AND during && ...`) rather than proving only an unscoped range overlap.

Classification: `KEEP`, subject to final exact-head catalog/proof confirmation.

### Recovery freshness fence authority — RESHAPE resolved

`recovery_source_revisions` is not disposable cache or shadow business state. It is a synchronous transactional version/freshness fence that rejects stale recovery assessments and supports reassessment coalescing. Replacing it with asynchronous notification would weaken that guarantee.

`0042_recovery_fence_boundary` removes direct app DML. Live Capacity and Operational Recovery now access the fence through explicit SQL surfaces:

- `request_read.recovery_source_revision(uuid, uuid)`;
- `request_cmd.lock_recovery_source_revision(uuid, uuid)`.

The physical table is therefore internal persistence behind an explicit Live Capacity ↔ Operational Recovery composition boundary. A rename would create high migration/function/trigger churn without improving authority or behavior.

Classification: semantic fence and current name/topology `KEEP` as an explicit composition boundary.

### Queue ↔ Delivery mutation boundary — RESHAPE resolved

`0043_queue_delivery_boundary` moves Delivery-originated QueueEntry lifecycle mutations behind:

- `request_cmd.mark_queue_entry_service_started(...)`;
- `request_cmd.mark_queue_entry_service_completed(...)`.

Both are tenant-fenced SECURITY DEFINER command surfaces with PUBLIC revoked and explicit app EXECUTE authority. Delivery no longer needs to encode a direct cross-owner Queue mutation path.

Database coherence triggers remain as invariant backstops across QueueEntry and ServiceSession.

Classification: explicit composition boundary `KEEP`.

### SlotOffer guard topology — REMOVE resolved

The effective trigger topology showed two BEFORE INSERT paths on `slot_offers` where `guard_slot_offer_subject_match()` checked only Hold-subject versus WaitlistEntry-subject provenance while `guard_slot_offer_live_hold()` already performed that check plus live hold, expiry, OfferingVersion, Offering, Location and time-range consistency.

`0044_remove_redundant_slot_guard` removes the subject-only trigger/function and retains the stronger live-hold guard and deferred cross-row consistency backstops.

Classification: redundant subject-only guard `REMOVE`; remaining Booking ↔ Queue SlotOffer/CapacityHold consistency topology `KEEP`, subject to final exact-head catalog confirmation.

### Legacy Resource location and recurring availability persistence — REMOVE resolved

The pre-launch model carried two overlapping representations of Resource context:

- `resources.location_id` as an implicit single Location association;
- `availability_schedules` as recurring Resource-wide availability with its own timezone/validity state.

The current product model instead makes contextual eligibility and recurring supply explicit:

```text
Resource
└── ResourceLocationAssignment [0..N]
    └── ResourceLocationAvailability [0..N]
```

A Resource may have concurrent assignments at multiple Locations; all commitments still consume the same Resource capacity. Location timezone belongs to `locations.timezone`, and assignment provenance is carried into reservable appointment options and authoritative booking.

Because Request Engine is pre-launch and has no production/customer rows to preserve, historical backfill/equivalence work for the removed representation would protect nonexistent data rather than a product guarantee. `0048_remove_legacy_location` therefore drops `request_engine.availability_schedules` and `resources.location_id` directly. Current proofs also assert that no surviving PostgreSQL routine references `availability_schedules`.

Classification: `availability_schedules` and `resources.location_id` `REMOVE`; `ResourceLocationAssignment` and `ResourceLocationAvailability` `KEEP` as current contextual authority.

## Current KEEP decisions

### Resource-wide exceptions vs assignment/location availability

The removed `availability_schedules` table must not be treated as a current recurring scheduling authority. Current recurring availability is assignment-contextual through `resource_location_availability`, while Location operational hours remain a separate Location authority.

`request_engine.schedule_exceptions` remains a distinct Resource-wide exception layer where current consumers/invariants require an exception to suppress or alter Resource availability independently of one assignment. Assignment-specific exceptions remain contextual to `ResourceLocationAssignment`.

This is not a justification for recreating Resource-wide recurring schedules. The distinction is:

- recurring availability: assignment/location contextual;
- broad Resource exception: Resource-wide when explicitly modeled;
- contextual exception: assignment-specific;
- Location operational availability: Location-owned.

Classification: surviving exception layers `KEEP` while their current consumers/invariants remain proven; legacy Resource-wide recurring schedule persistence `REMOVE`.

### RLS FORCE/non-FORCE mixture

The effective model intentionally contains both FORCE and non-FORCE RLS tables. Runtime app/worker/discovery roles are non-owners and remain constrained by ordinary RLS. Several non-FORCE relations participate in schema-owner SECURITY DEFINER command/worker/admin paths. A blanket FORCE-RLS conversion would change those authority paths rather than merely harden them.

Classification: `KEEP`. Global FORCE-RLS normalization is rejected unless each affected privileged path is redesigned first.

### Administrative health views

- `request_admin.outbox_health_v1`
- `request_admin.scheduled_action_health_v1`
- `request_admin.worker_dead_letters_v1`

These are deliberate admin-only operational SQL projections. Lack of Python consumption does not make an operator surface dead.

Classification: `KEEP`.

## Proof-system findings

`current-guarantees.toml` is normative. `current-proof-map.toml` is migration/review evidence and must not become another exact-file constitution.

The proof execution validator counts an `INV-*` proof only when its mapped test file actually appears in current-product JUnit output. CI #3902 produced `gaps: []`, proving that at that checkpoint no required evidence class depended solely on dormant historical files. Every later accepted schema/application change must receive the same exact-head treatment before the audit is closed.

The proof map has been reduced to representative executed evidence rather than hundreds of historical references. Obsolete files removed from current authority include:

- `tests/db/test_v3_runtime_privilege_closure.py`;
- `tests/db/test_v3_release_catalog.py`;
- `tests/db/test_v3_candidate.py`.

Historical `v3_*` naming is not itself a removal criterion. A historically named test remains `KEEP` when it still proves a current invariant and executes in current-product CI. Conversely, a test whose only purpose is preserving an unreleased compatibility state is not current authority merely because it once protected a V3 behavior.

Classification: proof execution system `KEEP`; obsolete closure/release/candidate suites `REMOVE`; remaining purely nominal path cleanup is non-semantic `RESHAPE`.

## Remaining exhaustive ownership work

The high-risk ownership hotspots have been resolved or classified, but rebaseline requires more than hotspot review. Every effective object still needs an explicit final owner/classification manifest.

The final inventory must cover at least:

- all physical tables and views;
- every routine, especially SECURITY DEFINER and cross-capability trigger helpers;
- every trigger and its composition boundary;
- RLS policies and privileged internal-writer policies;
- runtime and definer roles, memberships and object grants;
- constraints/indexes that embody product invariants rather than historical convenience.

Known cross-capability boundaries are not automatically defects:

- Live Capacity ↔ Operational Recovery freshness fence: `KEEP`;
- Queue ↔ Delivery lifecycle coherence: `KEEP` after `0043`;
- Booking ↔ Queue SlotOffer/CapacityHold consistency: `KEEP` after removal of the redundant subject-only guard;
- generic platform trigger utilities (`touch_updated_at`, exact revision step, immutable mutation rejection): `KEEP` when used as shared persistence mechanics rather than capability-owned business state.

The remaining task is to make these classifications exhaustive rather than infer them from spot checks.

## Rebaseline blockers

Rebaseline is **not authorized** yet. The remaining blockers are:

1. Obtain an exact-head green current-product run after the accepted schema and application cohesion changes through `0048` and the contextual-only booking cleanup.
2. Inspect the resulting effective PostgreSQL 18 catalog and verify the expected 101 relations, absence of `availability_schedules` and `resources.location_id`, and absence of the redundant SlotOffer guard while stronger consistency protections remain.
3. Complete an exhaustive relation/routine/trigger/policy/role/grant/index/constraint ownership-and-classification manifest for the final effective schema; no material object may remain unclassified.
4. Resolve every remaining `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding produced by that object-by-object pass.
5. Remove remaining unreleased application compatibility/shadow states that can still represent product-invalid booking/resource context.
6. Re-export the final catalog after all corrections and require `proof-execution.json` to remain gap-free.

Only after these blockers are closed should the repository decide whether to consolidate the pre-production migration chain into a new clean baseline and establish a new freeze.
