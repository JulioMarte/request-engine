# PostgreSQL schema cohesion audit

Status: **closed for pre-rebaseline schema design**

This audit classifies the effective PostgreSQL model produced by `alembic upgrade head` for the current Request Engine product. It is deliberately about current product truth, not about preserving the historical shape of unreleased migrations.

The audit is now closed: there is no known material `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding left in the effective schema. Designing the replacement pre-production initial baseline is authorized. Baseline construction itself remains a separate phase and must preserve the effective model and proof topology recorded here.

## Classification policy

- `KEEP`: current semantics/topology are justified.
- `RESHAPE`: semantics are valid but ownership, authority, naming, indexing or composition must change before rebaseline.
- `REMOVE`: no supported current consumer or invariant justifies the object.
- `NEEDS_PROOF`: evidence is insufficient and blocks rebaseline.

For bulk relation-owned objects such as ordinary `NOT NULL`, `CHECK`, `FOREIGN KEY`, primary-key and unique constraints, semantic ownership follows the owning relation unless an object establishes a cross-capability or temporal/concurrency boundary. High-risk exceptions are classified explicitly. Enumerating 1,575 constraint names in Markdown would not add audit evidence; the machine-readable catalog is the exhaustive physical inventory.

Likewise, an index is not classified as useful merely because it exists. Static pre-launch evidence can prove invalidity, exact duplication and known plan-sensitive access paths, but cannot honestly prove production utilization before production traffic exists. Post-launch pruning must use `pg_stat_user_indexes`, query plans and real workload telemetry.

## Final exact-head evidence

Final closure evidence is CI **#4138** on exact branch head:

`9a3347f898504c7d1baea00d58ef3491ca4d66e0`

The complete workflow is green:

- Python quality and architecture: `success`;
- PostgreSQL 18 current product proof: `success`;
- Observability runtime contract: `success`;
- PostgreSQL 18 V2 design history: `success`;
- aggregate V3 candidate/vertical gate: `success`.

The exact-head PostgreSQL artifact reports:

- schema catalog version 5;
- **101 relations**: 90 physical tables and 11 views;
- **145 routines**;
- **162 triggers**;
- **84 RLS policies**;
- **276 indexes**;
- **1,575 validated constraints**;
- **69 SECURITY DEFINER routines**;
- six database roles;
- zero `request_engine_*` role memberships;
- 12 explicit column grants;
- 82 trigger-returning routines and **82/82 referenced**;
- **256 executed current-product test files**;
- `proof-execution.json` → **`gaps: []`**.

### Analyzer v4 closure

The final exact-head `schema-cohesion-analysis.json` reports all critical structural anomaly sets empty:

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
```

Two classes of non-empty review output remain intentionally `KEEP` rather than anomalies.

#### Three multi-policy RLS relations

- `live_capacity_projection_policies`;
- `recovery_source_revisions`;
- `service_queue_intake_controls`.

Each has the ordinary tenant policy plus one narrow `pg_trigger_depth() > 0` schema-owner trigger-context exception. Their purpose and authority are classified in `postgresql-security-privilege-topology.md`. They are not a reason to generalize trigger bypass or FORCE RLS globally.

#### Three admin health views with no Python consumer

- `request_admin.outbox_health_v1`;
- `request_admin.scheduled_action_health_v1`;
- `request_admin.worker_dead_letters_v1`.

The analyzer correctly marks them as orphan *candidates* because they have no Python/database dependent. They are nevertheless intentional admin/operator SQL surfaces. Lack of Python consumption is not evidence that an administrative SQL projection is dead.

`request_read.service_queue_status_v2` also has zero direct Python references but is not orphaned: `request_read.live_service_staff_v1` depends on it.

## Resolved REMOVE / RESHAPE findings

### Runtime ACLs and immutable facts

Thirteen append-only relations once advertised app `UPDATE` authority while triggers rejected those mutations. `0035_schema_cohesion_hardening` removed the contradictory grants and synchronization was moved to mutable aggregate roots where required.

Final artifact: zero app `UPDATE/DELETE` grants on relations protected by `reject_immutable_mutation()`.

Classification: resolved `RESHAPE`; immutable facts `KEEP`.

### Discovery privileged ownership

`request_engine_discovery_definer` is the dedicated `NOLOGIN BYPASSRLS` owner for the reviewed Discovery privileged surface. It has no role memberships and no general schema creation authority.

Three `UPDATE(id)` column grants are required solely for the reviewed `SELECT ... FOR UPDATE` row-lock paths over `offerings`, `offering_service_classifications` and `discovery_publications`; they are not business mutation APIs.

Classification: resolved `RESHAPE`; current topology `KEEP`.

### Future ACL fail-closed behavior

`0038_future_acl_fail_closed` prevents new schema-owner relations/functions from inheriting broad runtime authority automatically. PUBLIC has no table/column/routine grant in the effective model and no surviving grant is grantable.

Classification: resolved `RESHAPE`; explicit grants `KEEP`.

### Column-level grants

All **12/12** effective column grants map to a current writer/lock path:

- five Operational Recovery execution lifecycle columns;
- two Queue recall-hold release columns;
- two Queue skip-consumption columns;
- three Discovery-definer row-lock columns.

No orphan grant was found and none should be widened to relation-level UPDATE merely to simplify a baseline.

Classification: `KEEP`.

### Unsupported read wrappers

Removed:

- `request_read.offering_summary_v1`;
- `request_read.request_status_v1`;
- `request_read.waitlist_status_v1`;
- `request_read.service_queue_status_v1`.

Surviving read views have either a current application/database consumer or an explicit admin/operator contract.

Classification: completed `REMOVE`.

### Redundant indexes / temporal access

Removed redundant access paths including `service_sessions_queue_idx` and the waitlist index removed by `0047`. Added `reservations_org_during_gist` for the tenant-scoped Day Board temporal predicate.

Final artifact: 276 valid indexes, zero exact definition duplicates.

Classification: resolved `RESHAPE`; current topology `KEEP` pending real post-launch workload telemetry.

### Recovery freshness authority

`recovery_source_revisions` is a synchronous freshness/version fence, not disposable cache. `0042_recovery_fence_boundary` removed direct app DML and exposes explicit read/lock SQL boundaries instead.

Classification: `KEEP` as the Live Capacity ↔ Operational Recovery composition fence.

### Queue ↔ Delivery mutation authority

`0043_queue_delivery_boundary` moves Delivery-originated QueueEntry lifecycle mutation behind explicit `request_cmd.mark_queue_entry_service_started/completed(...)` command functions. Cross-row coherence triggers remain invariant backstops.

Classification: resolved `RESHAPE`; explicit composition boundary `KEEP`.

### Redundant SlotOffer subject guard

`0044_remove_redundant_slot_guard` removed `guard_slot_offer_subject_match()` because `guard_slot_offer_live_hold()` already enforced that invariant plus the stronger live Hold/source contract.

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

The same Resource may be assigned concurrently to multiple different Locations. The no-overlap exclusion is scoped to Organization + Resource + Location; actual commitments still share the same Resource capacity root.

Because the product has not launched and there are no customer rows to preserve, manufacturing a backfill/equivalence migration for the removed representation would have protected nonexistent data rather than a product guarantee.

Classification: completed `REMOVE`; contextual model `KEEP`.

### Legacy/noncontextual Booking state

Appointment options and booking commands now require contextual provenance structurally. The unreleased noncontextual/`aptopt_v1` compatibility path and its compatibility-only errors/tests were removed.

Direct Booking, Discovery handoff and reschedule converge on one contextual commitment model.

Classification: completed `REMOVE`.

### Duplicate recovery bump trigger functions

`0049_consolidate_recovery_bump` replaced:

- `bump_queue_recovery_source_revision()`;
- `bump_projection_policy_recovery_source_revision()`

with:

- `bump_direct_queue_recovery_source_revision()`.

The two source triggers remain separate installations but call the same narrow helper. Routines reduced 146 → 145 while triggers remain 162.

Final artifact: exact routine duplicates `[]`; trigger routines 82/82 referenced.

Classification: completed `REMOVE`; consolidated helper `KEEP`.

## Constraints and indexes

The final catalog contains:

| Constraint type | Count |
|---|---:|
| NOT NULL | 770 |
| CHECK | 392 |
| FOREIGN KEY | 198 |
| UNIQUE | 107 |
| PRIMARY KEY | 90 |
| constraint trigger | 13 |
| EXCLUDE | 5 |
| **Total** | **1,575** |

All are validated.

The five EXCLUDE constraints were individually reviewed and encode current invariants:

- `booking_context_terms_no_active_overlap`;
- `discovery_publications_no_active_overlap`;
- `location_hours_exceptions_no_active_overlap`;
- `resource_location_assignments_no_overlap`;
- `resource_location_exceptions_no_active_overlap`.

A foreign key does not mechanically imply that a matching child index is required. Child-side indexes remain query/locking/workload decisions rather than schema-shape dogma.

Classification: current constraint/index topology `KEEP`; see `postgresql-constraint-index-topology.md`.

## RLS topology

The final model contains:

- 81 RLS relations;
- 42 FORCE-RLS relations;
- 39 ordinary RLS relations;
- 84 policies;
- zero RLS relation without a policy;
- zero policy installed on a non-RLS relation.

A blanket FORCE-RLS conversion is explicitly rejected: several privileged trigger/SECURITY DEFINER paths rely on reviewed schema-owner behavior. Changing that requires redesigning those paths, not flipping a global hardening switch.

Classification: `KEEP`.

## SECURITY DEFINER closure

All **69/69** surviving SECURITY DEFINER routines have an explicit owner/caller classification in `postgresql-security-definer-callers.md`.

Final evidence:

- zero PUBLIC routine grants;
- zero grantable routine grants;
- trigger/internal-only routines do not advertise runtime callers;
- admin-only, worker/admin, app command/read and Discovery definer boundaries are distinguished rather than collapsed into schema-wide EXECUTE.

Classification: security-definer authority closure complete; `KEEP`.

## Effective-object manifests

The audit consists of the machine-readable exact-head catalog plus these semantic manifests:

- `postgresql-relation-ownership.md` — relation/view ownership;
- `postgresql-routine-ownership.md` — **145/145** routines;
- `postgresql-trigger-topology.md` — **162** trigger installations and 82/82 trigger functions referenced;
- `postgresql-security-privilege-topology.md` — roles, RLS and table/column/routine grant topology;
- `postgresql-security-definer-callers.md` — **69/69** SECURITY DEFINER owner/caller classifications;
- `postgresql-constraint-index-topology.md` — constraint/index structural and high-risk-object classification.

The catalog remains the exhaustive physical inventory. The manifests describe the semantic ownership and exceptions that a clean baseline must preserve.

## Proof-system closure

`current-guarantees.toml` remains normative. `current-proof-map.toml` is evidence mapping, not another frozen file constitution.

Final exact-head current-product proof executed **256** test files and reports:

```text
gaps = []
```

Historical filenames such as `v3_*` are not defects by themselves when the test still proves a current invariant and executes in the current lane. Compatibility-only tests that constrained unreleased obsolete behavior were removed during this audit.

Classification: current proof system `KEEP`.

## Rebaseline decision

### GO — design the replacement initial baseline

The PostgreSQL Schema & Proof Cohesion Audit no longer has a known material blocker. The evidence supports moving to a new phase whose job is **baseline construction**, not further speculative cleanup.

That does **not** mean “generate one giant migration and delete history immediately.” The replacement baseline must be treated as a reproduction exercise against this audited effective model.

Before replacing the historical migration chain, the baseline phase must prove at minimum:

1. clean PostgreSQL 18 install from the proposed new initial baseline;
2. effective catalog equivalence for the audited current model, allowing only intentionally documented baseline-normalization differences;
3. all current-product proofs remain green with `gaps: []`;
4. role/RLS/ACL/SECURITY DEFINER topology remains fail-closed and equivalent;
5. relation/routine/trigger counts and semantic manifests remain reconciled;
6. no legacy `availability_schedules`, `resources.location_id`, noncontextual Booking state, redundant SlotOffer guard or pre-0049 duplicate recovery helper is accidentally resurrected;
7. the old migration chain is retained until the new baseline has passed the reproduction proof, then removed/consolidated deliberately;
8. only after that successful reproduction should a new freeze/baseline contract be established.

No additional cleanup migration is justified by the current exact-head evidence. Continuing to mutate the effective schema without a concrete finding would now be optimization by speculation and would increase risk rather than reduce it.
