# Test agent rules

Applies to `tests/**` in addition to the repository-wide `AGENTS.md`.

Before adding, deleting, moving, or weakening a durable proof, read `docs/testing/README.md` and `docs/testing/repository-governance-contract.md`.

## Rigidity versus flexibility

Every structural assertion must be treated as one of:

```text
HARD        invariant or semantic boundary; fail closed by default
CONTROLLED  accepted architecture/product shape; deliberate evolution only
FLEXIBLE    private implementation shape; do not freeze gratuitously
HISTORICAL  pinned release provenance; resolve against the historical tree/release
```

Do not interpret "fitness functions may evolve" as permission to relax HARD boundaries such as DTO/domain/persistence separation, cross-module `contracts`, dependency acyclicity, authority, transaction ownership, naming semantics, repository instruction routing, or exact-head integration discipline.

Conversely, do not turn FLEXIBLE details such as exact test filenames, test counts, private helper names, or internal file splits into permanent architecture contracts.

## Test ownership and evidence

- Organize durable feature tests by ownership/scope, not by the historical feature that introduced them. Module-owned tests belong under `tests/modules/<owner>/`; cross-module PostgreSQL contract/invariant tests belong in `tests/db/`; public production-like journeys belong in `tests/e2e/`; dependency/import/repository-governance fitness functions belong in `tests/architecture/`.
- `tests/historical/` is reserved for pinned release provenance/compatibility. Historical evidence must not force current Request Engine head to preserve an obsolete implementation shape.
- Classify what a test proves with pytest markers instead of creating parallel physical trees for `invariant`, `contract`, `adversarial`, or similar evidence classes. Physical location answers who owns the proof; markers answer what evidence it provides.
- Feature-local integration suites may exist while a feature is under active development. Before/at promotion into the current product, disposition them as durable current proof, historical evidence, replacement, or genuine redundancy rather than accumulating feature-era suites forever.

## Correctness-sensitive evidence

- Use real PostgreSQL for locks, constraints, transaction isolation, range behavior, `SKIP LOCKED`, privileges, and concurrency races.
- Do not make a critical concurrency test pass by mocking the database mechanism under test.
- Race/invariant regressions should reproduce the failing interleaving or enforcement condition before the fix. Prefer explicit synchronization/barriers over timing-only `sleep()` races.
- Use pytest markers declared in `pyproject.toml`. Evidence markers complement execution markers; avoid marker noise that does not improve selection or proof meaning.
- Tests should assert semantic outcomes/invariants, not incidental ORM call sequences or broad snapshots when a smaller semantic assertion is sufficient.

## Architecture/repository proofs

Architecture tests should strongly enforce HARD boundaries, detect CONTROLLED drift with actionable messages, and avoid freezing FLEXIBLE shape.

For DTO/type-boundary tests, protect the separation itself:

```text
HTTP Body/View != application/domain/contracts/persistence
Pydantic business transport != domain/application/cross-module contract
provider SDK type != business contract
```

For naming tests, enforce ownership-signaling conventions (`*Body`, `*View`, semantic command/query names, no generic business dumping grounds) rather than exact inventories of every class/file.

For LLM/documentation governance, prove that repository/local instruction adapters route to canonical `AGENTS.md`/docs and cannot silently become independent conflicting architecture manuals.

Removing or weakening a failing safety/architecture test requires an explicit KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition tied to the guarantee that remains protected.
