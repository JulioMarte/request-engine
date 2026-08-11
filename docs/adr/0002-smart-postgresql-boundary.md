# 0002 — Smart PostgreSQL boundary

**Status:** Accepted

## Context

Request Engine depends on relational integrity, stable serialization roots, capacity race protection, append-oriented financial/outcome facts, durable idempotency and transactional outbox semantics. Treating PostgreSQL as dumb storage would move correctness into convention-only application code; moving workflows into stored procedures would create a second application backend.

## Decision

Use PostgreSQL as an authoritative transactional consistency engine while Python owns command semantics, authorization/policy orchestration, lock-set planning, external integrations and transaction framing.

PostgreSQL exposes:

- `request_engine.*` authoritative relational structures;
- `request_read.*` versioned read contracts;
- `request_cmd.*` narrow atomic consistency primitives;
- `request_admin.*` operational diagnostics.

## Consequences

- Correctness-sensitive SQL may be explicit SQL/SQLAlchemy Core instead of ORM-only code.
- Python commands retain one explicit transaction boundary.
- External I/O never occurs while authoritative DB locks are held.
- Stored functions must remain narrow and data-centric.

## Rejected alternatives

- ORM CRUD over a dumb database.
- Stored-procedure application backend.
- Writable business views as mutation APIs.

Detailed normative rules live in `docs/07-database-access-contract.md`.
