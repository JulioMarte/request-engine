# Documentation agent rules

Applies to `docs/**`; `docs/legacy/AGENTS.md` is stricter for the historical archive.

- Current V3 product/capability semantics belong in `11-capability-first-v3.md`.
- V3 transition/disposition work belongs in `12-v3-transition-plan.md`.
- `00-product-definition.md`, `01-architecture-v2.md` and `02-pre-sql-domain-contract.md` remain V2 source material according to the precedence in `docs/README.md`; do not silently copy deferred V2 concepts into V3.
- Python/PostgreSQL boundary belongs in `07-database-access-contract.md` unless V3 explicitly supersedes a concept.
- Python physical/module architecture belongs in `09-python-module-architecture.md`.
- Module ownership belongs in `10-module-ownership-map.md`.
- Hard-to-reverse rationale belongs in `adr/`.
- Avoid copying the same normative rule into multiple documents; reference the owner document.
- When a rule changes, search for stale contradictory examples elsewhere.
- Executable SQL belongs under `migrations/`, not `docs/`.
- Never modify `legacy/**` unless explicitly requested.
