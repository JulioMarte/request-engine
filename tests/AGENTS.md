# Test agent rules

- Organize durable feature tests by ownership/scope, not by the historical feature that introduced them. Module-owned tests belong under `tests/modules/<owner>/`; cross-module PostgreSQL contract/invariant tests belong in `tests/db/`; public production-like journeys belong in `tests/e2e/`; dependency/import fitness functions belong in `tests/architecture/`.
- `tests/historical/` is reserved for pinned release provenance/compatibility. Historical evidence must not force current Request Engine head to preserve an obsolete implementation shape.
- Classify what a test proves with pytest markers instead of creating parallel physical trees for `invariant`, `contract`, `adversarial`, or similar evidence classes. Physical location answers who owns the proof; markers answer what evidence it provides.
- Feature-local integration suites may exist while a feature is under active development. Before/at promotion into the current product, disposition them as durable current proof, historical evidence, replacement, or genuine redundancy rather than accumulating feature-era suites forever.
- Use real PostgreSQL for locks, constraints, transaction isolation, range behavior, `SKIP LOCKED`, privileges, and concurrency races.
- Do not make a critical concurrency test pass by mocking the database mechanism under test.
- Race/invariant regressions should reproduce the failing interleaving or enforcement condition before the fix. Prefer explicit synchronization/barriers over timing-only `sleep()` races.
- Use pytest markers declared in `pyproject.toml`. Evidence markers complement execution markers; avoid marker noise that does not improve selection or proof meaning.
- Tests should assert semantic outcomes/invariants, not incidental ORM call sequences or broad snapshots when a smaller semantic assertion is sufficient.
- Removing or weakening a failing safety test requires an explicit KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition tied to the guarantee that remains protected.
