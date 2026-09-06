# PostgreSQL schema cohesion audit

Status: active pre-rebaseline audit

This document records the effective PostgreSQL model after `alembic upgrade head` on the system-optimization branch. It is intentionally about current product truth, not the historical shape of individual migrations. A future rebaseline remains blocked while any material object is `NEEDS_PROOF`, any accepted `RESHAPE` is unresolved, or the final effective-object ownership/security inventory is incomplete.

## Classification

- `KEEP`: current semantics and topology are justified.
- `RESHAPE`: current semantics are valid, but ownership, authority, naming, indexing or composition should change before rebaseline.
- `REMOVE`: no supported current consumer or invariant justifies the object.
- `NEEDS_PROOF`: evidence is insufficient; this classification blocks rebaseline.

## Effective-model evidence

The current-product lane upgrades a clean PostgreSQL 18 database to the repository's single Alembic head, exports the effective catalog, runs the cohesion analyzer and then executes the current semantic proof set.

The current fully green schema checkpoint is exact branch head `3aa13def2102e3fdb225d5a7302971f8f8db824b`, CI #4126, after migrations through `0049_consolidate_recovery_bump`. Its artifact reports:

- schema catalog version 5;
- **101 relations**;
- **145 routines**;
- **162 triggers**;
- **84 RLS policies**;
- **276 indexes**;
- **1,575 validated constraints**;
- six database roles and zero `request_engine_*` role memberships;
- 11 surviving views;
- zero exact view-definition duplicates;
- zero exact routine-implementation duplicates;
- zero exact index-definition duplicates;
- 82 trigger-returning routines, all 82 referenced by a trigger;
- `proof-execution.json` with **256 executed test files and `gaps: []`**.

The schema has not changed after #4126; later commits extend the analyzer and synchronize audit documentation. A final exact-head current-product artifact is still required before rebaseline so the stronger analyzer outputs are authoritative for the final branch tip.

## Resolved during this audit

### Runtime ACLs and immutable facts — RESHAPE resolved

Thirteen append-only/immutable relations once retained `UPDATE` authority for `request_engine_app`. Trigger rejection protected integrity but the ACL advertised authority the runtime could not legitimately use. `0035_schema_cohesion_hardening` revokes that authority and current catalog-driven proofs require it to remain absent.

The hardening exposed synchronization code that used `SELECT ... FOR UPDATE` on immutable facts. Serialization moved to mutable aggregate roots instead:

- OfferingVersion and booking-policy operations lock the owning mutable `offerings` row;
- contextual booking locks `offerings`, not `offering_versions`;
- recovery commercial reads do not lock immutable commitments;
- `0036_append_only_lock_roots` makes booking-terms synchronization lock `offerings` rather than `offering_versions`.

The #4126 catalog confirms zero app `UPDATE/DELETE` grants on the 13 relations protected by `reject_immutable_mutation()`.

Classification: append-only facts `KEEP`; mutable aggregate roots are the synchronization authority.

### Discovery SECURITY DEFINER ownership — RESHAPE resolved

Cross-tenant Discovery legitimately needs a narrowly privileged definer, but it previously used the runtime administrative role as code owner. `0035` introduces `request_engine_discovery_definer`:

- `NOLOGIN`, `BYPASSRLS`, no role membership and no schema `CREATE` authority;
- exact relation, column-lock and callable-function authority;
- owner of the six reviewed Discovery SECURITY DEFINER routines;
- runtime app/worker/admin/discovery groups own no application-schema objects.

Three `UPDATE(id)` column grants to this role are row-lock authority, not business mutation authority: the Discovery→Booking fences use `SELECT ... FOR UPDATE` on `offerings`, `offering_service_classifications` and `discovery_publications`.

Classification: `KEEP`.

### SECURITY DEFINER and future ACL closure — RESHAPE resolved

SECURITY DEFINER routines use closed trusted search paths and PUBLIC has no callable authority on application functions. `0038_future_acl_fail_closed` removes fail-open default relation grants that previously caused new schema-owner relations to inherit app `SELECT/INSERT/UPDATE` authority automatically.

The #4126 catalog contains zero table/column/routine grants to `PUBLIC` and zero grantable runtime grants.

Classification: `KEEP`.

### Column-level privilege topology — RESHAPE resolved

All 12 effective column grants are now mapped to a supported current path in `postgresql-security-privilege-topology.md`:

- five Operational Recovery execution lifecycle columns;
- two Queue recall-hold release columns;
- two Queue skip-consumption columns;
- three Discovery-definer `UPDATE(id)` row-lock grants.

No column grant is orphaned and none justifies widening to table-level `UPDATE`.

Classification: `KEEP`.

### Unsupported read views — REMOVE resolved

Removed unsupported views:

- `request_read.offering_summary_v1`
- `request_read.request_status_v1`
- `request_read.waitlist_status_v1`
- `request_read.service_queue_status_v1`

The first three had no current Python consumer, dependent database view or independent supported contract. `service_queue_status_v1` duplicated Queue identity metadata already available from `service_queues`.

`service_queue_status_v2` remains because `live_service_staff_v1` depends on its richer Queue/Delivery composition. The three analyzer-reported zero-Python-reference admin health views remain deliberate operator surfaces.

Classification: removed wrappers `REMOVE`; surviving read/admin views `KEEP`.

### Redundant indexes and Reservation temporal access — RESHAPE resolved

`service_sessions_queue_idx` duplicated the access path of an existing unique index and was removed. `0047` separately removes the redundant waitlist index.

`0041_reservation_window_index` adds the tenant-scoped GiST path used by the Day Board:

```sql
CREATE INDEX reservations_org_during_gist
ON request_engine.reservations USING gist (organization_id, during);
```

The #4126 catalog contains 276 valid indexes, zero exact duplicates and no reviewed obvious same-predicate non-unique btree left-prefix duplicate.

Classification: current index topology `KEEP`; post-launch pruning must use real workload/plan telemetry rather than synthetic pre-launch usage counts.

### Constraint topology — classified

The #4126 catalog contains 1,575 constraints and zero unvalidated constraints. The five exclusion constraints all encode current product invariants:

- `booking_context_terms_no_active_overlap`;
- `discovery_publications_no_active_overlap`;
- `location_hours_exceptions_no_active_overlap`;
- `resource_location_assignments_no_overlap`;
- `resource_location_exceptions_no_active_overlap`.

`resource_location_assignments_no_overlap` is intentionally scoped to Organization + Resource + Location. It does **not** prohibit the same Resource from concurrent assignments at different Locations; global capacity remains shared by `resource_id`.

Classification: `KEEP`; see `postgresql-constraint-index-topology.md`.

### Recovery freshness fence authority — RESHAPE resolved

`recovery_source_revisions` is not disposable cache or shadow business state. It is a synchronous transactional version/freshness fence that rejects stale recovery assessments and supports reassessment coalescing.

`0042_recovery_fence_boundary` removes direct app DML. Live Capacity and Operational Recovery access the fence through explicit SQL surfaces:

- `request_read.recovery_source_revision(uuid, uuid)`;
- `request_cmd.lock_recovery_source_revision(uuid, uuid)`.

Classification: semantic fence and current name/topology `KEEP` as an explicit composition boundary.

### Duplicate direct-Queue recovery bump helpers — REMOVE resolved

The post-0048 routine inventory exposed two SECURITY DEFINER trigger functions with the same implementation and the same `OLD/NEW.organization_id + service_queue_id` contract:

- `bump_queue_recovery_source_revision()`;
- `bump_projection_policy_recovery_source_revision()`.

`0049_consolidate_recovery_bump` replaces them with one narrow `bump_direct_queue_recovery_source_revision()` and rewires both source triggers. It does not introduce dynamic SQL or generic table dispatch.

Result in #4126:

- routines **146 → 145**;
- triggers remain **162**;
- exact routine duplicates = `[]`;
- trigger-returning routines = **82/82 referenced**.

Classification: old duplicate helpers `REMOVE`; consolidated helper `KEEP`.

### Queue ↔ Delivery mutation boundary — RESHAPE resolved

`0043_queue_delivery_boundary` moves Delivery-originated QueueEntry lifecycle mutations behind:

- `request_cmd.mark_queue_entry_service_started(...)`;
- `request_cmd.mark_queue_entry_service_completed(...)`.

Both are tenant-fenced SECURITY DEFINER command surfaces with PUBLIC revoked and explicit app EXECUTE authority. Database coherence triggers remain invariant backstops across QueueEntry and ServiceSession.

Classification: explicit composition boundary `KEEP`.

### SlotOffer guard topology — REMOVE resolved

`0044_remove_redundant_slot_guard` removes `guard_slot_offer_subject_match()` because `guard_slot_offer_live_hold()` already enforced the subject invariant plus the complete live-hold/source consistency contract.

Classification: redundant subject-only guard `REMOVE`; remaining Booking ↔ Queue SlotOffer/CapacityHold consistency topology `KEEP`.

### Legacy Resource location and recurring availability persistence — REMOVE resolved

The pre-launch model carried two overlapping representations of Resource context:

- `resources.location_id` as an implicit single Location association;
- `availability_schedules` as recurring Resource-wide availability.

The current product model is:

```text
Resource
└── ResourceLocationAssignment [0..N]
    └── ResourceLocationAvailability [0..N]
```

A Resource may have concurrent assignments at multiple Locations; all commitments still consume the same Resource capacity. Location timezone belongs to `locations.timezone`, and assignment provenance is carried into appointment options and authoritative booking.

Because Request Engine is pre-launch and has no production/customer rows to preserve, `0048_remove_legacy_location` drops the obsolete relation/column directly rather than manufacturing historical backfill complexity for nonexistent data.

The #4126 effective catalog contains neither `availability_schedules` nor `resources.location_id`.

Classification: legacy persistence `REMOVE`; contextual assignment/availability authority `KEEP`.

### Legacy/noncontextual Booking state — REMOVE resolved

Booking command and appointment-option contracts now require contextual provenance structurally. The former noncontextual/`aptopt_v1` state space and compatibility-only error branches/tests were removed rather than retained as optional nullable fields.

Direct Booking, Discovery handoff and reschedule now converge on the same contextual commitment model.

Classification: unreleased noncontextual compatibility `REMOVE`; contextual-only Booking `KEEP`.

## Current KEEP decisions

### Resource-wide exceptions vs assignment/location availability

The removed `availability_schedules` table is not a current recurring scheduling authority. Current recurring availability is assignment-contextual through `resource_location_availability`, while Location operational hours remain a separate Location authority.

`request_engine.schedule_exceptions` remains a distinct Resource-wide exception layer where a Resource must be suppressed/altered independently of one assignment. Assignment-specific exceptions remain contextual to `ResourceLocationAssignment`.

Classification: surviving exception layers `KEEP`; legacy Resource-wide recurring schedule persistence `REMOVE`.

### RLS FORCE/non-FORCE mixture

The effective model intentionally contains 42 FORCE-RLS and 39 non-FORCE RLS relations. Runtime app/worker/discovery roles are non-owners and remain constrained by ordinary RLS. Several non-FORCE relations participate in reviewed schema-owner SECURITY DEFINER/trigger paths.

Exactly three relations have multiple policies, all explicit trigger-context exceptions documented in `postgresql-security-privilege-topology.md`.

Classification: `KEEP`. Blanket FORCE-RLS normalization is rejected unless the affected privileged path is redesigned first.

### Administrative health views

- `request_admin.outbox_health_v1`
- `request_admin.scheduled_action_health_v1`
- `request_admin.worker_dead_letters_v1`

These are deliberate admin-only operational SQL projections. Lack of Python consumption does not make an operator surface dead.

Classification: `KEEP`.

## Effective-object manifests

The audit now has explicit manifests for the main object classes:

- relations/views: `postgresql-relation-ownership.md` — 101 expected/current relations;
- routines: `postgresql-routine-ownership.md` — 145/145 classified post-0049;
- triggers: `postgresql-trigger-topology.md` — 162 classified installations, 82/82 trigger functions referenced;
- policies/roles/grants: `postgresql-security-privilege-topology.md`;
- constraints/indexes: `postgresql-constraint-index-topology.md`.

These documents classify semantic ownership/topology. The final exact-head artifact remains the machine-readable authority for what physically exists.

## Proof-system findings

`current-guarantees.toml` is normative. `current-proof-map.toml` is migration/review evidence and must not become another exact-file constitution.

CI #4126 executed 256 test files and produced `gaps: []`. Historical filenames such as `v3_*` are not themselves removal criteria; a historically named test remains current when it proves a current invariant and executes in the current-product lane.

Conversely, tests whose only purpose was preserving unreleased compatibility state have been removed rather than allowed to constrain the current product indefinitely.

Classification: current proof execution system `KEEP`.

## Remaining work before rebaseline

The audit is substantially closer to closure, but rebaseline is **not authorized yet**.

Remaining blockers:

1. **SECURITY DEFINER caller/authority closure.** Reconcile every surviving SECURITY DEFINER routine against its owner and exact caller/grant class so the clean baseline cannot accidentally widen EXECUTE or object authority. Discovery's six definer routines and the major `request_cmd` boundaries are already understood; the final manifest must be exhaustive rather than representative.
2. **Exact-head analyzer v4 evidence.** Obtain a fully green current-product run on the final documentation/analyzer tip and inspect `schema-cohesion-analysis.json`. Required empty anomaly sets include exact routine/index/view duplicates, unreferenced trigger routines, invalid indexes, unvalidated constraints, PUBLIC grants, grantable grants, app mutation grants on append-only relations, RLS relations without policy and policies on non-RLS relations.
3. **Final catalog/proof closure.** Re-export the final PostgreSQL 18 catalog after all audit corrections and require `proof-execution.json` to remain `gaps: []`.
4. **No unresolved dispositions.** Any new `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding discovered by the final pass must be resolved before baseline construction starts.

No known current application compatibility/shadow-state blocker remains from the legacy Resource or noncontextual Booking model, and no additional schema migration is currently justified by the effective catalog.

Only after the four blockers above are closed should the repository design the replacement pre-production initial baseline and establish a new freeze.
