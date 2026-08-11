# Request Engine — agent instructions

## Current architecture

Request Engine is being rebuilt around PostgreSQL 18+, Python/FastAPI, SQLAlchemy/Alembic, a modular monolith, transactional outbox, and deterministic application commands.

Before changing architecture, domain behavior, persistence, concurrency, payments, scheduling/capacity or API persistence boundaries, read the current documents in this order:

1. `docs/00-product-definition.md`
2. `docs/01-architecture-v2.md`
3. `docs/02-pre-sql-domain-contract.md`
4. `docs/07-database-access-contract.md`
5. `docs/README.md` for the current PostgreSQL migration order.

Do not infer the current architecture from old source code, package files, Convex artifacts, prior frontend structure, or historical documents.

## Historical archive — no touch

`docs/legacy/**` is an immutable historical archive.

Unless the user explicitly asks to modify the archive itself, DO NOT edit, rewrite, reformat, rename, move, delete, or modernize anything under `docs/legacy/**`.

Do not implement requirements from `docs/legacy/**` directly. If an old idea is worth restoring, first make it an approved part of the current authoritative docs.

## Architectural boundaries

- PostgreSQL is authoritative for relational integrity, transactional state, serialization roots, local invariants, durable facts, idempotency, audit and outbox.
- Python/Application owns commands, authorization, policies, complete lock-set planning, external I/O, workflow orchestration and transaction boundaries.
- Do not create a generic CRUD architecture for authoritative domain transitions.
- Do not turn PostgreSQL into a stored-procedure application backend.
- No network I/O inside authoritative DB transactions.
- Critical relationships use typed tenant-aware references; public IDs never grant authority.
- Preserve canonical lock ordering and transaction proofs defined in `docs/02-pre-sql-domain-contract.md`.
