# Migration agent rules

These instructions apply to `migrations/**` and supplement the repository-root `AGENTS.md`.

Before editing schema or migration code, read:

1. `docs/architecture/continuous-evolution-policy.md`;
2. `docs/architecture/system-optimization-mode.md`;
3. `docs/architecture/pre-production-evolution-policy.md`;
4. `docs/testing/current-guarantees.toml`;
5. `docs/10-module-ownership-map.md`;
6. `docs/07-database-access-contract.md`;
7. `migrations/README.md`;
8. the current capability/domain contract affected by the change.

Use V2/V3 release material only as historical design/provenance unless a current contract explicitly adopts one of its guarantees or PostgreSQL patterns.

## Current posture

Request Engine is pre-production and has completed the audited PostgreSQL rebaseline on this line.

The migration layout is now:

```text
migrations/versions/          active Alembic graph
migrations/baseline/          immutable accepted 0001 payload
migrations/sql/design_chain/  historical V2 proof retained by CI
```

`0001_initial` and `migrations/baseline/` are accepted history. Ordinary schema work **must append `0002+`** from the current single Alembic head. Do not regenerate, edit or replace the baseline to make later work easier.

The permanent migration rule is:

```text
immutable history, evolvable future
```

Do not assume that historical V2/V3 candidate names, release fingerprints, old migration counts or removed revision names are normative for current product behavior.

## Database guarantees

PostgreSQL target is 18+.

Preserve or strengthen applicable current guarantees, especially:

- tenant Organization equality and RLS/foreign-row opacity;
- explicit authority and least-privilege runtime roles;
- capacity serialization and contested-operation safety;
- idempotency and transaction atomicity;
- immutable/reconstructable business provenance;
- lease/fencing/outbox durability;
- temporal, timezone, DST and half-open range semantics;
- deterministic lock roots/order and concurrent-loser behavior.

Never weaken a database invariant merely because application code also checks it unless the current accepted contract explicitly moves that responsibility out of PostgreSQL with equal-or-stronger proof.

No external/provider I/O may occur while authoritative database locks are held.

## Schema-change discipline

Before writing DDL, identify:

```text
Business owner
Current guarantee(s) affected
Change class / compatibility requirement
Authoritative table/function/constraint involved
READ / PLAN / LOCK / VALIDATE / WRITE / EMIT protocol, if applicable
Serialization root and lock order
Tenant/RLS/role implications
Failure/concurrency behavior
Migration/backfill/roll-forward implications
Proof that will falsify a bad implementation
```

Do not infer `table -> domain entity -> repository -> endpoint`. Database objects may be integrity mechanisms, historical facts, serialization identities or narrow read/command surfaces rather than public product concepts.

`request_read.*` remains read-only contract space. `request_cmd.*` remains narrow consistency/worker/idempotency primitives inside Python-owned command orchestration; do not move workflow-sized business policy into stored procedures for convenience.

## Baseline and forward-evolution rule

The accepted baseline is frozen as **migration history**, not as a ceiling on the product schema.

A valid new migration:

1. leaves accepted/applied revisions and `migrations/baseline/` unchanged;
2. appends from the single current Alembic head;
3. preserves bootstrap/role compatibility where applicable;
4. proves the resulting current HEAD against the current guarantee map;
5. adds or updates exact PostgreSQL evidence for changed invariants;
6. does not add a guardrail that requires the current head to remain a specific revision forever.

When old/new representations must coexist across deployment or data migration, use **expand → migrate → contract**. Do not perform an immediate destructive rename/drop solely because it is simpler in one local checkout.

For non-trivial backfills, require appropriate restart/idempotency, bounded transaction, observability and convergence semantics. For production-size DDL, explicitly assess lock and availability behavior rather than assuming all DDL is operationally equivalent.

A future destructive rebaseline is a separate architecture operation requiring a new effective-schema audit and independent clean-cluster proof. It must never happen implicitly inside ordinary feature work. After customer-owned production data exists, rebaseline is not a cleanup technique; extraordinary lineage replacement is a production migration/cutover project.

Historical SQL or helper modules that are not executed by a current proof or active migration belong in Git history, not beside the active migration authority. `migrations/sql/design_chain/` is the present exception because CI still executes it as V2 design-history evidence.

## Testing

Use real PostgreSQL 18 whenever the claim depends on constraints, ranges, locks, isolation, `SKIP LOCKED`, RLS/privileges, leases/fencing or race behavior.

Concurrency tests use independent connections/transactions and deterministic synchronization. Do not simulate races with one transaction or timing-only sleeps.

Current-product proof follows the repository Alembic head dynamically. Accepted-baseline integrity is proved separately from current HEAD; never pin current-product tests back to `0001_initial`.

When adding architecture tests around migrations, protect transition safety and invariants rather than exact future schema counts, revision numbers or object inventories. Exact historical fingerprints/counts are valid only when explicitly pinned to the historical artifact they describe.
