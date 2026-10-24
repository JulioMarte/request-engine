# Request Engine

Request Engine is a **headless, multi-tenant operational capability API** for agents, forms, applications and automation systems. It exposes deterministic business capabilities for identity/authority, operational configuration, discovery, booking/capacity, queues/waitlists, live service execution, communications, operational projection/recovery and bounded external operational tooling without forcing every process into one universal workflow model.

PostgreSQL owns relational/transactional truth, constraints, tenant/security backstops, locks and durable facts. Python owns semantic commands/queries, authorization/policy orchestration, provider/external I/O and transaction framing.

## Current repository mode

Request Engine is still pre-production and is currently in a dedicated cohesion/system-optimization phase.

Read first:

- `docs/architecture/system-optimization-mode.md` — current optimization/rebaseline authority;
- `docs/testing/current-guarantees.toml` — semantic guarantees that must not disappear silently;
- `docs/README.md` — current documentation index and precedence;
- `docs/10-module-ownership-map.md` — current business ownership;
- `migrations/README.md` — current schema-evolution/rebaseline rules.

The released V3 baseline and earlier V2 design chain remain historical provenance. They are **not permanent ceilings on current schema/module/test/repository shape**. During this pre-production phase a deliberate architecture/schema rebaseline may be performed after the required audit and proof. Do not casually rewrite migration history during unrelated work.

The current rule is:

```text
freeze guarantees, not accidental repository shape
```

## Product semantics

Public/application behavior distinguishes four different semantics:

```text
Query            read/derive current state
Command          execute a semantic immediate mutation
Request          create durable new business demand requiring later processing
ScheduledAction  execute durable future work
```

Do not use `Request` as a universal wrapper for every mutation merely because of the project name.

Public capabilities are semantic rather than table-shaped. Internal persistence nouns such as claims, outbox rows, provider events or lock roots are not automatically public tools/resources.

## Repository architecture

Python is organized **module first, layer second**.

```text
src/request_engine/
├── bootstrap/       # composition/settings
├── entrypoints/     # HTTP/worker/CLI process + trust boundaries
├── platform/        # technical cross-cutting mechanics
└── modules/
    ├── tenancy/
    ├── platform_configuration/
    ├── catalog/
    ├── requests/
    ├── booking/
    ├── queue/
    ├── communications/
    ├── discovery/
    ├── delivery/
    ├── live_capacity/
    ├── operational_recovery/
    ├── operational_copilot/
    └── onboarding/
```

`operational_copilot` is a historical module name for the bounded typed operational-tool/admission boundary; it is not an embedded conversational/LLM runtime. `payments` and `dispatch` are future product areas, not current Python modules; they need a concrete accepted capability before establishing ownership.

See `docs/09-python-module-architecture.md`, `docs/10-module-ownership-map.md`, `docs/13-connection-surfaces.md` and `docs/14-architecture-fitness-functions.md` for normative architecture.

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

This is a growth shape, not required ceremony. File size/file count are not architecture targets.

## Current ownership model

The detailed source is `docs/10-module-ownership-map.md`. At a high level:

- `tenancy` — Organization/Principal/Party/Representation and tenant/subject authority;
- `catalog` — Location/Offering/OfferingVersion and service/configuration vocabulary;
- `requests` — durable new business demand;
- `booking` — Resource planning/contextual supply, availability, holds/claims and Reservations;
- `queue` — live waiting/calling/no-show and waitlist/released-slot interest;
- `communications` — transactional communication intent/delivery/reminder semantics;
- `discovery` — explicitly published cross-tenant supply projection and Booking handoff;
- `delivery` — ReservationAccess and actual service/execution facts;
- `live_capacity` — advisory ETA/capacity/intake projection over owner facts;
- `operational_recovery` — recovery proposal/execution composition over owner capabilities;
- `operational_copilot` — typed external operational tools/admission over published owner contracts.

Important durable distinction:

```text
Reservation    = planned commitment/capacity history
QueueEntry     = arrival/wait/call truth
ServiceSession = actual execution truth
```

Projection/recovery/tooling modules compose these owner facts; they do not gain shadow mutation authority over them.

## Key implementation rules

- One semantic command/query has one obvious owner.
- Cross-module imports use the target module's published `contracts` surface and an approved dependency direction.
- Application code defines semantic ports; DB/provider implementations remain adapters.
- Domain/application/contracts do not depend on HTTP/Pydantic/persistence implementation details.
- Repositories/adapters are semantic persistence surfaces, not generic CRUD stores.
- SQLAlchemy ORM is appropriate for ordinary persistence; explicit PostgreSQL/SQLAlchemy Core is appropriate where locking/range/batch semantics are part of correctness.
- Cross-module transactions are allowed when a real invariant requires one atomic transaction.
- `platform` contains technical cross-cutting mechanics, not displaced business policy.
- `bootstrap` composes dependencies; business code must not use it as a service locator.
- PostgreSQL constraints, RLS/privileges and concurrency protocols are correctness mechanisms, not implementation details to mock away.
- No external network I/O occurs while authoritative database locks are held.
- Providers/n8n do not mutate Request Engine storage directly; callbacks execute authenticated/idempotent semantic operations.

## SQL and migrations

Executable schema evolution lives in:

```text
migrations/versions/       current Alembic line
```

Current baseline and retained historical evidence:

```text
migrations/baseline/           checksummed current 0001 payload
migrations/sql/design_chain/   retained V2 design-history proof
```

The retired V3 candidate/feature-step payloads and collapsed revision chains remain
in Git history, not as a second executable schema authority. The 2026-10-23
pre-production rebaseline and parallel-install procedure are documented in
`docs/audits/postgresql-rebaseline-0047.md`. Existing development data is not
migrated or discarded by replacing the code.

Current CI requires exactly one repository Alembic head and upgrades a clean PostgreSQL 18 database to that head. Do not hardcode one old revision in documentation as timeless current truth.

Before changing schema, read `docs/architecture/system-optimization-mode.md`, `migrations/README.md` and `migrations/AGENTS.md`. A future rebaseline, if justified by the complete PostgreSQL audit, is a dedicated controlled operation — not a blind squash or pg_dump of the current chain.

## Testing and engineering quality

Current semantic guarantees live in `docs/testing/current-guarantees.toml`. Test filenames/directories such as `v3_*`, `f1_*` or `f2_*` may record origin; they do not freeze current architecture.

Architecture HARD failures remain blocking. Maintainability metrics such as file LOC, C901 and module fan-in/fan-out are non-blocking `REVIEW_CANDIDATE` signals requiring semantic review; there is no hard 120-line architecture ceiling.

Read:

- `docs/testing/README.md`
- `docs/testing/repository-governance-contract.md`
- `docs/testing/evidence-authoring-guide.md`
- `docs/engineering-quality/README.md`

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

### Run the whole system locally (development only)

One command builds the CI image (`deploy/reference/Dockerfile`), starts a fresh PostgreSQL 18, runs `alembic upgrade head`, creates least-privilege runtime logins, and starts the runtime API, control plane, admin console, a dev-only gateway and the worker (`compose.dev.yaml`):

```bash
./scripts/dev/local_stack.sh up          # Windows: .\scripts\dev\local_stack.ps1 up
./scripts/dev/local_stack.sh status      # health of every service
./scripts/dev/local_stack.sh down        # add --volumes to delete data and generated secrets
```

- Console: `http://localhost:58102` (use `localhost`, not `127.0.0.1`, for passkeys). API `:58100`, control plane `:58101`, dev gateway inspection `:58190/status`. Ports bind to `127.0.0.1`; override with `--api-port`, `--control-port`, `--console-port`, `--gateway-port`, and use `--project` for a second stack.
- `up` claims the instance over the public setup API with a throwaway software passkey, then creates a dev Organization, its owner and an activated integration principal for the worker. Generated logins/passwords and recovery codes are in `.local-stack/<project>/credentials.json` (gitignored).
- `up --manual-claim` leaves the instance unclaimed so you run the console setup wizard yourself; the worker then waits until you run `local_stack.sh worker --principal-id <activated integration principal>`.
- Every secret is generated per stack into `.local-stack/<project>/dev.env` and is dev-only. The tool refuses non-local Docker endpoints. The dev gateway accepts outbox publishes (HTTP) and webhook handoffs (HTTPS with a generated dev CA) and delivers nothing; production still fails closed without a configured publisher and webhook.

For repository-managed local publication and exact-head CI expectations, read `AGENTS.md`, `CONTRIBUTING.md` and `docs/engineering-quality/local-publish-certification.md`.

## LLM / coding agents

Repository documentation is the engineering system of record. `AGENTS.md` is the repository-wide operational map, with nearer instruction files adding path-specific rules.

Before changing code, a human or agent should be able to answer:

1. Which capability/module owns this behavior?
2. Is it a Query, Command, Request or ScheduledAction?
3. Which supported contract crosses each module/transport/provider boundary?
4. What authority/tenant context is required?
5. Which PostgreSQL facts/locks serialize the authoritative mutation?
6. What are retry/concurrency/ambiguous-failure semantics?
7. Which current guarantee(s) does the change affect?
8. Which tests can falsify a regression in those guarantees?
9. Is a schema change an ordinary controlled migration or part of the dedicated audited rebaseline?

North star:

```text
one public operational API
        ≠
one universal bounded context
        ≠
one frozen historical repository shape
```
