# Request Engine repository instructions

Use `AGENTS.md` as the repository-wide engineering map and contract. Use the nearest path-specific instruction file when one applies. Repository documentation is the source of truth; this file is an adapter, not an independent architecture manual.

Before changing business code:

- identify ownership in `docs/10-module-ownership-map.md` and read the owning module README;
- read the current capability/transaction contract selected by `docs/README.md` precedence; for released V3 invariants use `docs/v3/02-pre-sql-contract.md`, and for an indexed post-V3 feature read its explicit normative delta first;
- follow `docs/07-database-access-contract.md`, `docs/09-python-module-architecture.md`, `docs/13-connection-surfaces.md`, and `docs/14-architecture-fitness-functions.md` for persistence/module/boundary rules;
- use `docs/testing/repository-governance-contract.md` to distinguish HARD semantic/type/repository boundaries from CONTROLLED architecture shape and FLEXIBLE implementation detail.

Do not infer current requirements from `docs/02-pre-sql-domain-contract.md` or `docs/legacy/**`; those are historical/V2 source material unless a current canonical document explicitly cites them for history.

Do not recreate horizontal global business layers, import another module's internals, mix API/Pydantic DTOs with domain/application/contracts/persistence, introduce generic CRUD repositories/table-shaped APIs, perform network I/O inside authoritative DB transactions, or move workflows into stored procedures.

Prefer mechanical validation over prose-only convention. Run relevant tests/lint/type checks and never report a check as passing unless it actually ran.
