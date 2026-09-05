# PostgreSQL schema cohesion audit

Status: active pre-rebaseline audit

This document records the effective PostgreSQL model after `alembic upgrade head` on the system-optimization branch. It is intentionally about current product truth, not the historical shape of individual migrations. A future rebaseline is blocked while any material object remains `NEEDS_PROOF` or an accepted `RESHAPE` is unresolved.

## Classification

- `KEEP`: current semantics and topology are justified.
- `RESHAPE`: current semantics are valid, but ownership, authority, naming, indexing or composition should change before rebaseline.
- `REMOVE`: no supported current consumer or invariant justifies the object.
- `NEEDS_PROOF`: evidence is insufficient; this classification blocks rebaseline.

## Resolved during this audit

### Runtime ACLs and immutable facts — RESHAPE resolved

Thirteen append-only/immutable relations were still born with or retained `UPDATE` authority for `request_engine_app`. Trigger rejection protected data integrity but the ACL advertised authority the runtime could not legitimately use. `0035_schema_cohesion_hardening` revokes app `UPDATE` from those relations and current catalog-driven proofs require the privilege to remain absent.

The hardening exposed hidden synchronization that relied on `SELECT ... FOR UPDATE` against immutable facts. Those locks were not restored by widening ACLs. Instead, serialization moved to mutable aggregate roots:

- OfferingVersion/booking-policy operations lock the owning mutable `offerings` row.
- contextual booking locks `offerings`, not `offering_versions`.
- recovery commercial reads no longer lock immutable commercial commitments.
- `0036_append_only_lock_roots` makes booking-terms trigger synchronization lock the owning `offerings` row rather than `offering_versions`.

Classification: `KEEP` append-only facts, with mutable aggregate roots as the synchronization authority.

### Discovery SECURITY DEFINER ownership — RESHAPE resolved

Cross-tenant Discovery legitimately requires a narrowly privileged definer, but the implementation used the runtime administrative role as code owner. `0035` introduces `request_engine_discovery_definer`:

- `NOLOGIN`, `BYPASSRLS`, no role membership and no schema `CREATE` authority.
- exact relation, column-lock and function authority.
- owns the six reviewed Discovery SECURITY DEFINER routines.
- runtime app/worker/admin/discovery groups own no application-schema objects.

The current F2 PostgreSQL suite has exercised the cross-tenant Discovery path under this topology.

Classification: `KEEP`.

### SECURITY DEFINER search paths — RESHAPE resolved

Six SECURITY DEFINER routines used inconsistent trusted search paths. They now use the closed form `pg_catalog, request_engine, pg_temp`. Current proofs enumerate SECURITY DEFINER routines across all four application schemas and reject PUBLIC execution or unreviewed ownership.

Classification: `KEEP`.

### Redundant ServiceSession index — REMOVE resolved

`request_engine.service_sessions_queue_idx` duplicated the exact leading access path already enforced by the unique queue-entry index. It was removed by `0035` and `test_schema_index_cohesion.py` detects future exact unique/non-unique access-path twins.

### Unsupported read views — REMOVE resolved

The following `request_read` views had no current Python consumer, no dependent database view and no independent supported contract:

- `offering_summary_v1`
- `request_status_v1`
- `waitlist_status_v1`

`0037_remove_unused_read_views` removes them.

`service_queue_status_v1` was then audited separately. Its only active consumer used it solely to recover `queue_id`, `queue_key` and `display_name`; QueueEntry truth was already queried from Queue-owned tables. The reader now reads those identity fields directly from `service_queues`, and `0039_remove_queue_status_v1` removes the redundant view. `service_queue_status_v2` remains because `live_service_staff_v1` depends on its richer Queue/Delivery composition.

Classification: removed v1 wrappers are `REMOVE`; `service_queue_status_v2` is `KEEP`.

### Future relation default ACLs — RESHAPE resolved

The effective catalog showed a structural least-privilege defect in `pg_default_acl`: new schema-owner relations in `request_engine` automatically granted `SELECT, INSERT, UPDATE` to `request_engine_app`, and new `request_read` relations automatically granted app `SELECT`. That made future persistence fail-open and was the underlying reason append-only tables repeatedly inherited unusable `UPDATE` authority.

`0038_future_acl_fail_closed` removes those app relation defaults without changing existing relation ACLs. New tables/views must receive explicit reviewed grants. `test_runtime_privilege_boundary.py` now proves both function-default and relation-default authority remain fail-closed.

Classification: `KEEP` after `0038` is validated on effective head.

## Current KEEP decisions

### Resource-wide vs assignment/location schedules

`availability_schedules` / `schedule_exceptions` and `resource_location_availability` / `resource_location_schedule_exceptions` are not duplicate models. They represent distinct resource-wide and ResourceLocationAssignment-specific availability authorities, with Location operational hours as another separate layer.

Classification: `KEEP`.

### Recovery source revision fence

`recovery_source_revisions` is not disposable cache/shadow state. It is a synchronous transactional freshness fence used to reject stale recovery assessments and coalesce reassessment work. Replacing it with asynchronous notification would weaken stale-result rejection.

Its semantic guarantee is `KEEP`. Ownership/naming remains a `RESHAPE` candidate because Live Capacity constructs the recovery capacity checkpoint while Operational Recovery consumes it; the current name suggests Recovery ownership more strongly than the actual composition boundary warrants.

### RLS FORCE/non-FORCE mixture

The effective model intentionally contains both FORCE and non-FORCE RLS tables. Runtime app/worker/discovery roles are non-owners and remain constrained by ordinary RLS. Many non-FORCE tables participate in schema-owner SECURITY DEFINER command/worker/admin surfaces; forcing RLS globally would change those authority paths and can break legitimate internal operations.

Classification: topology `KEEP`; rationale must remain documented. A global FORCE-RLS normalization is explicitly rejected unless each affected privileged path is redesigned first.

### Administrative health views

- `request_admin.outbox_health_v1`
- `request_admin.scheduled_action_health_v1`
- `request_admin.worker_dead_letters_v1`

These have no Python consumer but are deliberate operator-facing SQL projections with admin-only read authority. Lack of application consumption does not make an administrative surface dead.

Classification: `KEEP`.

## Proof-system findings

`current-guarantees.toml` is the normative semantic inventory. `current-proof-map.toml` is migration/review evidence and must not become another repository-shape freeze.

The current-product runner now records JUnit evidence and `validate_current_proof_execution.py` counts a proof-map entry only when that file actually executed. This prevents a dormant legacy test from satisfying a current invariant by file existence alone.

Two historical privilege files are no longer acceptable current authority:

- `tests/db/test_v3_runtime_privilege_closure.py`
- `tests/db/test_v3_release_catalog.py`

The old closure encoded an obsolete broad app table-privilege default and an obsolete SECURITY DEFINER ownership model. Their useful guarantees have been migrated into current catalog/runtime proofs, principally `test_runtime_role_topology.py` and `test_runtime_privilege_boundary.py`. The proof map still requires cleanup before those historical files are deleted.

Classification: old files `REMOVE`; proof-map migration remains `RESHAPE` until exact-head proof validation confirms required evidence classes remain satisfied.

The app callable inventory is a current least-privilege guarantee, not a V3 freeze. Its implementation already enumerates all four application schemas including `request_read`; only its historical filename remains to be migrated safely.

## Constraints and indexes

The audit rejects a mechanical rule that every foreign key requires a new leading B-tree index. The effective catalog contains many FK/index asymmetries, but hot-path inspection shows several are already served by stronger purpose-built partial, unique or GiST indexes.

Examples already judged adequately indexed:

- `capacity_claims`: active hold/reservation uniqueness plus resource/time GiST paths and assignment provenance lookup.
- `queue_entries`: queue FIFO access plus active-subject uniqueness.

### Reservations temporal access — RESHAPE candidate

`reservations` currently has only identity-oriented indexes, while Day Board reads filter by tenant plus `during && tstzrange(...)`, optionally by location, order temporally and cap at 500 rows. This can degrade toward tenant-wide scans as Reservation volume grows.

Before rebaseline, review all Reservation window consumers and choose a measured temporal access path (likely tenant + range GiST, with location strategy evaluated separately). Do not add indexes solely to make FK symmetry look tidy.

Status: `RESHAPE`, pending query-plan-oriented design and proof.

## Remaining ownership work

Most table ownership maps cleanly to Tenancy, Catalog, Requests, Booking, Queue, Delivery, Discovery, Live Capacity, Communications, Platform or Operational Recovery. Remaining composition hotspots require explicit documentation rather than pretending every cross-table trigger is local:

- Recovery source revision freshness fence: semantic owner vs persistence name/topology.
- Queue/Delivery coherence triggers around QueueEntry ↔ ServiceSession.
- Booking/Queue composition around SlotOffer / CapacityHold.
- generic platform trigger utilities (`touch_updated_at`, exact revision step, immutable mutation rejection).

These are not automatically defects. Each must be classified as an explicit composition boundary or reshaped before rebaseline.

## Rebaseline blockers

Rebaseline is **not authorized** yet. The current blockers are:

1. Obtain an exact-head green `PostgreSQL 18 current product proof` after migrations 0035–0039 and the runtime lock-root fixes.
2. Produce and inspect `proof-execution.json`; no required `INV-*` evidence class may depend only on an unexecuted historical proof.
3. Migrate the proof map away from obsolete privilege/release V3 files, then remove those files.
4. Complete the Reservation temporal-index decision with workload/query evidence.
5. Finish the ownership classification of cross-capability trigger/function composition, especially the recovery freshness fence.
6. Re-export the final effective catalog and ensure every remaining relation/view/routine/trigger/policy/role/grant is KEEP or an accepted resolved RESHAPE.

Only after these blockers are closed should the repository decide whether to consolidate the pre-production migration chain into a new clean baseline and establish a new freeze.