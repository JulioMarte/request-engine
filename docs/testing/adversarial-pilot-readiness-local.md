# Local adversarial pilot-readiness checks

This branch contains two GitHub matrix workflows. The local runner mirrors
their node IDs and executes each case in a separate pytest process:

```powershell
uv sync --all-groups
uv run python scripts/ci/run_adversarial_pilot_readiness.py --readiness-only
```

The readiness probes do not require PostgreSQL. They are product-surface
checks, so a failure means the current application contract is missing the
capability described by the test; it is not a database setup failure.

PostgreSQL challenges require a clean PostgreSQL 18 database and a user that
can run the current migrations and create the temporary runtime roles used by
the E2E fixtures. Configure the same variables used by the CI workflow before
running:

```powershell
$env:PGHOST = "127.0.0.1"
$env:PGPORT = "5432"
$env:PGDATABASE = "request_engine_current"
$env:PGUSER = "postgres"
$env:PGPASSWORD = "postgres"
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/request_engine_current"
uv run python scripts/ci/run_adversarial_pilot_readiness.py --postgres-only
```

The migration command upgrades the selected database to the branch head. Use
an isolated disposable database; do not point this at a database containing
data you need. PostgreSQL challenge tests truncate the application schemas
before and after each case, but the migration itself is intentionally not
rolled back.

Run the complete local matrix with:

```powershell
uv run python scripts/ci/run_adversarial_pilot_readiness.py
```

A non-zero exit code is meaningful. The runner reports every failing case and
does not convert known product failures into skips or successes. Local results
are diagnostic evidence; GitHub exact-head CI remains the merge authority.
