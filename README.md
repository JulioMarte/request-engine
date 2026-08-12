# Request Engine

Request Engine is a **headless, multi-tenant operational capability API** for agents, forms, applications and automation systems. It exposes deterministic business capabilities such as structured business information, appointment booking, queues, waitlists, transactional communications and durable Requests without requiring every business process to fit one universal workflow model.

PostgreSQL owns local relational/transactional truth, locks and consistency backstops. Python owns semantic commands/queries, authorization, policy orchestration, external I/O and transaction framing.

The repository is currently in a **pre-baseline capability-first V3 transition**. The V2 SQL design chain remains useful design history but is not the schema to freeze.

## Read first

Start with `docs/README.md`, which defines canonical precedence.

Most relevant current documents:

- `docs/11-capability-first-v3.md` — current product thesis, capability semantics and V3 baseline;
- `docs/12-v3-transition-plan.md` — V2 reduction/migration plan;
- `docs/v3/sql-disposition.md` — PostgreSQL object disposition before the clean V3 candidate;
- `docs/07-database-access-contract.md` — Python ↔ PostgreSQL boundary;
- `docs/09-python-module-architecture.md` — physical Python layout/import boundaries;
- `docs/10-module-ownership-map.md` — business ownership;
- `docs/adr/README.md` — durable architectural rationale.

`docs/legacy/**` is historical and non-authoritative.

## Product semantics

Public/application behavior is explicit about four different semantics:

```text
Query            read current state
Command          execute a semantic immediate mutation
Request          create durable new business demand requiring later processing
ScheduledAction  execute durable future work
```

Do not use `Request` as a universal wrapper for every operation merely because of the project name.

Examples of capability-oriented surfaces:

```text
business.get_info
catalog.search_offerings
appointments.find_slots
appointments.book
appointments.cancel
appointments.reschedule
appointments.confirm_attendance
queue.join
queue.status
waitlist.join
waitlist.status
quotes.request
requests.status
```

Internal persistence nouns such as CapacityClaim, outbox rows or provider events are not automatically public/agent tools.

## Repository architecture

Python is organized **module first, layer second**.

```text
request-engine/
├── src/request_engine/
│   ├── bootstrap/                # composition root + runtime settings
│   ├── entrypoints/              # HTTP, worker and CLI process adapters
│   ├── platform/                 # technical cross-cutting capabilities
│   │   ├── db/
│   │   ├── idempotency/
│   │   ├── outbox/
│   │   ├── audit/
│   │   ├── events/
│   │   ├── scheduling/
│   │   ├── observability/
│   │   └── security/
│   └── modules/
│       ├── tenancy/              # V3 baseline
│       ├── catalog/              # V3 baseline
│       ├── requests/             # V3 baseline
│       ├── booking/              # V3 baseline
│       ├── queue/                # V3 baseline
│       ├── communications/       # V3 baseline
│       ├── delivery/             # deferred/incubating
│       ├── payments/             # deferred/incubating
│       └── dispatch/             # deferred/incubating
├── migrations/
├── tests/
├── docs/
├── scripts/
└── deploy/
```

Baseline modules may not depend on deferred modules unless a concrete product requirement reactivates that boundary through an accepted architecture change.

A module grows only the structure real code requires:

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

Do not create empty architectural folders pre-emptively.

## Current V3 baseline capabilities

### Structured business information

Operational profile/location/hours/Offering truth that agents and applications can query. Request Engine does not become a universal CMS/RAG system.

### Booking

Local `Resource` availability, Holds/claims and Reservations with `exclusive`/`units` capacity models. Booking owns race-safe book/cancel/reschedule semantics.

Reservation confirmation is distinct from customer/patient attendance confirmation.

### Service queue

FIFO service flow for people/items waiting to be served now.

### Waitlist

Future capacity interest, distinct from the live service queue. Released capacity may produce expiring `SlotOffer` opportunities that still revalidate through booking.

### Transactional communications

Request Engine owns durable communication intent/result; WhatsApp, SMS, email, voice and n8n are replaceable adapters/providers.

### Durable scheduling

`platform/scheduling` owns generic lease/fencing/retry/dead-letter mechanics for future actions. Business modules own why those actions exist.

### Generic Requests and n8n extension

New or volatile processes can begin as durable Request/intake + outbox → n8n → authenticated idempotent semantic callback. Stable high-value processes can later be promoted into native modules without changing the external capability contract.

Principle:

> **Experiment outside; harden inside.**

## Key implementation rules

- One semantic command/query has one obvious owner.
- Application code defines semantic ports; DB/provider implementations are adapters.
- Repositories are semantic persistence adapters, not generic CRUD stores.
- SQLAlchemy ORM is appropriate for ordinary persistence; Core/explicit SQL is preferred for locks, ranges, `SKIP LOCKED`, aggregate concurrency checks and narrow `request_cmd.*` primitives.
- Domain objects, persistence mappings, API DTOs and cross-module contracts are separate concepts.
- Cross-module transactions are allowed when a real local invariant requires one atomic transaction.
- Cross-module imports use the target module's `contracts` surface.
- `platform` may not depend on business modules.
- `bootstrap` wires dependencies; business code must not use it as a service locator.
- PostgreSQL constraints and concurrency protocols are part of correctness, not implementation details to mock away.
- No external network I/O occurs while authoritative database locks are held.
- n8n/providers never mutate Request Engine storage directly; callbacks execute authenticated idempotent semantic commands.

## SQL and migrations

The V2.6→V2.10 design chain remains under:

```text
migrations/sql/design_chain/
```

It is executable pre-production design history, **not production Alembic history and not the V3 baseline candidate**.

Do not continue adding V2.x hardening deltas by default. V3 will construct a clean reduced candidate after object disposition and capability contracts are proven. Because no production baseline exists yet, obsolete speculative object shapes do not require compatibility migrations.

See `migrations/README.md` before changing SQL.

## Development tooling

The project uses `uv` and `pyproject.toml` as the Python project control plane.

```bash
uv sync --all-groups
docker compose up -d postgres
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## LLM / coding agents

Repository documentation is the engineering system of record. `AGENTS.md` is a compact map/guardrail file, with nearer instruction files adding local rules.

Before changing code, a human or agent should be able to answer:

1. Which capability/module owns this behavior?
2. Is it a Query, Command, Request, or ScheduledAction?
3. Which public contract may another module depend on?
4. Which PostgreSQL row(s) serialize the authoritative mutation?
5. Which locks/races/failure modes must be proven?
6. Which provider work occurs only after commit?
7. Which tests demonstrate the invariant rather than merely the happy path?

The V3 north star is intentionally simple:

```text
one public operational API
        ≠
one universal domain model
```
