# Request Engine

Request Engine is a headless, multi-tenant transactional engine that turns durable intent into deterministic work, capacity commitments, monetary obligations, observable execution, and auditable outcomes.

This repository is the clean Python/PostgreSQL implementation of the V2 architecture. PostgreSQL is authoritative for relational and transactional truth; Python owns commands, authorization, policies, orchestration, external I/O, and transaction boundaries.

## Read first

Authoritative material is read in this order:

1. `docs/00-product-definition.md`
2. `docs/01-architecture-v2.md`
3. `docs/02-pre-sql-domain-contract.md`
4. `docs/07-database-access-contract.md`
5. `docs/09-python-module-architecture.md`
6. `docs/10-module-ownership-map.md`
7. `docs/README.md`

`docs/legacy/**` is historical and non-authoritative.

## Repository architecture

The Python code is organized **module first, layer second**. Business capabilities stay together so a change normally has one obvious home.

```text
request-engine/
├── src/request_engine/
│   ├── bootstrap/                # composition root only
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

Each business module may contain small internal layers such as:

```text
module/
├── domain/
├── application/
│   ├── commands/
│   └── queries/
├── persistence/
├── integrations/
├── api/
├── contracts.py
├── facade.py
└── README.md
```

Do not create empty architectural folders pre-emptively. Add a package when real code needs it.

## Key implementation rules

- One semantic command should have one obvious implementation file.
- Repositories are semantic persistence ports, not generic CRUD stores.
- SQLAlchemy ORM is useful for ordinary persistence; SQLAlchemy Core / explicit SQL is preferred for locks, ranges, `SKIP LOCKED`, aggregate concurrency checks, and `request_cmd.*` primitives.
- Domain objects, persistence mappings, and API DTOs are separate concepts.
- Cross-module transactions are allowed when the domain contract requires one atomic transaction.
- Cross-module imports must use the target module's public contracts/facade, never its persistence internals.
- PostgreSQL constraints and transaction protocols are part of application correctness, not implementation details to mock away.
- No network I/O occurs while authoritative database locks are held.

## SQL and migrations

The current V2.6→V2.10 SQL design chain lives under:

```text
migrations/sql/design_chain/
```

It is executable design history, **not yet production Alembic history**. When the schema is formally frozen, the chain should be consolidated into the first production baseline migration. After that point, migration history is append-only.

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

Read `AGENTS.md` before editing. More-specific `AGENTS.md` files and `.github/instructions/*.instructions.md` add path-specific rules. Module ownership is documented in `docs/10-module-ownership-map.md` and in each module README.

The repository is intentionally optimized so an agent can answer these questions before changing code:

1. Which module owns this behavior?
2. Which command/query owns the use case?
3. Which PostgreSQL tables/views/functions are authoritative?
4. Which serialization roots and lock order apply?
5. Which tests prove the invariant?
