# Request Engine — clean architecture rebuild

This branch is the clean implementation starting point for the current Request Engine architecture.

**There is intentionally no application code yet.** The retired Convex/Vite implementation, npm configuration, generated files and previous frontend/backend tree were deliberately not carried into this branch.

## Source of truth

Implementation must follow, in order:

1. `docs/00-product-definition.md`
2. `docs/01-architecture-v2.md`
3. `docs/02-pre-sql-domain-contract.md`
4. `docs/07-database-access-contract.md`
5. `docs/README.md` and the PostgreSQL 18+ reference migration chain

`docs/legacy/**` is historical, immutable and non-authoritative. See `AGENTS.md`.

## Intended project shape

```text
src/request_engine/
├── api/                 # FastAPI / HTTP / agent-facing adapters
├── application/         # commands, queries, orchestration, UoW coordination
├── domain/
│   ├── organizations/
│   ├── identity/
│   ├── offerings/
│   ├── requests/
│   ├── pricing/
│   ├── workflows/
│   ├── capacity/
│   ├── reservations/
│   ├── admission/
│   ├── schedules/
│   ├── locations/
│   ├── dispatch/
│   ├── payments/
│   └── fulfillment/
├── infrastructure/
│   ├── persistence/     # PostgreSQL / SQLAlchemy adapters
│   ├── integrations/    # external providers and channels
│   ├── messaging/       # outbox/event delivery adapters
│   └── observability/   # logging/tracing/metrics adapters
├── workers/             # asynchronous workers
└── bootstrap/           # composition root / dependency wiring

migrations/              # future Alembic migration environment
tests/
├── unit/
├── integration/
├── concurrency/
├── architecture/
└── fixtures/

scripts/                 # operational/development scripts
deploy/                  # deployment assets when introduced
```

The folders are placeholders only. Do not add frameworks, generated boilerplate, package configuration or runtime code until the corresponding implementation decision is made against the current contracts.

## Non-negotiable implementation rules

- PostgreSQL is authoritative transactional storage, not a dumb persistence layer and not a stored-procedure application backend.
- Python owns domain/application commands, transaction orchestration, policies, authorization and external I/O.
- The modular monolith dependency direction in `docs/01-architecture-v2.md` must be preserved.
- Critical concurrency protocols and canonical lock ordering come from `docs/02-pre-sql-domain-contract.md`.
- Python ↔ PostgreSQL access must follow `docs/07-database-access-contract.md`.
- No code from the retired implementation should be copied forward merely for convenience; behavior must be re-derived from the current architecture.
