# Migration agent rules

These instructions apply to `migrations/**` and supplement the repository-root `AGENTS.md`.

Before editing schema or migration code, read:

1. `docs/architecture/system-optimization-mode.md` — current pre-production cohesion/rebaseline policy;
2. `docs/architecture/pre-production-evolution-policy.md` — general pre-production evolution policy;
3. `docs/testing/current-guarantees.toml` — semantic guarantees that must survive schema evolution;
4. `docs/10-module-ownership-map.md` — current business ownership;
5. `docs/07-database-access-contract.md` — Python/PostgreSQL ownership and transaction boundary;
6. `migrations/README.md` — executable schema-history layout and current migration posture;
7. the current capability/domain contract affected by the change.

Use V2/V3 release material only as historical design/provenance unless a current contract explicitly adopts one of its guarantees or PostgreSQL patterns.

## Current posture

Request Engine is pre-production and is currently in an explicit system-optimization phase.

`migrations/versions/` is the current production-facing Alembic line. `migrations/sql/v3_candidate/` is **not** an active schema-development surface. `migrations/sql/design_chain/` is historical V2 design history.

Do not assume that a historical V3 candidate, release fingerprint, exact migration count or old revision name is normative for the current product.

Until a dedicated repository rebaseline is explicitly approved and designed, ordinary schema changes still append from the current single Alembic head. A rebaseline is a controlled architecture operation, not a shortcut for making migration tests easier.

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
Authoritative table/function/constraint involved
READ / PLAN / LOCK / VALIDATE / WRITE / EMIT protocol, if applicable
Serialization root and lock order
Tenant/RLS/role implications
Upgrade or rebaseline decision
Failure/concurrency behavior
Proof that will falsify a bad implementation
```

Do not infer `table -> domain entity -> repository -> endpoint`. Database objects may be integrity mechanisms, historical facts, serialization identities or narrow read/command surfaces rather than public product concepts.

`request_read.*` remains read-only contract space. `request_cmd.*` remains narrow consistency/worker/idempotency primitives inside Python-owned command orchestration; do not move workflow-sized business policy into stored procedures for convenience.

## Rebaseline rule

A current-schema rebaseline is permitted during this phase only as a dedicated change after the complete schema audit. Do not casually edit `0001_initial` or regenerate its payload while unrelated work is in progress.

A valid rebaseline must be derived from the intended current domain model and must disposition obsolete tables, functions, indexes, constraints, roles and RLS policies explicitly. It must then prove clean PostgreSQL 18 bootstrap to exactly one head plus the current invariant/security/concurrency/E2E evidence.

Historical V2/V3 artifacts may subsequently be retained, moved or removed according to their real provenance value; they must not remain active merely to preserve release archaeology.

## Testing

Use real PostgreSQL 18 whenever the claim depends on constraints, ranges, locks, isolation, `SKIP LOCKED`, RLS/privileges, leases/fencing or race behavior.

Concurrency tests use independent connections/transactions and deterministic synchronization. Do not simulate races with one transaction or timing-only sleeps.

Current-product proof follows the repository Alembic head dynamically. Do not pin current-product tests back to a historical revision name.
