# Database migrations

This directory owns executable PostgreSQL schema evolution and the historical design evidence that is still deliberately exercised by CI.

Current governing policy:

- `docs/architecture/continuous-evolution-policy.md` — permanent schema/application evolution model;
- `docs/architecture/system-optimization-mode.md` — current pre-production optimization mode;
- `docs/architecture/pre-production-evolution-policy.md` — current pre-production compatibility freedom;
- `docs/testing/current-guarantees.toml` — semantic guarantees that evolution must preserve or explicitly supersede.

The permanent rule is **immutable history, evolvable future**. The accepted baseline is protected as history; current schema continues to evolve through appended migrations.

## Canonical layout

```text
migrations/versions/          active Alembic graph
migrations/baseline/          immutable payload for accepted 0001_initial
migrations/sql/design_chain/  historical V2 design proof still required by CI
```

`migrations/versions/0001_initial.py` is the accepted pre-production baseline. It bootstraps the ten audited Request Engine/platform bootstrap roles (exact topology, no memberships), ensures the seven audited extension roles with their historical fail-closed ensure blocks, installs the checksummed PostgreSQL 18 schema payload from `migrations/baseline/` and then runs the post-install extension-role audit.

The current baseline was promoted by the **2026-10-23 rebaseline**, which collapsed the former `0001_initial` + `0002..0047` chain (historical head `0047_reservation_calendar_read`). See `docs/audits/postgresql-rebaseline-0047.md` for the effective-schema audit, object disposition and the clean-cluster reproduction proof.

The baseline is **history now, not a mutable schema template**. Future product changes append `0002+` revisions. Do not regenerate or edit `0001_initial` or `migrations/baseline/` merely because current HEAD evolves.

## Baseline vs current HEAD

CI protects two different contracts:

1. **accepted baseline integrity** — `0001_initial` must continue to install from a clean PostgreSQL 18 cluster with the exact manifested role topology and accepted baseline model;
2. **current-product integrity** — `alembic upgrade head` must reach the repository's single current head and pass the complete current guarantee, security, concurrency and E2E proof set.

Those contracts must not be collapsed into `HEAD == 0001`. A reviewed `0002+` is legitimate evolution and must not require rewriting the baseline.

The accepted baseline model recorded in `migrations/baseline/manifest.json` is:

```text
164 relations = 153 tables + 11 views
1,820 columns
2,673 validated constraints
442 indexes
376 routines
218 triggers
118 RLS policies
17 roles = 10 bootstrap roles + 7 extension roles
0 role memberships
819 column grants
```

These counts describe the accepted `0001` checkpoint. They are **not ratchets for current HEAD**. Current product counts may change through legitimate migrations; baseline-integrity proof remains pinned to the historical baseline.

Cluster role extensions keep their own audited semantics inside the baseline.
`migrations/baseline/0001_extension_roles.sql` holds the historical ensure blocks of
`request_retention_recorder`, `request_proof_cleanup_worker`,
`request_webauthn_retention[_definer]`, `request_http_admission_definer` and
`request_operator_metrics[_definer]`: each creates its closed-namespace NOLOGIN group
only when missing and fails closed on unsafe attributes, memberships or pre-existing
local ACLs (these groups may legitimately have isolated LOGIN members, so they are not
held to the bootstrap roles' empty-membership contract). The recorder's exact ACL
inventory and the WebAuthn dependent-foreign-key check run after the schema from
`0001_post_install_audit.sql`. A cluster that still holds the legacy
`request_engine_retention_recorder` group is incompatible with this baseline. Preserve
that cluster and install in a separate clean cluster; do not reset a shared cluster
merely to make installation pass.

Fresh-install identity is intentionally **not** a literal part of the checkpoint: `platform_instance.id`, the two built-in authority UUIDs and their creation timestamps are generated anew on every installation. Seed-state evidence normalizes only those fields, and CI proves two clean installs do not reuse the same installation UUIDs.

## Historical/provenance surfaces

`migrations/sql/design_chain/` is retained because the repository's V2 design-history status check still executes it through `scripts/db/apply_design_chain.sh`. It is not the current schema source of truth.

The old V3 payloads, candidate SQL, feature-step helper modules, the certified pre-rebaseline 0002..0094 chain (GitHub Actions run 36354361866) and the 0002..0047 chain collapsed on 2026-10-23 (last present at commit `afbbe397681732399702aad34da917e15d503018`) are intentionally absent from current HEAD. Their provenance remains in Git history; keeping dead executable migration machinery beside the accepted baseline would create a false second authority.

Existing databases created from the collapsed chain cannot upgrade across this
rebaseline: their recorded revision no longer exists. The code change does not
migrate or delete their data. Preserve the existing project/volume and use the
parallel-install procedure in `docs/audits/postgresql-rebaseline-0047.md`. Do not
stamp the new revision over an old database. Reusing the name `0001_initial` also
means an old database at the former `0001` cannot be recognized by revision alone;
use a genuinely clean cluster, not just an apparently known revision.

## Schema-change discipline

For any new schema change:

1. identify the owning capability and current guarantee affected;
2. classify compatibility/data risk using `continuous-evolution-policy.md`;
3. append a new Alembic revision from the current single head;
4. use **expand → migrate → contract** when old/new application or data representations must coexist;
5. review RLS, ownership, grants and SECURITY DEFINER impact;
6. review transaction, lock, range/timezone and concurrency semantics;
7. make non-trivial backfills resumable/idempotent/bounded/observable as applicable;
8. add PostgreSQL-backed falsification evidence for database claims;
9. keep accepted historical revisions and `migrations/baseline/` unchanged;
10. prove clean `upgrade head` and the current-product proof map with no gaps.

For production-sized tables, explicitly assess DDL lock/availability consequences. Use staged constraint validation, concurrent index creation or other PostgreSQL mechanisms when they materially reduce production risk; do not apply them mechanically when an ordinary transactional migration is demonstrably safer.

PostgreSQL target is 18+.

## SQL ownership

```text
request_engine  authoritative relational state + integrity/RLS
request_read    capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python owns business-command orchestration and transaction framing. PostgreSQL owns structural truth, concurrency, leases/fencing and local invariant backstops. No external/provider I/O occurs while authoritative database locks are held.

## Production compatibility trigger

Pre-production freedom ends when Request Engine stores customer-owned production data that must survive upgrades or when an external/independently deployed consumer has a supported compatibility promise.

From that point, schema changes still evolve normally, but destructive operations require explicit data/consumer migration and roll-forward/rollback analysis. Deployment overlap must be considered, and published surfaces require controlled deprecation/removal criteria.

History remains immutable; the future remains evolvable.

## Future rebaseline policy

A future destructive rebaseline is possible only while pre-production and only as an explicit repository-architecture operation backed by another effective-schema audit and clean-cluster reproduction proof. Never silently rewrite the accepted baseline as part of a feature or cleanup PR.

After customer-owned production data exists, rebaseline is **not a cleanup technique**. Any extraordinary lineage replacement becomes a production data migration/cutover project with explicit transfer and recovery semantics.
