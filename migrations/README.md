# Database migrations

This directory owns executable PostgreSQL schema evolution and the provenance needed to explain how Request Engine reached its current schema.

Current governing policy:

- `docs/architecture/system-optimization-mode.md`
- `docs/architecture/pre-production-evolution-policy.md`
- `docs/testing/current-guarantees.toml`

The current rule is:

```text
freeze guarantees, not accidental repository shape
```

## Current executable line

`migrations/versions/` is the current production-facing Alembic line. Current-product CI must prove exactly one repository head, upgrade a clean PostgreSQL 18 database to that head, and execute the accepted current guarantees against it.

Do not hard-code a historical revision as the permanent current head.

## Historical/provenance surfaces

```text
migrations/sql/design_chain/   historical V2.6→V2.10 design history
migrations/sql/v3_candidate/   historical V3 release-candidate provenance
migrations/f2_steps/           preserved F2 development SQL/support provenance
migrations/sql/v3_initial/     encoded payload backing the historical 0001 V3 baseline
```

These locations explain past releases/design steps. They are not active product-schema development surfaces.

## Current optimization posture

Request Engine has no customer-owned production data or externally committed compatibility contract and is currently undergoing a deliberate cohesion/schema audit.

Therefore the current schema is **CONTROLLED but mutable**. The repository may eventually perform an intentional pre-production rebaseline if the audit shows that carrying the historical migration chain materially harms correctness, clarity or maintainability.

Until that rebaseline is explicitly designed and approved:

1. ordinary schema changes append from the current single Alembic head;
2. do not casually edit `0001_initial` or its encoded payload;
3. do not append current-product changes to `sql/v3_candidate`;
4. do not preserve obsolete schema solely because an old V2/V3 proof once referenced it;
5. do not delete a database guarantee merely to simplify the schema.

This temporary caution around `0001_initial` is sequencing discipline, not a declaration that its shape is a permanent product ceiling.

## Rebaseline gate

A repository rebaseline must be a dedicated architecture change after the complete current-schema audit. It must not be a blind `pg_dump` of the existing head.

Before creating a replacement baseline, disposition every current database object relevant to product behavior:

```text
tables and columns
primary/foreign/unique/exclusion/check constraints
indexes
sequences/defaults
views/read contracts
request_cmd functions
triggers
RLS policies
roles/grants/security-definer surfaces
extensions
migration-only compatibility objects
```

For each removal or redesign, identify the owning capability and affected guarantee.

A valid replacement baseline must:

1. encode the intended current domain model rather than every historical intermediate state;
2. preserve or strengthen applicable entries in `docs/testing/current-guarantees.toml`;
3. bootstrap a clean PostgreSQL 18 database to exactly one Alembic head;
4. preserve explicit tenant/RLS/role boundaries;
5. preserve authoritative transaction, lock, capacity, idempotency and provenance semantics;
6. pass current security, concurrency, worker and E2E evidence;
7. record which former migration/release artifacts remain only as Git/tag/release provenance.

Once customer-owned data or an external compatibility promise exists, destructive rebaseline stops being an ordinary option and a production migration/versioning policy becomes mandatory.

## SQL ownership

PostgreSQL object responsibilities remain:

```text
request_engine  authoritative relational state + integrity/RLS
request_read    capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python remains owner of business-command orchestration and transaction framing. PostgreSQL protects structural truth, concurrency, leases/fencing and local invariant backstops.

No external/provider I/O occurs while authoritative database locks are held.

## Schema-change checklist

For any current schema change:

1. identify the business owner and current semantic contract;
2. identify affected guarantees in `current-guarantees.toml`;
3. choose explicitly between ordinary append-only evolution and the separately approved rebaseline path;
4. review tenant/RLS/privilege impact;
5. review transaction/lock/concurrency impact;
6. add or adapt PostgreSQL-backed falsification evidence;
7. prove clean upgrade/bootstrap to the single current head;
8. do not claim historical compatibility unless it is actually required and tested.
