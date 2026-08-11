@AGENTS.md

# Claude Code adapter

Treat the imported `AGENTS.md` as the repository-wide engineering map. Repository documentation is the source of truth; load the specific canonical doc referenced by `AGENTS.md` for the task instead of treating this file as an independent architecture manual.

When working under `docs/`, `migrations/`, `src/request_engine/modules/`, or `tests/`, also obey that area's local agent/instruction file when discovered. Never infer current requirements from `docs/legacy/**`.
