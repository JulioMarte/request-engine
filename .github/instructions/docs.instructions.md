---
applyTo: "docs/**/*.md,README.md,AGENTS.md,CLAUDE.md,GEMINI.md,.github/**/*.md"
---

# Documentation rules

- Treat repository documentation as the source of truth and instruction files as concise adapters/maps.
- Keep normative documents explicit about status and precedence.
- Use `docs/testing/repository-governance-contract.md` to classify HARD / CONTROLLED / FLEXIBLE / HISTORICAL repository rules before changing architecture/test/instruction assertions.
- Avoid duplicating the same rule in many files; one document owns the semantic rule and local docs/instructions reference it.
- Update `docs/10-module-ownership-map.md` when concept/module/DB ownership changes.
- Update `docs/README.md` when authority/precedence/indexing changes.
- Keep Claude/Gemini/Copilot instruction adapters aligned with root/local `AGENTS.md`; do not let tool-specific files become independent architecture manuals.
- `docs/legacy/**` is immutable and non-authoritative unless an archive edit is explicitly requested.
- V2 documents such as `docs/02-pre-sql-domain-contract.md` are historical/source material, not implicit current authority.
- Examples must not silently contradict tenant, authority, transaction, lock, DTO/type-boundary, or module-ownership invariants.
