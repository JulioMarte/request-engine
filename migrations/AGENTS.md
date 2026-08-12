# Migration agent rules

Before editing anything here, read:

1. `docs/11-capability-first-v3.md`
2. `docs/v3/01-capability-contracts.md`
3. `docs/v3/02-pre-sql-contract.md`
4. `docs/v3/sql-disposition.md`
5. `docs/07-database-access-contract.md`
6. `migrations/README.md`

Use V2 SQL/docs only as design history and as a source of proven PostgreSQL patterns where a V3 promise survives. `docs/v3/02-pre-sql-contract.md` is authoritative for current cardinality, serialization roots, lock order, transaction protocols, `V3-Ixx` invariants and race requirements.

Rules:

- PostgreSQL target is 18+.
- `sql/design_chain/` is pre-baseline V2 design history. Preserve its historical meaning; do not pretend it is production Alembic history.
- Do **not** append new V2.x deltas by default. The next schema artifact is a clean reduced V3 candidate.
- Before production baseline exists, compatibility with speculative V2 object shapes is not a requirement.
- After production baseline exists, never rewrite applied migration history; add a new revision.
- Critical tenant relationships keep DB-provable Organization equality and V3 tenant-owned tables implement the accepted RLS defense-in-depth model.
- Runtime roles never use schema-owner/superuser privileges; cross-tenant worker discovery uses narrow controlled claim surfaces.
- Preserve typed FKs, stable serialization roots actually required by V3, canonical lock protocols, append-oriented facts and deny-by-default interface privileges.
- V3 baseline uses concrete `Resource` as capacity lock root; do not recreate a separate one-to-one CapacityAuthority table.
- V3 baseline uses one `CapacityClaim` truth for Hold/Reservation capacity; do not recreate ResourceAllocation one-to-one duplication.
- V3 baseline has no ReservationItem, OutcomeScope, universal Workflow, CapacityPool, PlanningRevision, advanced payment, Dispatch or Fulfillment dependency.
- `request_cmd` functions remain narrow data-centric primitives inside Python-owned transactions.
- SQL changes require PostgreSQL-backed tests for affected `V3-Ixx` invariants/races.
- Never weaken a DB invariant because application code also checks it unless the V3 contract explicitly assigns it to application-only policy.
- Booking reschedule must prove self-overlap and final-state validation without temporary double counting.
- Hold wall-clock expiry must block confirmation even before cleanup updates persisted state.
- ServiceQueue `CallNext`, SlotOpportunity/SlotOffer, ScheduledAction, outbox and idempotency races require real PostgreSQL tests.
- Outbox/ScheduledAction worker state requires lease/fencing, bounded retries, terminal dead-letter state and manual replay semantics before production readiness.
- No external/provider I/O may occur while authoritative DB locks are held.
- Do not create `0001_initial` until the schema construction gate in `docs/v3/02-pre-sql-contract.md` passes.
