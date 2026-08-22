# Documentation agent rules

Applies to `docs/**`; `docs/legacy/AGENTS.md` is stricter for the historical archive.

- Current V3 product/capability semantics belong in `11-capability-first-v3.md` unless an indexed post-V3 delta explicitly supersedes them.
- V3 transition/disposition work belongs in `12-v3-transition-plan.md`.
- `00-product-definition.md`, `01-architecture-v2.md` and `02-pre-sql-domain-contract.md` remain V2 source material according to the precedence in `docs/README.md`; do not silently copy deferred V2 concepts into V3/current design.
- Python/PostgreSQL boundary belongs in `07-database-access-contract.md` unless a newer accepted contract explicitly supersedes a concept.
- Python physical/module architecture belongs in `09-python-module-architecture.md`.
- Module ownership belongs in `10-module-ownership-map.md`.
- Connection surfaces belong in `13-connection-surfaces.md`.
- Executable architecture dependency rules belong in `14-architecture-fitness-functions.md`.
- Pre-production architecture/test evolution belongs in `architecture/pre-production-evolution-policy.md`.
- Repository/test/DTO/naming/LLM rigidity-versus-flexibility rules belong in `testing/repository-governance-contract.md`.
- Current guarantee inventory and representative proof mapping belong under `testing/`.
- Hard-to-reverse rationale belongs in `adr/`.
- Avoid copying the same normative rule into multiple documents; reference the owner document.
- When a HARD or CONTROLLED rule changes, update its canonical owner first, then update indexes/agent maps/tests in the same coherent change.
- When a rule changes, search for stale contradictory current examples elsewhere.
- Historical documents may preserve historical wording; current READMEs/maps/instructions must not treat historical material as current authority.
- Executable SQL belongs under `migrations/`, not `docs/`.
- Never modify `legacy/**` unless explicitly requested.
