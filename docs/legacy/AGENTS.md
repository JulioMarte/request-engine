# Historical archive — DO NOT MODIFY

Everything under `docs/legacy/**` is preserved only for historical traceability, migration archaeology, and comparison with the retired architecture.

## Hard rule

Unless the user explicitly asks to modify the historical archive itself, agents and developers MUST NOT:

- edit, rewrite, reformat, rename, move, delete, or modernize files in this folder;
- implement features from these files as if they were current requirements;
- treat Convex, Chatwoot, Evolution, n8n, Vite, `booking.*`, or other V1-specific choices found here as current Request Engine architecture.

If historical material contains an idea worth restoring, first restate and approve that idea in the current authoritative documents outside `docs/legacy/**`.

Current architecture is defined by `docs/00-product-definition.md`, `docs/01-architecture-v2.md`, `docs/02-pre-sql-domain-contract.md`, `docs/07-database-access-contract.md`, and the PostgreSQL migration chain documented in `docs/README.md`.
