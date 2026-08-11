# Documentation agent rules

Applies to `docs/**`; `docs/legacy/AGENTS.md` is stricter for the historical archive.

- Product/domain semantics belong in `00-product-definition.md`.
- Transaction/concurrency architecture belongs in `01-architecture-v2.md` and `02-pre-sql-domain-contract.md`.
- Python/PostgreSQL boundary belongs in `07-database-access-contract.md`.
- Python physical/module architecture belongs in `09-python-module-architecture.md`.
- Module ownership belongs in `10-module-ownership-map.md`.
- Avoid copying the same normative rule into multiple documents; reference the owner document.
- When a rule changes, search for stale contradictory examples elsewhere.
- Executable SQL belongs under `migrations/`, not `docs/`.
- Never modify `legacy/**` unless explicitly requested.
