# Request Engine repository instructions

Follow `AGENTS.md` as the repository-wide engineering contract.

Before editing business code, identify the owning module using `docs/10-module-ownership-map.md`, then read that module's README. The repository is a module-first modular monolith; do not recreate horizontal global domain/application/infrastructure layers.

For authoritative commands, preserve the transaction and lock protocols from `docs/02-pre-sql-domain-contract.md` and the Python/PostgreSQL ownership boundary from `docs/07-database-access-contract.md`.

Do not introduce generic CRUD repositories, table-shaped APIs, shared SQLAlchemy models as cross-module contracts, network I/O inside authoritative DB transactions, or workflow-sized stored procedures.

When changing critical behavior, add or update tests proving the relevant invariant and run the narrowest relevant validation. Never state that tests passed unless they were actually executed.
