---
applyTo: "docs/**/*.md,README.md,AGENTS.md,CLAUDE.md,GEMINI.md,.github/**/*.md"
---

# Documentation rules

- Treat repository documentation as the source of truth and instruction files as concise adapters/maps.
- `docs/architecture/system-optimization-mode.md` is the current repository-wide cohesion/rebaseline authority while Request Engine remains pre-production; current docs and instruction adapters must not contradict it.
- `docs/testing/current-guarantees.toml` is the current semantic-guarantee inventory. Historical V2/V3/F1-F7 names, branch names, release lanes and migration checkpoints are not present authority by themselves.
- Keep normative documents explicit about status and precedence.
- Use `docs/testing/repository-governance-contract.md` to classify HARD / CONTROLLED / FLEXIBLE / HISTORICAL repository rules before changing architecture/test/instruction assertions.
- Avoid duplicating the same rule in many files; one document owns the semantic rule and local docs/instructions reference it.
- Update `docs/10-module-ownership-map.md` when concept/module/DB ownership changes.
- Update `docs/README.md` when authority/precedence/indexing changes; keep it an index of the present system rather than a chronological feature-status diary.
- Do not hardcode a particular Alembic revision as timeless current head in documentation; executable migration truth belongs to `migrations/` and the current head is discovered from the repository graph.
- Do not describe a feature as active, complete, shipped or pending solely from an F/S label or an old branch name; verify actual repository/product evidence when status matters.
- Keep Claude/Gemini/Copilot instruction adapters aligned with root/local `AGENTS.md`; do not let tool-specific files become independent architecture manuals.
- `docs/legacy/**` is immutable and non-authoritative unless an archive edit is explicitly requested.
- V2 documents such as `docs/02-pre-sql-domain-contract.md` are historical/source material, not implicit current authority.
- Historical release/provenance documents may preserve historical wording; current READMEs/maps/instructions must not present retired frozen-V3 runners, obsolete branch names or old migration checkpoints as current.
- Examples must not silently contradict tenant, authority, transaction, lock, DTO/type-boundary, module-ownership or current guarantee invariants.
