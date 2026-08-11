# Request Engine

Request Engine is a headless, multi-tenant transactional engine that turns durable intent into deterministic work, capacity commitments, monetary obligations, observable execution, and auditable outcomes.

This repository is the clean Python/PostgreSQL implementation of the V2 architecture. PostgreSQL is authoritative for relational and transactional truth; Python owns commands, authorization, policies, orchestration, external I/O, and transaction boundaries.

## Read first

Start with `docs/README.md`, which maps the canonical documents and their precedence. The most implementation-relevant documents are:

- `docs/02-pre-sql-domain-contract.md` — invariants, serialization roots and transaction proofs;
- `docs/07-database-access-contract.md` — Python ↔ PostgreSQL boundary;
- `docs/09-python-module-architecture.md` — physical Python layout/import boundaries;
- `docs/10-module-ownership-map.md` — business ownership;
- `docs/adr/README.md` — durable architectural rationale.

`docs/legacy/**` is historical and non-authoritative.

## Repository architecture

The Python code is organized **module first, layer second**. Business capabilities stay together so a change normally has one obvious home.

```text
request-engine/
├── src/request_engine/
│   ├── bootstrap/                # composition root + runtime settings
│   ├── entrypoints/              # HTTP, worker and CLI process adapters
│   ├── platform/                 # truly cross-cutting technical capabilities
│   │   ├── db/
│   │   ├── idempotency/
│   │   ├── outbox/
│   │   ├── audit/
│   │   ├── events/
│   │   ├── observability/
│   │   └── security/
│   └── modules/
│       ├── tenancy/
│       ├── catalog/
│       ├── requests/
│       ├── booking/
│       ├── delivery/
│       ├── payments/
│       └── dispatch/
├── migrations/
├── tests/
├── docs/
├── scripts/
└── deploy/
```

A business module grows only the structure real code requires. The preferred vocabulary is:

```text
module/
├── domain/
├── application/
│   ├── commands/
│   ├── queries/
│   └── ports/
├── adapters/
│   ├── db/
│   └── providers/
├── api/
├── contracts/
└── README.md
```

Do not create empty architectural folders pre-emptively. A small module may remain a handful of cohesive files.

## Key implementation rules

- One semantic command should have one obvious implementation/use-case entry point.
- Application code defines semantic ports; DB/provider implementations are adapters.
- Repositories are semantic persistence adapters, not generic CRUD stores.
- SQLAlchemy ORM is useful for ordinary persistence; SQLAlchemy Core / explicit SQL is preferred for locks, ranges, `SKIP LOCKED`, aggregate concurrency checks, and `request_cmd.*` primitives.
- Domain objects, persistence mappings, API DTOs and cross-module contracts are separate concepts.
- Cross-module transactions are allowed when the domain contract requires one atomic transaction.
- Cross-module imports must use the target module's `contracts` surface, never its domain/application/adapter/API internals.
- `platform` may not depend on business modules.
- `bootstrap` wires dependencies; business code must not use it as a service locator.
- PostgreSQL constraints and transaction protocols are part of application correctness, not implementation details to mock away.
- No network I/O occurs while authoritative database locks are held.

## SQL and migrations

The current V2.6→V2.10 SQL design chain lives under:

```text
migrations/sql/design_chain/
```

It is executable pre-production design history, **not production Alembic history**. When the schema freeze gate is satisfied, the chain is consolidated into a reviewed first production baseline. After that point, migration history is append-only.

See `migrations/README.md` before changing SQL.

## Development tooling

The project uses `uv` and `pyproject.toml` as the Python project control plane.

Typical workflow after runtime implementation begins:

```bash
uv sync --all-groups
docker compose up -d postgres
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## LLM / coding agents

Repository documentation is the engineering system of record. `AGENTS.md` is intentionally a compact map/guardrail file, with nearer `AGENTS.md` files adding local rules. GitHub Copilot, Claude and Gemini instruction files are thin adapters to the same knowledge rather than separate architecture manuals.

The repository is optimized so a human or agent can answer these questions before changing code:

1. Which module owns this behavior?
2. Which command/query owns the use case?
3. Which public contract may another module depend on?
4. Which PostgreSQL tables/views/functions are authoritative?
5. Which serialization roots and lock order apply?
6. Which tests prove the invariant and architectural boundary?
