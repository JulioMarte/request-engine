---
applyTo: "docs/**/*.md,README.md,AGENTS.md,CLAUDE.md"
---

# Documentation rules

- Keep normative documents explicit about status and precedence.
- Avoid duplicating the same rule in many files; one document owns the semantic rule and local docs reference it.
- Update `docs/10-module-ownership-map.md` when concept/module/DB ownership changes.
- `docs/legacy/**` is immutable and non-authoritative unless an archive edit is explicitly requested.
- Examples must not silently contradict tenant, authority, transaction, or lock invariants.
