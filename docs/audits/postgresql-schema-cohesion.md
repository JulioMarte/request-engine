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

The last fully green audit checkpoint before the final `0044`/proof-map cleanup was exact head `4a4a3e20ad79cecf59132f55b8fd671023b06427` in CI #3902. Its artifact reported:

- schema catalog version 5;
- 102 relations;
- 147 routines;
- 164 triggers;
- 85 RLS policies;
- 280 indexes;
- six database roles and zero `request_engine_*` role memberships;
- 11 surviving views, no identical view definitions and no parallel version families;
- `proof-execution.json` with 258 executed test files and `gaps: []`.

The later `0044_remove_redundant_slot_guard` migration and proof-map cleanup must receive their own exact-head green artifact before this audit can be closed.

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

Classification: `KEEP`, pending final exact-head CI after the strengthened plan proof.

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

### SlotOffer guard topology — REMOVE in progress

The effective trigger topology showed two BEFORE INSERT paths on `slot_offers` where `guard_slot_offer_subject_match()` checked only Hold-subject versus WaitlistEntry-subject provenance while `guard_slot_offer_live_hold()` already performs that same check plus live hold, expiry, OfferingVersion, Offering, Location and time-range consistency.

`0044_remove_redundant_slot_guard` removes the subject-only trigger/function and retains the stronger live-hold guard and deferred cross-row consistency backstops.

Classification: redundant subject-only guard `REMOVE`; remaining Booking ↔ Queue SlotOffer/CapacityHold consistency topology `KEEP` as an explicit composition boundary, pending exact-head PostgreSQL proof of `0044`.

## Current KEEP decisions

### Resource-wide vs assignment/location schedules

`availability_schedules` / `schedule_exceptions` and `resource_location_availability` / `resource_location_schedule_exceptions` are distinct authorities: resource-wide scheduling versus ResourceLocationAssignment-specific scheduling, with Location operational hours as a separate layer.

Classification: `KEEP`.

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

`validate_current_proof_execution.py` counts an `INV-*` proof only when its mapped test file actually appears in current-product JUnit output. CI #3902 produced `gaps: []`, proving that no required evidence class depends solely on dormant historical files.

The proof map has now been reduced to representative executed evidence rather than hundreds of historical references. Obsolete files removed from current authority include:

- `tests/db/test_v3_runtime_privilege_closure.py`;
- `tests/db/test_v3_release_catalog.py`;
- `tests/db/test_v3_candidate.py`.

The first encoded an obsolete broad app table-privilege default; the second duplicated current PUBLIC/default-ACL checks; the mixed candidate suite combined a historical repository-shape assertion with capacity, RLS, Queue and worker guarantees already covered by focal current suites.

Historical `v3_*` naming is not itself a removal criterion. A historically named test remains `KEEP` when it still proves a current invariant and executes in current-product CI. The app callable inventory is one such current least-privilege guarantee; a neutral duplicate exists and its runner path can be normalized without changing semantics.

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

1. Obtain exact-head green current-product proof after `0044` and the reduced proof map/test cleanup.
2. Inspect the resulting effective catalog and confirm the redundant SlotOffer trigger/function are absent while the stronger live-hold/deferred consistency protections remain.
3. Complete an exhaustive relation/routine/trigger/policy/role/grant ownership-and-classification manifest for the final effective schema; no material object may remain unclassified.
4. Resolve any `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding produced by that final object-by-object pass.
5. Re-export the final catalog after all corrections and require `proof-execution.json` to remain gap-free.

Only after these blockers are closed should the repository decide whether to consolidate the pre-production migration chain into a new clean baseline and establish a new freeze.
