# Database migrations

This directory owns executable PostgreSQL schema evolution and the historical design evidence that is still deliberately exercised by CI.

Current governing policy:

- `docs/architecture/system-optimization-mode.md`
- `docs/architecture/pre-production-evolution-policy.md`
- `docs/testing/current-guarantees.toml`

## Canonical layout

```text
migrations/versions/          active Alembic graph
migrations/baseline/          immutable payload for accepted 0001_initial
migrations/sql/design_chain/  historical V2 design proof still required by CI
```

`migrations/versions/0001_initial.py` is the accepted pre-production baseline. It bootstraps the six audited Request Engine roles and installs the checksummed PostgreSQL 18 schema payload from `migrations/baseline/`.

The baseline is **history now, not a mutable schema template**. Future product changes append `0002+` revisions. Do not regenerate or edit `0001_initial` or `migrations/baseline/` merely because current HEAD evolves.

## Baseline vs current HEAD

CI protects two different contracts:

1. **accepted baseline integrity** — `0001_initial` must continue to install from a clean PostgreSQL 18 cluster with the exact manifested role topology and accepted baseline model;
2. **current-product integrity** — `alembic upgrade head` must reach the repository's single current head and pass the complete current guarantee, security, concurrency and E2E proof set.

Those contracts must not be collapsed into `HEAD == 0001`. A reviewed `0002+` is legitimate evolution and must not require rewriting the baseline.

The accepted baseline model recorded in `migrations/baseline/manifest.json` is:

```text
99 relations = 90 tables + 9 views
1,085 columns
1,575 validated constraints
276 indexes
145 routines
162 triggers
84 RLS policies
6 Request Engine roles
0 role memberships
12 column grants
```

## Historical/provenance surfaces

`migrations/sql/design_chain/` is retained because the repository's V2 design-history status check still executes it through `scripts/db/apply_design_chain.sh`. It is not the current schema source of truth.

The old V3 Base85 payload, V3 candidate SQL, feature-step helper modules and the pre-rebaseline `0002..0050` chain are intentionally absent from current HEAD. Their provenance remains in Git history and historical documentation; keeping dead executable migration machinery beside the accepted baseline would create a false second authority.

## Schema-change discipline

For any new schema change:

1. identify the owning capability and current guarantee affected;
2. append a new Alembic revision from the current single head;
3. review RLS, ownership, grants and SECURITY DEFINER impact;
4. review transaction, lock, range/timezone and concurrency semantics;
5. add PostgreSQL-backed falsification evidence for database claims;
6. keep `0001_initial` and `migrations/baseline/` unchanged;
7. prove clean `upgrade head` and the current-product proof map with no gaps.

PostgreSQL target is 18+.

## SQL ownership

```text
request_engine  authoritative relational state + integrity/RLS
request_read    capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python owns business-command orchestration and transaction framing. PostgreSQL owns structural truth, concurrency, leases/fencing and local invariant backstops. No external/provider I/O occurs while authoritative database locks are held.

## Future rebaseline policy

Request Engine is still pre-production, so a future destructive rebaseline is possible in principle, but it is **not** ordinary schema evolution. It would require another explicit effective-schema audit, clean-cluster reproduction proof and repository-level decision. Never silently rewrite the accepted baseline as part of a feature or cleanup PR.
