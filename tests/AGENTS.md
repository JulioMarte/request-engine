# Test agent rules

- Organize feature tests under `tests/modules/<owner>/`.
- Put cross-module database contract tests in `tests/db/` and dependency/import tests in `tests/architecture/`.
- Use real PostgreSQL for locks, constraints, transaction isolation, range behavior, `SKIP LOCKED`, privileges, and concurrency races.
- Do not make a critical concurrency test pass by mocking the database mechanism under test.
- Race/invariant regressions should reproduce the failing interleaving or enforcement condition before the fix.
- Use pytest markers declared in `pyproject.toml`.
- Tests should assert semantic outcomes/invariants, not incidental ORM call sequences.
