# 0004 — Repository knowledge for coding agents

**Status:** Accepted

## Context

Request Engine is expected to be maintained by humans and multiple coding-agent harnesses. Large duplicated instruction files consume context, drift quickly and create conflicting sources of truth. Modern agent tooling supports repository-wide and path-specific instructions, but each harness uses different filenames/discovery rules.

## Decision

Treat versioned repository documentation as the knowledge system of record.

- Root `AGENTS.md` is a short repository map plus non-negotiable operational guardrails.
- Nested `AGENTS.md` files add only stricter local rules for important boundaries (`docs`, `migrations`, business modules, tests).
- `.github/copilot-instructions.md` and path-specific `.github/instructions/*.instructions.md` are thin GitHub Copilot adapters to the same repository rules.
- `CLAUDE.md` and `GEMINI.md` remain thin harness adapters/import maps rather than independent architecture manuals.
- Durable architectural rationale belongs in canonical docs and ADRs, not duplicated in agent files.
- Mechanical rules are enforced by tests/lint/type checking whenever feasible instead of relying only on prose.

## Consequences

- Agents receive a map rather than the entire architecture on every task.
- Local context can become more specific without bloating repository-wide instructions.
- Changes to architecture should update one canonical source and any small routing references that point to it.
- Agent instructions must contain validation commands and explicitly forbid claiming checks that were not run.

## Rejected alternatives

- One giant repository instruction file containing the whole architecture.
- Separate, independently maintained instruction manuals for Codex, Copilot, Claude and Gemini.
- Relying on prompts alone for dependency/import rules that can be tested mechanically.

## External guidance considered

This decision follows the documented behavior of Codex `AGENTS.md`, GitHub Copilot repository/path-specific instructions and Gemini CLI hierarchical `GEMINI.md` context. The repository does not depend on any single agent vendor for its canonical engineering knowledge.
