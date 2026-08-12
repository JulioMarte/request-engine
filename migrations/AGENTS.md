# Migration agent rules

Before editing anything here, read:

1. `docs/11-capability-first-v3.md`
2. `docs/12-v3-transition-plan.md`
3. `docs/v3/sql-disposition.md` when present/relevant
4. `docs/07-database-access-contract.md`
5. `migrations/README.md`

Use `docs/02-pre-sql-domain-contract.md` as V2 safety/race source material only for concepts that survive V3. Do not preserve a deferred concept solely because it has an old invariant number or SQL object.

Rules:

- PostgreSQL target is 18+.
- The files under `sql/design_chain/` are pre-baseline V2 design history. Preserve their historical meaning; do not pretend they are production Alembic revisions.
- During the V3 transition, **do not append new V2.x design deltas by default**. Prefer a clean V3 candidate schema once object disposition is approved.
- Before production baseline exists, compatibility with speculative V2 object shapes is not a requirement.
- After production baseline exists, never rewrite applied migration history; add a new revision.
- Critical tenant relationships keep DB-provable tenant equality.
- Preserve proven typed FKs, stable serialization authorities where actually required, canonical lock protocols, append-oriented facts and deny-by-default interface privileges.
- Do not preserve duplicate serialization/state tables merely because V2 separated two conceptual nouns; prove that they represent independent truths first.
- `request_cmd` functions remain narrow data-centric primitives inside Python-owned transactions.
- SQL changes require PostgreSQL-backed tests for affected V3 invariants/races.
- Never weaken a constraint because application code already checks it unless the accepted V3 contract explicitly assigns that invariant to application policy.
- Booking reschedule must be tested for self-overlap and must validate final capacity state without temporary double-counting of claims being replaced.
- Worker tables for outbox/scheduled actions/communications require bounded retry, lease/fencing and terminal dead-letter semantics before production readiness.
