# Documentation agent rules

Applies to `docs/**`; `docs/legacy/AGENTS.md` is stricter for the historical archive.

## Current authority

- `architecture/system-optimization-mode.md` is the current repository-wide cohesion/rebaseline policy while Request Engine remains pre-production. Current indexes, READMEs and agent instructions must not contradict it.
- `testing/current-guarantees.toml` inventories current semantic guarantees. Historical V2/V3/F1-F7 names, branches, migration checkpoints and release lanes are not current authority merely because older documents mention them.
- `docs/README.md` is the current documentation index and precedence map. Keep it about the present system; do not turn it into a chronological feature diary.

## Document ownership

- Current capability semantics belong to the owning indexed capability/domain contract; the historical `v3/` path/name does not itself freeze V3 repository shape.
- `11-capability-first-v3.md` and `v3/01-capability-contracts.md` remain important baseline design sources where their guarantees are still current, but newer accepted contracts and the optimization-mode policy may supersede structural assumptions explicitly.
- `00-product-definition.md`, `01-architecture-v2.md` and `02-pre-sql-domain-contract.md` remain V2 source material; do not silently copy retired V2 concepts into current design.
- Python/PostgreSQL ownership belongs in `07-database-access-contract.md` unless a newer accepted contract explicitly supersedes a concept.
- Python physical/module architecture belongs in `09-python-module-architecture.md`.
- Module ownership belongs in `10-module-ownership-map.md`.
- Connection surfaces belong in `13-connection-surfaces.md`.
- Executable architecture dependency rules belong in `14-architecture-fitness-functions.md`.
- API usability/design rules belong in `15-api-design-and-usability-standards.md`.
- Pre-production contract/test evolution belongs in `architecture/pre-production-evolution-policy.md`; system-optimization/rebaseline authority for the current phase belongs in `architecture/system-optimization-mode.md`.
- Repository/test/DTO/naming/LLM rigidity-versus-flexibility rules belong in `testing/repository-governance-contract.md`.
- Current guarantee inventory and representative proof mapping belong under `testing/`.
- Schema-evolution/current executable migration truth belongs under `migrations/`, especially `migrations/README.md`; do not copy a fixed Alembic head into docs as timeless current truth.
- Hard-to-reverse rationale belongs in `adr/`.
- Release provenance belongs under `release/` or Git history/releases/tags and is HISTORICAL unless explicitly reactivated by a current compatibility obligation.

## Integrity rules

- Avoid copying the same normative rule into multiple documents; reference the owner document.
- When a HARD or CONTROLLED rule changes, update its canonical owner first, then indexes/agent maps/tests in the same coherent change.
- When a rule changes, search for stale contradictory **current** examples elsewhere.
- Historical documents may preserve historical wording. Current READMEs/maps/instructions must not present historical branches, release candidates, frozen compatibility runners, migration checkpoints or feature status as current unless verified.
- A filename/path such as `v3/*`, `f1_*` or `f7_*` is provenance/naming, not proof of present authority or implementation status.
- Do not describe a feature as active, complete, shipped or pending merely from a roadmap label. Use verified repository/product evidence when status matters.
- Executable SQL belongs under `migrations/`, not `docs/`.
- Never modify `legacy/**` unless explicitly requested.
