# PostgreSQL schema cohesion audit

Status: **closed — rebaseline accepted and installed**.

This audit classified the effective PostgreSQL model for the product Request Engine actually implements, removed unsupported pre-launch compatibility state, proved the resulting model from clean PostgreSQL 18 clusters, and then replaced the historical Alembic chain with the accepted `0001_initial` baseline.

The audit is no longer a proposal for a future rebaseline. The cut has happened.

## Accepted baseline

Canonical authority:

```text
migrations/versions/0001_initial.py
migrations/baseline/
```

`migrations/baseline/manifest.json` records checksums, six-role bootstrap topology and the accepted effective-model counts. `0001_initial` verifies and installs that payload in online Alembic mode.

Final post-cut repository evidence is CI **#4188** on `cohesion/system-optimization@3f3e0fb43cdea194b6e60d07da0e0079189b04c5`, which is fully green across Python quality/architecture, PostgreSQL current product, Observability, V2 design history and the aggregate gate.

The accepted/current model at the cut is:

```text
99 relations = 90 tables + 9 views
1,085 columns
1,575 validated constraints
276 indexes
145 routines
162 triggers
84 RLS policies
6 Request Engine roles
0 Request Engine role memberships
12 explicit column grants
```

The current-product proof executed **256 test files** with `gaps = []`.

## Reproduction evidence

Before the historical chain was removed, CI proved equivalence against the audited 0001→0050 effective model in both a second database and an independent PostgreSQL 18 cluster. The promoted single-Alembic `0001_initial` was then executed from a clean independent cluster with no pre-existing Request Engine roles and reproduced the same schema/role topology.

The accepted schema comparison permits one normalization only: surviving column ordinals are densified per relation so PostgreSQL `DROP COLUMN` `attnum` holes from historical tables do not make a clean baseline appear different. Adversarial tests prove that a true reordering of surviving columns still fails comparison.

Final post-cut baseline integrity is now a permanent proof separate from current HEAD. This distinction is deliberate:

```text
accepted 0001 baseline
    immutable bootstrap history

current Alembic head (0001 today, 0002+ in future)
    evolving product schema
```

Future migrations must not make CI require `HEAD == 0001` forever.

## Structural closure

The final analyzer closure at the cut reports no unresolved structural anomaly:

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

Two zero-Python-reference views are intentionally retained and are not orphans:

- `request_admin.worker_dead_letters_v1` — explicit operator SQL contract;
- `request_read.service_queue_status_v2` — database dependency of `request_read.live_service_staff_v1`.

Three relations intentionally have multiple RLS policies because they combine ordinary tenant policy with a narrow reviewed trigger-context schema-owner exception:

- `live_capacity_projection_policies`;
- `recovery_source_revisions`;
- `service_queue_intake_controls`.

## Major resolved findings

### Resource contextual authority

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

### Booking contextual-only state

The unreleased noncontextual appointment-option/booking path was removed. Booking, Discovery handoff and reschedule converge on contextual Location, assignment, revision and commercial provenance.

### Recovery shadow compatibility state

Compatibility-only `contextual_commitment`, legacy/current target partitioning, `RecoveryTarget.actionable` and `blocked_reason` were removed. A Recovery target is either absent or structurally complete and still passes authoritative freshness/Booking gates.

### Routine and trigger cohesion

Dangling references to removed Resource Location state were repaired before the baseline. Duplicate recovery bump trigger functions were consolidated into the single narrow helper `bump_direct_queue_recovery_source_revision()` while preserving trigger installations and lock/freshness semantics.

Final topology: 145 routines, 162 triggers, zero exact routine duplicates and zero unreferenced trigger routines.

### Unsupported administrative wrappers

Removed before the cut:

- `request_admin.outbox_health_v1`;
- `request_admin.scheduled_action_health_v1`.

They had no production consumer, database dependent or explicit operator contract. `request_admin.worker_dead_letters_v1` was retained because it does have a normative operational contract.

### Privilege topology

The final model has:

- zero PUBLIC table/column/routine grants;
- zero grantable runtime grants;
- zero app `UPDATE/DELETE` grants on append-only relations;
- 69 reviewed SECURITY DEFINER routines with explicit owner/caller classification;
- exactly 12 justified column grants;
- BYPASSRLS only where the reviewed topology requires it.

### Constraints and indexes

All 1,575 constraints are validated. The five EXCLUDE constraints encode current temporal/cardinality invariants, including Resource assignment overlap scoped by Organization + Resource + Location. All 276 indexes are valid and there are no exact index-definition duplicates. Pre-production absence of workload telemetry is not evidence for speculative index removal.

## Effective-object manifests

The semantic manifests for the accepted cut are:

- `postgresql-relation-ownership.md` — 99/99 relations;
- `postgresql-routine-ownership.md` — 145/145 routines;
- `postgresql-trigger-topology.md` — 162 trigger installations;
- `postgresql-security-privilege-topology.md` — roles, RLS and grants;
- `postgresql-security-definer-callers.md` — SECURITY DEFINER owner/caller classification;
- `postgresql-constraint-index-topology.md` — constraint/index classification.

The machine-readable CI catalog remains the exhaustive physical inventory; these documents classify semantic ownership and the important exceptions rather than copying 1,575 constraint names into prose.

## Post-rebaseline rule

There is no known material `REMOVE`, `RESHAPE` or `NEEDS_PROOF` finding left from this audit.

The next database change is **not another rebaseline**. It is an ordinary Alembic `0002+` migration from the current head. `0001_initial` and `migrations/baseline/` are now immutable accepted history.

A future destructive rebaseline remains possible only while the product is pre-production and only through another explicit effective-schema audit plus independent reproduction cycle. It must never happen implicitly to make a feature, migration or test easier.
