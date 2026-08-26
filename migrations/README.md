# Database migrations

This directory owns executable PostgreSQL schema evolution and the provenance needed to explain how current and historical Request Engine schemas were produced.

The governing product-evolution policy is [`docs/architecture/pre-production-evolution-policy.md`](../docs/architecture/pre-production-evolution-policy.md). Its core rule is:

```text
freeze the evidence, not the future
```

## Schema/history tracks

```text
migrations/sql/design_chain/   historical V2.6→V2.10 executable design history
migrations/sql/v3_candidate/   frozen V3 release-candidate provenance
migrations/versions/           current production-facing Alembic revision line
migrations/f2_steps/           preserved pre-integration F2 SQL steps, not Alembic revisions
```

## Immutable historical baseline

`migrations/versions/0001_initial.py` is the released V3 production baseline and remains immutable historical migration evidence.

Do not rewrite, regenerate or squash `0001_initial`; do not back-port later feature DDL into it. Historical proof answers what was proven then; it must not become a permanent restriction on current pre-production product evolution.

## Current Alembic line

Before F4 introduces any SQL, the actual integrated production-facing line is:

```text
0001_initial
  -> 0002_operational_profile_contextual_supply
  -> 0003_f1_runtime_acl_completion
  -> 0004_geospatial_cross_tenant_discovery
  -> 0005_live_service_operations
  -> 0006_f3_historical_fact_hardening
```

`0006_f3_historical_fact_hardening` is the current predecessor head for F4 unless an explicit repository rebaseline occurs before the F4 migration is created.

Current CI must prove exactly one repository head and a database upgraded to that head.

## Integrated history vs unreleased feature-local migrations

Once a migration revision is integrated/released as supported history, treat it as append-only unless an explicit repository rebaseline decision says otherwise.

While Request Engine remains greenfield/pre-production with no customer-owned data or external compatibility commitment, unreleased feature-local migration chains may be intentionally consolidated before integration when all of the following hold:

1. the feature has not been deployed to customer-owned data;
2. consolidation is explicitly allowed by the pre-production evolution policy;
3. released/integrated historical baselines are not silently rewritten;
4. the final migration reproduces accepted schema/behavior instead of preserving known-wrong intermediate states;
5. exact-head bootstrap, current-product and relevant compatibility lanes pass after consolidation;
6. useful development provenance is retained separately when it improves reviewability.

This is a controlled pre-production rebaseline, not permission to delete failing history or bypass migration safety.

## F2 consolidation

F2 development SQL-bearing steps are preserved under `migrations/f2_steps/` and composed by:

```text
migrations/versions/0004_geospatial_cross_tenant_discovery.py
```

Those support modules are provenance, not independent Alembic revisions.

## F3 integration and historical-fact hardening

F3 entered the supported migration line as:

```text
0004_geospatial_cross_tenant_discovery
  -> 0005_live_service_operations
  -> 0006_f3_historical_fact_hardening
```

`0005_live_service_operations` introduces the live Queue/Delivery schema and primary F3 invariants.

`0006_f3_historical_fact_hardening` is a real append-only successor created after adversarial review to strengthen the immutability/append-preservation of historical execution facts, including completed ServiceSession and ServiceSessionInterruption history. It is not provisional history and must not be described as having been consolidated into `0005`.

F4 may add the next revision only after its normative schema semantics are accepted. The migration must declare the actual then-current head as `down_revision`.

## Frozen V3 candidate provenance

The frozen V3 candidate remains under:

```text
migrations/sql/v3_candidate/
```

and may be installed in release-proof/equivalence contexts with:

```bash
bash scripts/db/apply_v3_candidate.sh
```

It is not the mutable current schema-development line. Do not append post-V3 product changes there or modify frozen files merely to match later Alembic history.

## Historical V2 design chain

The V2.6→V2.10 design chain remains under `migrations/sql/design_chain/` and may continue to execute in its dedicated CI lane so historical SQL knowledge does not silently rot.

It is not production Alembic history and should not receive ordinary current-product migrations.

## Current schema-evolution requirements

For a schema change intended to become part of supported current history:

1. update the owning canonical domain/architecture contract when semantics or invariants change;
2. choose explicitly between append-only migration and justified pre-production rebaseline;
3. preserve immutable historical release artifacts that still serve provenance;
4. add/update PostgreSQL-backed tests for invariants, races, RLS/privileges and runtime behavior;
5. prove fresh bootstrap to the single current head;
6. prove supported upgrade paths when a real compatibility obligation exists;
7. preserve rollback policy explicitly and do not fake reversibility for semantically irreversible changes;
8. keep historical release/design evidence separate from current-product proof.

For F4 specifically, prediction/read-model values such as ETA, queue position and remaining live capacity must not be persisted as authoritative counters merely for migration convenience. F4 schema persistence is limited to accepted configuration/policy/supporting structures unless its normative contract is explicitly amended.

Once real customer-owned data or an external compatibility commitment exists, destructive history changes require explicit data migration, rollback/forward-safety and compatibility analysis.

## V3 release provenance

The V3 release baseline was closed with G01–G20 evidence, a frozen candidate inventory, reviewed `0001_initial`, structural fingerprinting, behavioral equivalence proof and production-like runtime-role bootstrap evidence.

See `docs/release/v3-release-gates.md` and `docs/release/v3-current-release-roadmap.md` for historical release provenance.

## SQL ownership

PostgreSQL object responsibilities remain:

```text
request_engine  authoritative relational state + integrity/RLS
request_read    versioned capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python remains owner of business-command orchestration and transaction framing. PostgreSQL protects structural truth, concurrency, leases/fencing and local invariant backstops.

No external/provider I/O occurs while authoritative database locks are held.
