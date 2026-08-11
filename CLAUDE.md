@AGENTS.md
@docs/09-python-module-architecture.md
@docs/10-module-ownership-map.md

# Claude-specific note

Treat `AGENTS.md` as the repository-wide operating contract. When entering `docs/`, `migrations/`, `src/request_engine/modules/`, or `tests/`, also obey the nearest nested `AGENTS.md`. Do not infer current requirements from `docs/legacy/**`.
