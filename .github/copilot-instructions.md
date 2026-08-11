# Request Engine repository instructions

Use `AGENTS.md` as the repository-wide engineering map and contract. Use the nearest path-specific instruction file when one applies.

Before changing business code, identify ownership in `docs/10-module-ownership-map.md` and read the owning module README. For concurrency/authoritative mutations, read the relevant invariant/lock protocol in `docs/02-pre-sql-domain-contract.md`. For persistence, follow `docs/07-database-access-contract.md` and `docs/09-python-module-architecture.md`.

Do not recreate horizontal global business layers, import another module's internals, introduce generic CRUD repositories/table-shaped APIs, perform network I/O inside authoritative DB transactions, or move workflows into stored procedures.

Prefer mechanical validation over prose-only convention. Run relevant tests/lint/type checks and never report a check as passing unless it actually ran.
