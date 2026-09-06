# PostgreSQL security and privilege topology audit

Status: active pre-rebaseline effective-model audit

Source checkpoint: exact branch head `3aa13def2102e3fdb225d5a7302971f8f8db824b`, CI #4126, PostgreSQL 18 current-product proof. The schema is unchanged by the later analyzer/documentation-only commits; a later exact-head artifact must reconfirm these facts before rebaseline.

## Effective security topology

The #4126 catalog reports:

- 101 relations;
- 81 relations with RLS enabled;
- 84 RLS policies;
- 42 FORCE-RLS relations and 39 non-FORCE RLS relations;
- six database roles;
- zero `request_engine_*` role memberships;
- zero table, column or routine grants to `PUBLIC`;
- zero grantable table, column or routine grants;
- 12 explicit column-level grants, all mapped below to a supported writer/lock path;
- 13 append-only relations protected by `reject_immutable_mutation()` and zero `request_engine_app` `UPDATE`/`DELETE` grants on those relations.

Classification: the broad runtime security topology is `KEEP`, subject to final exact-head reconfirmation.

## Roles

The effective database roles are deliberately capability-shaped rather than an inheritance hierarchy. There are no memberships between the `request_engine_*` roles.

- `request_engine_schema_owner` owns application-schema objects and migration authority.
- `request_engine_app` is the ordinary application runtime role and does not bypass RLS.
- `request_engine_worker` owns worker execution authority through reviewed command surfaces.
- `request_engine_discovery` is the cross-tenant Discovery caller role with narrow callable authority.
- `request_engine_discovery_definer` is `NOLOGIN`, `BYPASSRLS`, has no role memberships and owns only the reviewed Discovery definer surface.
- `request_engine_admin` is the explicit administrative role and is not a runtime application substitute.

Classification: `KEEP`. Rebaseline must preserve role separation rather than collapse these into one application role.

## RLS coverage

Every relation with `row_security = true` has at least one policy, and no policy is installed on a relation whose RLS flag is off.

Most tenant-owned relations use the ordinary tenant predicate:

```text
organization_id = request_engine.current_organization_id()
```

The effective model contains exactly three relations with more than one policy. They are intentional privileged-trigger exceptions and therefore require explicit classification rather than being normalized away mechanically.

### `live_capacity_projection_policies`

Policies:

- tenant `ALL` policy for ordinary tenant access;
- schema-owner `SELECT` policy gated by `pg_trigger_depth() > 0`.

Purpose: the recovery-freshness trigger path must be able to read the policy row while executing under the reviewed schema-owner trigger context.

Classification: `KEEP` as part of the Live Capacity ↔ Operational Recovery synchronous freshness boundary.

### `recovery_source_revisions`

Policies:

- tenant `ALL` policy;
- schema-owner internal-writer `ALL` policy gated by `pg_trigger_depth() > 0`.

Purpose: this relation is the synchronous recovery freshness fence. Direct app DML was already removed; trigger-driven maintenance remains the database-authoritative path.

Classification: `KEEP`.

### `service_queue_intake_controls`

Policies:

- tenant `ALL` policy;
- schema-owner trigger-writer `INSERT` policy gated by `pg_trigger_depth() > 0`.

Purpose: Queue initialization may materialize the control row through a trigger without turning schema-owner access into general runtime authority.

Classification: `KEEP`.

These `pg_trigger_depth()` policies are narrow execution-context exceptions. They must not be generalized into a reusable bypass policy for arbitrary tables.

## Runtime table authority

`request_engine_app` has no broad ownership or grant option. Its DML authority is relation-specific.

The only effective relation on which the app role has ordinary `DELETE` is:

- `request_engine.resource_location_availability` — `SELECT/INSERT/UPDATE/DELETE`.

This is intentional because the owner command replaces assignment-scoped recurring availability windows transactionally; deletion here is configuration replacement, not historical fact destruction. The parent `ResourceLocationAssignment` remains the contextual identity/provenance root.

Classification: `KEEP` while the Booking supply command continues to own replace-style recurring-window configuration.

Append-only historical facts are a stronger case: 13 relations install `reject_immutable_mutation()`, and none advertise app `UPDATE` or `DELETE` authority. Trigger rejection is therefore a backstop, not a contradiction between ACL and supported runtime behavior.

Classification: `KEEP`.

## Column-level authority — 12/12 mapped

The catalog contains exactly 12 column grants. None is orphaned.

### Operational Recovery execution lifecycle — 5

`request_engine_app` has `UPDATE` only on these columns of `operational_recovery_executions`:

- `status`;
- `completed_at`;
- `failure_code`;
- `resulting_reservation_revision`;
- `communication_task_id`.

Supported writers:

- `execution_transition_store.succeed_execution()` writes `status`, `resulting_reservation_revision`, `completed_at`;
- `execution_transition_store.reject_execution()` writes `status`, `failure_code`, `completed_at`;
- `execution_notification_store.attach_communication_task()` writes `communication_task_id` after successful execution.

The grants intentionally avoid table-wide `UPDATE` on the execution fact.

Classification: `KEEP`.

### Queue recall-hold lifecycle — 2

`request_engine_app` has `UPDATE` on:

- `queue_entry_recall_holds.released_at`;
- `queue_entry_recall_holds.release_kind`.

Queue triage expiry/release paths update exactly these lifecycle columns while preserving the original hold identity/provenance. `triage_entry.expire_time_hold()` and `triage_selection.expire_queue_time_holds()` are direct current consumers.

Classification: `KEEP`.

### Queue skip consumption lifecycle — 2

`request_engine_app` has `UPDATE` on:

- `queue_entry_skips.consumed_at`;
- `queue_entry_skips.consumed_by_entry_id`.

`triage_selection.consume_active_skips()` writes exactly those fields when a later eligible QueueEntry consumes the active skip gate, then advances affected QueueEntry revisions.

Classification: `KEEP`.

### Discovery definer row-lock authority — 3

`request_engine_discovery_definer` has `UPDATE(id)` on:

- `offerings.id`;
- `offering_service_classifications.id`;
- `discovery_publications.id`.

These are not supported business mutations. They provide the minimal PostgreSQL authority required for the Discovery→Booking SECURITY DEFINER fence to acquire row locks with `SELECT ... FOR UPDATE`:

- `guard_discovery_handoff_latest_version()` locks the current `offerings` root;
- `guard_discovery_handoff_reservation()` locks the exact active mapping and publication observed by the handoff.

The definer role is `NOLOGIN`; it cannot be used as an ordinary client role. Expanding these narrow column grants to table-wide `UPDATE` would weaken the boundary, while removing them would break the authoritative row-lock fence.

Classification: `KEEP` as lock authority, not mutation authority.

### Column-grant conclusion

All **12/12** column grants now map to a current supported writer or lock path. None justifies a schema change. Rebaseline must preserve the narrow column-level grants rather than replacing them with broader table authority.

## Routine execution authority

The catalog contains no routine grant to `PUBLIC` and no grantable routine authority. SECURITY DEFINER routines use explicit reviewed callers rather than public execution.

Current high-risk boundaries already separately proven include:

- Discovery definer execution and object authority;
- worker `request_cmd.*` execution;
- app `request_cmd.*` narrow mutation/lock surfaces;
- admin-only operational functions;
- recovery-fence read/lock functions.

Classification: topology `KEEP`. Final rebaseline must preserve the exact caller class for every SECURITY DEFINER routine; a clean baseline is not permission to replace explicit grants with schema-wide EXECUTE.

## Analyzer-backed evidence

`scripts/db/analyze_schema_cohesion.py` now derives review evidence for:

- RLS relations without policies;
- policies on non-RLS relations;
- multi-policy relations;
- grants to `PUBLIC`;
- grantable table/column/routine grants;
- app mutation authority on append-only relations;
- invalid indexes;
- unvalidated constraints.

These outputs are review/falsification evidence, not automatic deletion rules. A multi-policy relation can be correct; an empty anomaly list can only show structural closure for the checks encoded by the analyzer.

## Rebaseline implication

Security topology is no longer an unbounded `NEEDS_PROOF` area. The current effective model has explicit role/RLS/ACL structure, all 12 column grants have supported consumers, and anomaly detection is repeatable.

Remaining security/privilege work before rebaseline:

1. reconfirm the analyzer outputs on the final exact head;
2. preserve the final routine SECURITY DEFINER caller/owner classification from `postgresql-routine-ownership.md`;
3. keep the three multi-policy trigger exceptions explicit rather than silently broadening them;
4. require `PUBLIC` grants, grantable runtime grants, append-only app mutation grants, RLS-without-policy and policy-without-RLS outputs to remain empty.

No new schema migration is justified by the current security evidence.
