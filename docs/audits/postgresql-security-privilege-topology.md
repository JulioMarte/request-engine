# PostgreSQL security and privilege topology audit

Status: active pre-rebaseline effective-model audit

Source checkpoint: exact branch head `3aa13def2102e3fdb225d5a7302971f8f8db824b`, CI #4126, PostgreSQL 18 current-product proof. The schema is unchanged by the later analyzer-only commits; a later exact-head artifact must reconfirm these facts before rebaseline.

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
- 12 explicit column-level grants;
- 13 append-only relations protected by `reject_immutable_mutation()` and zero `request_engine_app` `UPDATE`/`DELETE` grants on those relations.

Classification: the broad runtime security topology is `KEEP`, subject to the explicit exception reviews below and final exact-head reconfirmation.

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

## Column-level authority

The catalog contains 12 explicit column grants. They exist to narrow mutable authority where a relation is otherwise more restricted, rather than to create hidden cross-module ownership.

These grants must remain part of the final privilege manifest and must not be expanded to table-wide `UPDATE` merely to simplify the baseline. Final rebaseline review should compare each column grant to its owning command path and reject any column with no supported writer.

Classification: `KEEP` provisionally; exact per-column command-consumer review remains required before the final rebaseline authorization.

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

Security topology is no longer an unbounded `NEEDS_PROOF` area. The current effective model has explicit role/RLS/ACL structure and repeatable anomaly detection.

Remaining security/privilege work before rebaseline:

1. reconfirm the analyzer outputs on the final exact head;
2. complete the exact 12-column-grant → supported writer mapping;
3. ensure every SECURITY DEFINER routine retains an explicit caller/owner classification after the final routine manifest is updated for `0049`;
4. keep the three multi-policy trigger exceptions explicit rather than silently broadening them;
5. require `PUBLIC` grants, grantable runtime grants, append-only app mutation grants, RLS-without-policy and policy-without-RLS outputs to remain empty.

No new schema migration is justified by the current security evidence.
