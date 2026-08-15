# V3 PostgreSQL release-test isolation

Status: normative Phase 6 test-harness contract.

## Scope

The V3 release suites intentionally use destructive database isolation. This contract applies only to disposable PostgreSQL 18 CI and local-CI databases created for release proof. It is not an application runtime pattern and must never target a shared, staging or production database.

## Isolation layers

Repeated concurrency, reverse-order and mutation proofs each use `fresh_v3_database()` to:

1. create a uniquely named scratch database;
2. apply the complete V3 candidate;
3. bind the child proof process through `PGDATABASE`;
4. force-drop the database on every exit path; and
5. query `pg_database` to verify that cleanup actually removed it.

Database creation, cleanup and verification have bounded command timeouts. Candidate bootstrap has its own bounded timeout. A failed or unverifiable cleanup is a proof failure; when the proof body also fails, the cleanup failure is attached to the original exception instead of hiding it.

Because a client can lose its connection after PostgreSQL accepted `CREATE DATABASE`,
even a failed `createdb` result triggers safe `--if-exists` cleanup and an absence
check for the generated database name.

The repeated-bootstrap and candidate-versus-initial Bash proofs apply the same
boundary in their exit traps: force-drop every owned proof database, verify absence,
preserve an existing proof failure and turn cleanup failure into a nonzero result
when the proof body otherwise succeeded.

Within one candidate database, the root autouse pytest fixture resets data before every test marked `postgres`. It discovers non-partition-child base and partitioned tables across the four application schemas (`request_engine`, `request_read`, `request_cmd`, `request_admin`) and executes one `TRUNCATE ... RESTART IDENTITY CASCADE` statement.

This means the reverse-order proof establishes order independence under the declared release-test isolation contract. It does not claim that every test independently deletes the rows it creates.

## Privilege and timeout boundary

Isolation runs through the bootstrap/test principal supplied by `PGUSER`; runtime application, worker and admin roles are not granted `TRUNCATE`. Runtime-role behavior remains exercised inside individual tests after their setup boundary.

The per-test isolation connection uses:

- `connect_timeout = 5s`;
- `lock_timeout = 5s`;
- `statement_timeout = 30s`; and
- a dedicated `application_name` for diagnostics.

`TRUNCATE` requires an `ACCESS EXCLUSIVE` lock. The lock timeout therefore turns a leaked transaction into a fast, attributable test failure instead of allowing the entire CI job to hang.

## Evidence semantics

`.phase6/v3-evidence-manifest.json` distinguishes candidate evidence validity from overall release readiness:

- `evidence_status=VALID` means every required candidate-CI artifact exists, parses and satisfies its artifact-specific success contract;
- `evidence_status=INCOMPLETE` means one or more required artifacts are absent;
- `evidence_status=INVALID` means all files exist but at least one has failing or malformed evidence;
- `release_status=READY` is possible only when candidate evidence is `VALID` and all G01-G20 registry rows are `PASS`.

Semantic validation includes JSON status and counts, blocking catalog findings, required query-plan index selection, catalog-equivalence marker and fingerprint, JUnit test/failure/error/skip totals, completed concurrency rounds, reverse-order execution and mutation-kill results. File presence and hashes alone are insufficient.

The manifest records `head_sha`, `base_sha`, the actually tested merge/checkout SHA, tree SHA and dirty-tree state separately so a pull-request merge candidate cannot be confused with its feature head.

## Required GitHub check

The ruleset-required `PostgreSQL 18 V3 candidate and verticals` job always starts after its dependencies resolve. Before installing test dependencies, it reads the complete `needs` result map and fails unless every prerequisite result is exactly `success`. A failed, cancelled or skipped prerequisite can therefore never turn the required gate into a non-blocking skipped job.
