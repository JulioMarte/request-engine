# PostgreSQL rebaseline 0047 — effective-schema audit and disposition

Status: **candidate integrated without commit into the local
`feature/admin-dashboard-completion` worktree on 2026-10-23**. The original
candidate evidence below is provenance; follow-up validation is recorded separately
and exact-head GitHub CI remains required before integration into `development`.

## Why

Request Engine is operating under the pre-production policy. This audit does not
establish the absence of customer-owned data in every environment. Local development
contains identities, grants, reservations, queue entries and service sessions;
those existing data and volumes are preserved by this code-only operation.
After ADR 0020 (change feed), tenant-controller v9 and the front-desk read contracts,
the accepted 0094-era `0001_initial` carried 46 appended revisions (`0002..0047`)
including cluster-role evolution (`0013` → `0020` rename), ACL-poisoning guards and
populated-upgrade proofs whose old graph is no longer supported by the new code. The
product owner requested the dedicated destructive rebaseline permitted by
`docs/architecture/system-optimization-mode.md` §4.

This is a **history collapse, not a schema redesign**. Every effective object at
historical head `0047_reservation_calendar_read` is kept as-is.

## Procedure (precedent: PR #135, `feature/rebaseline-0094`)

1. **Cluster A** — fresh PostgreSQL 18.6 container; the former chain
   `0001_initial (0094 baseline) + 0002..0047` installed with `alembic upgrade head`
   from commit `afbbe397681732399702aad34da917e15d503018`.
2. Effective catalog exported with `export_schema_catalog.py`, `export_role_catalog.py`
   (now including the `request_retention_%` namespace), `export_seed_data_catalog.py`
   and analysed with `analyze_schema_cohesion.py`.
3. Payload materialized by the transitional `scripts/db/build_rebaseline_0047_candidate.py`
   (PostgreSQL 18.6 `pg_dump`, full plain dump with `--inserts --rows-per-insert=1`,
   `alembic_version` excluded) and `scripts/db/extract_rebaseline_0047_extension_roles.py`;
   the manifest by `scripts/db/write_rebaseline_0047_manifest.py`. These three scripts
   only run against the pre-collapse tree and were removed after promotion; they remain
   in Git history.
4. **Cluster B** — independent fresh PostgreSQL 18.6 container; the new single
   `0001_initial` installed; the same catalogs exported and compared.

## Effective model at the cut (cluster A = cluster B)

```text
164 relations = 153 tables + 11 views (10 with view options)
1,820 columns
2,673 validated constraints (5 EXCLUDE)
442 indexes (93 partial), 0 invalid
376 routines (270 SECURITY DEFINER)
218 triggers
118 RLS policies on 103 RLS relations (64 FORCE RLS)
819 column grants, 2,250 table grants, 634 routine grants, 10 default ACLs
1 object comment (request_engine.outbox_messages column, ADR 0020)
0 sequences, 0 enums
17 roles = 10 bootstrap roles + 7 extension roles, 0 memberships, 0 role settings
seed/reference state: 18 rows in 5 tables
  identity_authorities (2, installation-local identity), platform_instance (1),
  initial_controller_policies v1..v9 (9), platform_owner_policies (5),
  http_auth_admission_state singleton (1)
```

## Analyzer findings and disposition

All structural anomaly lists are empty except one:

| Finding | Disposition |
|---|---|
| `exact_index_definition_duplicates`: `staff_memberships_org_id_unique` (historical 0011) duplicates `staff_memberships_org_id_uq` (historical 0009); both foreign keys (`staff_invitations`, `staff_member_profiles`) use `_uq` | **KEEP** in the collapse. Dropping it is ordinary `0002+` evolution. The manifest records it under `accepted_analyzer_findings`; `verify_accepted_baseline.py` now requires the findings to equal that record exactly (a new or vanished finding fails). |

Object disposition: **KEEP all** tables, columns, constraints, indexes, views and
view options, routines (owners, `SECURITY DEFINER`, `search_path`), triggers, RLS
policies, grants/ACLs, default ACLs, the comment and all seed rows. Nothing was dropped
or reshaped.

## Payload decisions

- **Roles.** `0001_roles.sql` (10 bootstrap roles, exact-topology/empty-membership
  contract) is byte-identical to the 0094 payload. The 7 extension roles
  (`request_retention_recorder`, `request_proof_cleanup_worker`,
  `request_webauthn_retention[_definer]`, `request_http_admission_definer`,
  `request_operator_metrics[_definer]`) keep the per-role **audited ensure semantics**
  of their historical revisions (they deliberately allow isolated LOGIN members):
  `0001_extension_roles.sql` contains the verbatim 0024/0037/0038/0039 ensure blocks and
  the 0013 creation under the 0020 canonical name, and runs before the schema. Two checks
  need the installed schema and run afterwards from `0001_post_install_audit.sql`: the
  0020 recorder inventory and the 0037 dependent-foreign-key check. The manifest pins the
  resulting extension-role attributes. A cluster still holding the legacy
  `request_engine_retention_recorder` fails closed.
- **Comments are kept** (the precedent used `--no-comments`; the head now owns a
  migration comment). Only `COMMENT ON EXTENSION` is dropped because `CREATE EXTENSION`
  recreates it.
- **Installation-local identity** is canonicalized exactly as in 0094: built-in
  authority / platform-instance UUIDs and timestamps come from PostgreSQL defaults on
  every install.
- **Expression-tree fidelity.** Four CHECK constraints were written as
  `length(x) BETWEEN a AND b AND …`. Replaying pg_dump's deparsed text flattens that
  nested AND, which is logically identical but deparses differently. The payload
  restores the original `BETWEEN` source form for those four, so the stored expression
  trees are identical.
- **Concurrent indexes.** The six 0039 metric indexes and the 0046/0047 indexes built
  `CONCURRENTLY` are created by plain `CREATE INDEX` on a fresh, empty install. The
  resulting index definitions are identical and valid.

## Independent clean-cluster reproduction proof

Run locally on 2026-10-23, cluster A (`re-pg-rb-a`) vs cluster B (`re-pg-rb-b`), both
`postgres:18` (18.6):

| Check | Result |
|---|---|
| `compare_schema_catalogs.py` | equivalent |
| `compare_role_catalogs.py` (17 roles) | equivalent |
| `compare_seed_data_catalogs.py` (normalized) | equivalent; B's catalog byte-identical to the manifested one |
| `pg_dump --schema-only` (with comments, owners, ACLs), A vs B | **byte-identical**, 2,010,892 bytes |
| `pg_dumpall --roles-only --no-role-passwords` (Request Engine roles) | identical |
| `verify_accepted_baseline.py` on cluster B | PASS |
| `prove_baseline_integrity.sh` (third clean cluster + identity probe) | PASS; two installs got distinct installation UUIDs |
| `prove_multidatabase_migration_compatibility.py` | PASS (second database reached `0001_initial` reusing shared roles) |

The only differences between the clusters are the ones the proof excludes on purpose:
object OIDs and installation-local UUIDs and timestamps.

## Test disposition (`docs/testing/repository-governance-contract.md`)

| Test | Disposition | Guarantee that remains protected |
|---|---|---|
| `tests/db/test_tenant_controller_v7_populated_upgrade.py` | **REMOVE (HISTORICAL)**: it upgraded a populated 0039 database through 0040. That transition is no longer executable in the replacement graph; retained old databases still require their old code. | v7/v9 adoption authority is still covered by `test_tenant_controller_v9_adoption.py`, `test_controller_policy_upgrade.py`, `test_controller_policy_adoption_provenance.py` and `test_initial_controller_policy.py`. |
| `tests/db/test_tenant_controller_v9_populated_upgrade.py` | **ADAPT** → `test_tenant_controller_v9_adoption.py`. The physical 0043→head half is gone; the adoption half runs on head. | A v8 root reaches v9 only through adoption with the exact, independently listed 15-capability delta. Provisioning v7/v8 grants none of it. No other root, organization or policy row changes. |
| `tests/db/test_webauthn_populated_upgrade.py` | **REMOVE (HISTORICAL)**: legacy pre-0034 passkey sources cannot exist after the collapse. | `INV-NATIVE-WEBAUTHN-DISCOVERABLE-LOGIN-001` is still covered by `test_webauthn_persistence.py` and `tests/e2e/test_native_webauthn_login_http.py`. The proof-map entry was removed. |
| `test_shared_http_auth_admission.py::…schema_acl_transactionally` | **ADAPT**: the ACL poisoning now targets the fresh database before `0001`. | Installation fails closed and transactionally on a pre-existing local ACL, and does not rewrite it. |
| `test_operator_metrics_projection.py::test_column_acl_poisoning_rejects_baseline_before_any_object_is_installed` | **ADAPT** (renamed from `…_0039_…`) | Same, for a column ACL held by `request_operator_metrics`. |
| `test_webauthn_challenge_retention.py::test_upgrade_rejects_unexpected_shared_role_acl_without_rewriting_it` | **ADAPT** | Same, for both WebAuthn retention roles. |
| `test_temporary_proof_inventory.py::test_current_retention_role_inventory_rejects_escalation` | **ADAPT**: it now loads the checksummed audit via the baseline loader. | The recorder escalation inventory is unchanged. |
| `scripts/db/initial_controller_upgrade_evidence.py` | **REMOVE**: orphaned 0035→head helper with no importer. | none (it was dormant) |

## Operational consequences

- Existing databases created from the former chain **cannot upgrade across this
  rebaseline**: their `alembic_version` (`0047_…` or earlier) is unknown to the new
   graph. This is a code lineage replacement, not an in-place data migration.
   Existing projects/volumes must be preserved unless their data is explicitly
   declared disposable. Never use `alembic stamp` as a substitute for a verified
   data/schema transition.
- Cluster-global roles are shared. Use an independent cluster for the new install;
  a legacy recorder role fails closed, and a shared cluster must not be reset to
  work around the refusal.
- After this cut, `0001_initial` and `migrations/baseline/` are again immutable
  accepted history. The next schema change is an ordinary `0002+` migration.

### Parallel local installation (preserves the old project)

Run from the backend repository with Docker and Python dependencies available:

```powershell
$env:RE_DEV_IMAGE_TAG = 'rebaseline-0047-parallel'
uv run python scripts/dev/local_stack.py up --project request-engine-rb-0047 `
  --api-port 58200 --control-port 58201 --console-port 58202 --gateway-port 58290
uv run python scripts/dev/local_stack.py status --project request-engine-rb-0047
```

The distinct image tag also avoids replacing the old project's `dev-local` tag.
The new project creates its own PostgreSQL volume, generated credentials and
installation-local identities. The development seed creates owners, one organization
and a worker integration; it does not transfer existing staff or business history.
Keep the original project and `.local-stack` state. A retained old installation
requires its matching old code/image. Moving its data is a separate transfer and
recovery project; deleting volumes is not part of this procedure.

### Follow-up validation

Execution evidence for the integrated, uncommitted worktree is recorded in
`docs/testing/rebaseline-0047-validation-2026-10-23.md`. A local full lane is not
published-commit CI or production certification.
