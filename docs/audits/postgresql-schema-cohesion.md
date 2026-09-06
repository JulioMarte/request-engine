# PostgreSQL schema cohesion audit

Status: **closed for pre-rebaseline schema design**

This audit classifies the effective PostgreSQL model produced by `alembic upgrade head` for the current Request Engine product. It is deliberately about current product truth, not preserving the historical shape of unreleased migrations.

There is no known material `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding left in the effective schema. The replacement pre-production initial baseline is authorized as the next phase. Baseline construction remains a separate reproduction exercise and must preserve the effective model and proof topology recorded here.

## Classification policy

- `KEEP`: current semantics/topology are justified.
- `RESHAPE`: semantics are valid but ownership, authority, naming, indexing or composition must change before rebaseline.
- `REMOVE`: no supported current consumer or invariant justifies the object.
- `NEEDS_PROOF`: evidence is insufficient and blocks rebaseline.

Bulk relation-owned objects inherit semantic ownership from the relation unless they establish a cross-capability, temporal, concurrency or privilege boundary. The machine-readable catalog is the exhaustive physical inventory; the manifests classify the semantics and exceptions.

Static pre-launch evidence can prove invalid indexes, exact duplication and known plan-sensitive access paths, but cannot prove production index utilization before production traffic exists. Post-launch pruning remains a telemetry/query-plan decision.

## Final exact-head evidence

Final pre-rebaseline closure evidence is CI **#4164** on exact branch head:

`4ba7dbf092528f26aee5db1003af455a381d3431`

The relevant gates are green:

- Python quality and architecture: `success`;
- PostgreSQL 18 current product proof: `success`;
- Observability runtime contract: `success`;
- PostgreSQL 18 V2 design history: `success`.

The exact-head PostgreSQL artifact reports:

- schema catalog version 5;
- **99 relations**;
- **1,085 columns**;
- **9 views**;
- **145 routines**;
- **162 triggers**;
- **84 RLS policies**;
- **276 indexes**;
- **1,575 validated constraints**;
- six Request Engine roles;
- zero Request Engine role memberships;
- zero Request Engine role settings;
- 12 explicit column grants.

### Rebaseline reproduction evidence

The audited head is no longer proven only by replaying history. CI #4164 generated a schema-only candidate from the effective model and proved all of the following:

1. replay into a second empty database in the source PostgreSQL cluster;
2. bootstrap of the audited six Request Engine roles into a completely independent PostgreSQL 18 cluster;
3. replay of the candidate schema into that independent cluster;
4. independent export and comparison of schema and role catalogs.

All three comparison artifacts report:

```text
equivalent = true
first_difference = null
```

The schema comparator permits one normalization only: surviving column ordinals are densified per relation so historical `DROP COLUMN` `attnum` holes do not make an otherwise identical fresh baseline appear different. Adversarial unit tests prove that this normalization still rejects a real reordering of surviving columns.

The fresh role proof requires exactly six roles with:

- `NOSUPERUSER`;
- `INHERIT`;
- `NOCREATEROLE`;
- `NOCREATEDB`;
- `NOLOGIN`;
- `NOREPLICATION`;
- connection limit `-1`;
- no password;
- no `VALID UNTIL`;
- no role memberships;
- no role settings;
- `BYPASSRLS` only for `request_engine_admin` and `request_engine_discovery_definer`.

Role password presence is read from privileged `pg_authid`, not the masked `pg_roles.rolpassword` representation.

## Analyzer v5 closure

The final `schema-cohesion-analysis.json` reports all critical structural anomaly sets empty:

```text
exact_view_definition_duplicates = []
exact_routine_implementation_duplicates = []
exact_index_definition_duplicates = []
unreferenced_trigger_routines = []
invalid_indexes = []
unvalidated_constraints = []
public_grants = []
grantable_grants = []
immutable_app_mutation_grants = []
rls_relations_without_policy = []
policies_on_non_rls_relations = []
version_families = []
orphan_view_candidates = []
```

Two zero-Python-reference views remain and neither is an orphan:

- `request_admin.worker_dead_letters_v1` is an explicit external/operator SQL contract documented by `docs/v3/10-worker-runtime-hardening.md`;
- `request_read.service_queue_status_v2` is a database dependency of `request_read.live_service_staff_v1`.

The analyzer therefore distinguishes `zero_production_reference_views` from true orphan candidates instead of treating absence of Python imports as proof of dead administrative SQL.

### Multi-policy RLS relations

Three relations intentionally have multiple policies:

- `live_capacity_projection_policies`;
- `recovery_source_revisions`;
- `service_queue_intake_controls`.

Each has ordinary tenant policy plus a narrow reviewed trigger-context schema-owner exception. Their authority is classified in `postgresql-security-privilege-topology.md`; they are not justification for generalized trigger bypass or blanket FORCE RLS changes.

## Resolved REMOVE / RESHAPE findings

### Runtime ACLs and immutable facts

Thirteen append-only relations once advertised app `UPDATE` authority while triggers rejected those mutations. `0035_schema_cohesion_hardening` removed contradictory grants and synchronization moved to mutable aggregate roots where required.

Final evidence: zero app `UPDATE/DELETE` grants on relations protected by `reject_immutable_mutation()`.

Classification: resolved `RESHAPE`; immutable facts `KEEP`.

### Discovery privileged ownership

`request_engine_discovery_definer` is the dedicated `NOLOGIN BYPASSRLS` owner for the reviewed Discovery privileged surface, with no memberships or general schema creation authority.

Three `UPDATE(id)` grants exist only for reviewed `SELECT ... FOR UPDATE` paths over `offerings`, `offering_service_classifications` and `discovery_publications`; they are not business mutation APIs.

Classification: resolved `RESHAPE`; current topology `KEEP`.

### Future ACL fail-closed behavior

`0038_future_acl_fail_closed` prevents new schema-owner relations/functions from inheriting broad runtime authority automatically. PUBLIC has no table/column/routine grants in the effective model and no surviving grant is grantable.

Classification: resolved `RESHAPE`; explicit grants `KEEP`.

### Column-level grants

All **12/12** column grants map to current writer/lock paths:

- five Operational Recovery execution lifecycle columns;
- two Queue recall-hold release columns;
- two Queue skip-consumption columns;
- three Discovery-definer row-lock columns.

Classification: `KEEP`; none should be widened merely to simplify a baseline.

### Unsupported read/admin wrappers

Removed read wrappers:

- `request_read.offering_summary_v1`;
- `request_read.request_status_v1`;
- `request_read.waitlist_status_v1`;
- `request_read.service_queue_status_v1`.

`0050_remove_admin_health_views` additionally removed:

- `request_admin.outbox_health_v1`;
- `request_admin.scheduled_action_health_v1`.

Those two administrative summaries had no application consumer, no database dependent and no explicit operator contract. `request_admin.worker_dead_letters_v1` was deliberately retained because it *does* have a normative operator contract.

Classification: completed `REMOVE`; surviving views are justified by application/database consumption or an explicit external contract.

### Redundant indexes / temporal access

Redundant access paths including `service_sessions_queue_idx` and the waitlist index removed by `0047` are gone. `reservations_org_during_gist` provides the tenant-scoped Day Board temporal access path.

Final evidence: 276 valid indexes and zero exact index-definition duplicates.

Classification: resolved `RESHAPE`; current topology `KEEP` pending post-launch workload telemetry.

### Recovery freshness authority

`recovery_source_revisions` is a synchronous freshness/version fence, not disposable cache. `0042_recovery_fence_boundary` removed direct app DML and exposes explicit read/lock boundaries.

Classification: `KEEP` as the Live Capacity ↔ Operational Recovery composition fence.

### Queue ↔ Delivery mutation authority

`0043_queue_delivery_boundary` moves Delivery-originated QueueEntry lifecycle mutation behind explicit `request_cmd.mark_queue_entry_service_started/completed(...)` command functions. Cross-row coherence triggers remain invariant backstops.

Classification: resolved `RESHAPE`; composition boundary `KEEP`.

### Redundant SlotOffer subject guard

`0044_remove_redundant_slot_guard` removed `guard_slot_offer_subject_match()` because `guard_slot_offer_live_hold()` already enforces that invariant plus the stronger live Hold/source contract.

Classification: completed `REMOVE`.

### Legacy Resource location / recurring availability model

Removed pre-launch compatibility state:

- `resources.location_id`;
- `availability_schedules`.

Current authority is:

```text
Resource
└── ResourceLocationAssignment [0..N]
    └── ResourceLocationAvailability [0..N]
```

A Resource may be assigned concurrently to multiple different Locations. Assignment overlap exclusion is scoped to Organization + Resource + Location; commitments still share the Resource capacity root.

Because the product has not launched and there are no customer rows to preserve, no compatibility backfill was manufactured for nonexistent production state.

Classification: completed `REMOVE`; contextual model `KEEP`.

### Legacy/noncontextual Booking state

Appointment options and booking commands require contextual provenance. The unreleased `aptopt_v1`/noncontextual compatibility path and compatibility-only errors/tests were removed. Direct Booking, Discovery handoff and reschedule converge on one contextual commitment model.

Classification: completed `REMOVE`.

### Duplicate recovery bump trigger functions

`0049_consolidate_recovery_bump` replaced two duplicate helpers with `bump_direct_queue_recovery_source_revision()`. The two source trigger installations remain but call the same narrow helper.

Final evidence: 145 routines, 162 triggers, exact routine duplicates `[]`, and no unreferenced trigger routine.

Classification: completed `REMOVE`; consolidated helper `KEEP`.

## Constraints and indexes

The final catalog contains **1,575 validated constraints**. The five EXCLUDE constraints individually encode current invariants:

- `booking_context_terms_no_active_overlap`;
- `discovery_publications_no_active_overlap`;
- `location_hours_exceptions_no_active_overlap`;
- `resource_location_assignments_no_overlap`;
- `resource_location_exceptions_no_active_overlap`.

A foreign key does not mechanically imply a matching child index; child-side indexing remains a query/locking/workload decision.

Classification: current constraint/index topology `KEEP`; see `postgresql-constraint-index-topology.md`.

## RLS and privilege topology

The final model contains 84 policies, zero RLS relations without policy and zero policies on non-RLS relations. A blanket FORCE-RLS conversion remains rejected because reviewed privileged trigger/SECURITY DEFINER paths intentionally depend on their present authority boundaries.

All surviving SECURITY DEFINER routines retain explicit owner/caller classification in `postgresql-security-definer-callers.md`.

Final privilege evidence includes:

- zero PUBLIC table/column/routine grants;
- zero grantable runtime grants;
- explicit runtime role topology;
- no Request Engine role memberships/settings;
- trigger/internal routines do not advertise runtime callers.

Classification: current security topology `KEEP`.

## Effective-object manifests

The machine-readable exact-head catalog is the exhaustive inventory. Semantic manifests are:

- `postgresql-relation-ownership.md` — **99/99** relations;
- `postgresql-routine-ownership.md` — **145/145** routines;
- `postgresql-trigger-topology.md` — **162** trigger installations;
- `postgresql-security-privilege-topology.md` — roles, RLS and grants;
- `postgresql-security-definer-callers.md` — SECURITY DEFINER owner/caller classifications;
- `postgresql-constraint-index-topology.md` — constraint/index classification.

## Rebaseline decision

### GO — construct and prove the replacement initial baseline

The effective-schema audit is closed. Further speculative object deletion would now create more risk than value.

The next phase is not “delete migrations.” It is to materialize a proposed replacement `0001` and prove it independently against the exact audited target.

Before the historical chain may be removed, the proposed baseline must prove:

1. clean PostgreSQL 18 installation with **no pre-existing Request Engine roles**;
2. role bootstrap recreates the audited six-role topology;
3. `alembic upgrade head` from the proposed single baseline succeeds;
4. schema catalog equals the audited 99-relation model, permitting only the documented `attnum`-gap normalization;
5. role catalog equality is exact;
6. all current-product proofs remain green with `gaps: []`;
7. RLS/ACL/SECURITY DEFINER topology remains fail-closed and equivalent;
8. no removed Resource/Booking/admin-view/recovery-helper compatibility state is resurrected;
9. only after those proofs pass may the old migration chain and old V3 payload be removed deliberately.

The baseline should keep cluster-global role bootstrap and database-local schema payload conceptually separate. A readable audited schema source plus checksum is preferred over making opaque compressed blobs the only reviewable representation.
