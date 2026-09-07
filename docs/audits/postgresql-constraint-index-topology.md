# PostgreSQL constraint and index topology audit

Status: active pre-rebaseline effective-model audit

Source checkpoint: exact PostgreSQL 18 current-product catalog from green head `3aa13def2102e3fdb225d5a7302971f8f8db824b`, CI #4126, after migrations through `0049_consolidate_recovery_bump`.

A later exact-head artifact must reconfirm these structural facts before rebaseline. The counts below are evidence for the intended current schema, not permanent repository-shape limits.

## Effective counts

The #4126 catalog contains:

- **1,575 constraints**, all validated;
- **276 indexes**, all valid;
- **0 exact index-definition duplicates** according to the catalog cohesion analyzer.

Constraint types:

| Type | Count | Interpretation |
|---|---:|---|
| NOT NULL | 770 | required relational state |
| CHECK | 392 | local value/state invariants |
| FOREIGN KEY | 198 | relational/tenant provenance links |
| UNIQUE | 107 | natural/business/concurrency identity |
| PRIMARY KEY | 90 | row identity |
| constraint trigger | 13 | deferred cross-row consistency |
| EXCLUDE | 5 | temporal overlap/cardinality invariants |
| **Total** | **1,575** | |

Classification: the topology is structurally healthy. No migration is justified merely by the object count.

## Invalid or incomplete objects

The effective catalog contains:

- **0 unvalidated constraints**;
- **0 invalid indexes**;
- **0 exact duplicate index definitions** after ignoring only index names;
- no reviewed same-predicate non-unique btree index where one key list is an obvious left-prefix duplicate of another.

Classification: no current `REMOVE` finding from invalidity or exact/prefix duplication.

## Exclusion constraints — 5/5 KEEP

Exclusion constraints are expensive enough that each one must correspond to a real product invariant. All five do.

### `booking_context_terms_no_active_overlap`

Prevents ambiguous simultaneous effective BookingContextTerms authority for the same contextual scope. Booking must resolve one commercial/configuration provenance set for an appointment context rather than arbitrarily choosing between overlapping active terms.

Classification: `KEEP` — terms authority/provenance invariant.

### `discovery_publications_no_active_overlap`

Prevents conflicting overlapping effective Discovery publication scopes for the same governed publication identity. This supports deterministic cross-tenant discoverability and the publication/mapping handoff fence.

Classification: `KEEP` — Discovery authority/concurrency invariant.

### `location_hours_exceptions_no_active_overlap`

Prevents contradictory overlapping active Location-hours exceptions. Without it, the Location operational calendar could contain mutually competing exception facts over the same interval.

Classification: `KEEP` — Catalog temporal-authority invariant.

### `resource_location_assignments_no_overlap`

Prevents overlapping assignments for the **same Organization + Resource + Location** while intentionally allowing the same Resource to have concurrent assignments at different Locations.

This is the correct current product invariant. It must not be strengthened to Resource-global exclusivity: a Resource may be eligible at multiple Locations concurrently, while all actual commitments still consume the same Resource capacity root.

Classification: `KEEP` — Booking contextual-provenance invariant.

### `resource_location_exceptions_no_active_overlap`

Prevents contradictory overlapping assignment-specific Resource availability exceptions within one contextual assignment.

Classification: `KEEP` — Booking temporal/contextual-supply invariant.

## Deferred constraint triggers — 13

The catalog also contains 13 constraint-backed deferred triggers. These are not evidence of accidental duplication simply because PostgreSQL exposes them through constraint and trigger catalogs. They are the deferred half of cross-row consistency guarantees where immediate row-local validation is insufficient.

The trigger installation topology is classified separately in `postgresql-trigger-topology.md`. A future rebaseline must preserve the semantic constraint/trigger pair where both are required; it must not count the two catalog representations as two independent business invariants and delete one mechanically.

Classification: `KEEP` according to the trigger-topology manifest.

## Unique and primary-key indexes

Primary-key and UNIQUE constraints legitimately materialize backing indexes. These are not redundant merely because an index and a constraint describe the same key; the index is PostgreSQL's enforcement/access structure for the constraint.

The analyzer's duplicate-index comparison therefore preserves `is_primary` and `is_unique` in the structural signature. It does not recommend dropping constraint-owned indexes because another non-unique index happens to mention the same columns.

Classification: constraint-owned enforcement indexes `KEEP` unless a separate exact redundant non-constraint access path is proven.

## Foreign-key indexing policy

A foreign key does **not** automatically require a matching child-side index. PostgreSQL uses the referenced-side unique/primary key to enforce parent existence; a child index is workload-dependent and mainly affects parent UPDATE/DELETE checks and child-side access plans.

Therefore this audit rejects the mechanical rule:

```text
one foreign key -> one mandatory child index
```

A missing left-prefix index is a review candidate only when a current query, lock, delete/update path or measured plan requires it. Conversely, an index must not be retained solely because it resembles a foreign-key column list if no current access path or invariant benefits from it.

Classification: workload/plan-driven, not shape-driven.

## Current performance-sensitive index decisions

Previously resolved current decisions remain valid:

- redundant `service_sessions_queue_idx` was removed because an existing unique index already provided the same access path;
- `reservations_org_during_gist` was added because the tenant-scoped Day Board predicate needs `organization_id = ... AND during && ...` support;
- the redundant waitlist index removed by `0047` remains absent;
- the #4126 analyzer reports no new exact index duplicate after these changes.

Classification: `KEEP`, subject to final exact-head plan/proof reconfirmation where the guarantee is plan-sensitive.

## What this audit does not claim

A static catalog cannot prove that all 276 indexes earn their write/storage cost under real production workload; Request Engine has not launched and therefore has no representative production `pg_stat_user_indexes` history.

Dropping low-usage indexes before launch based on synthetic usage counters would be false precision. The pre-launch audit can prove:

- no invalid indexes;
- no exact duplicates;
- no obvious reviewed left-prefix duplicates;
- explicit justification for high-cost exclusion/GiST structures;
- plan tests for known performance-critical predicates.

Post-launch index pruning should use workload telemetry and plan evidence rather than continue to expand this pre-launch shape audit indefinitely.

## Rebaseline implication

Constraint/index topology is no longer an unbounded `NEEDS_PROOF` area. The current effective model has validated constraints, valid indexes, no exact duplicates, and explicit justification for all five exclusion constraints.

Before final rebaseline authorization:

1. reconfirm `invalid_indexes = []`, `unvalidated_constraints = []` and `exact_index_definition_duplicates = []` on the final exact head;
2. preserve the five exclusion constraints and the deferred consistency topology unless a specific invariant is deliberately redesigned;
3. retain plan-oriented proofs for known performance-critical access paths;
4. do not invent pre-launch index removals from absent production usage statistics.

No new schema migration is justified by the current constraint/index evidence.
