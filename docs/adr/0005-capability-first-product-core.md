# 0005 — Capability-first product core
Status: Accepted

## Context

Request Engine began with a useful goal: expose one operational API that bots, forms, applications and automation systems could use to interact with a business. During architecture exploration, that goal drifted toward a universal transactional model capable of representing scheduling, payments, fulfillment, dispatch, queues, external commitments and generic workflows before concrete production use cases proved the need for those abstractions.

The resulting V2 design contains strong transaction and PostgreSQL ideas, but too much of the domain breadth is speculative. The first concrete product use cases are simpler and clearer: business information, appointment booking, FIFO service queues, waitlists, transactional reminders/confirmations, generic quote/intake Requests and n8n integration.

## Decision

Request Engine is a **capability-first operational API**, not a universal workflow engine.

A single public API may expose capabilities from multiple bounded contexts, but those contexts do not share one universal domain model.

Every public operation is classified as one of:

- `Query` — read state;
- `Command` — execute an immediate semantic mutation;
- `Request` — create durable new business demand that requires later processing;
- `ScheduledAction` — execute a durable future action.

`Request` is narrowed accordingly. Mutations such as cancel/reschedule are Commands by default, not Request types.

The baseline prioritizes:

- tenancy/authority;
- structured business/catalog information;
- booking and local capacity;
- service queue and waitlist;
- transactional communications;
- durable scheduling;
- generic Request/intake;
- outbox/idempotency/audit;
- n8n as an extension boundary.

Payments, dispatch, advanced fulfillment, capacity pools and external planning are deferred until a concrete production capability requires them.

`Workflow` is not a universal aggregate/DSL. Orchestration uses typed application handlers, explicit state/facts, scheduled actions, outbox/provider callbacks and n8n for volatile external workflows.

## Consequences

Positive:

- lower conceptual and implementation complexity before the first database baseline;
- clearer agent/tool contracts;
- easier delivery of real customer-service bots;
- domain boundaries can evolve from demonstrated business language;
- proven PostgreSQL concurrency patterns are retained without preserving speculative breadth;
- n8n provides an explicit escape hatch for new workflows instead of forcing premature native modeling.

Costs/trade-offs:

- some V2 domain work becomes deferred design knowledge rather than baseline implementation;
- canonical docs and SQL must be reduced before baseline;
- future payment/dispatch/fulfillment capabilities may require new ADRs and migrations;
- one API does not imply one aggregate or one transaction boundary, so capability routing/documentation must remain explicit.

## Rejected alternatives

### Keep expanding the V2 universal model

Rejected because it optimizes for hypothetical future industries instead of verified product behavior and increases the probability of freezing incorrect abstractions into PostgreSQL.

### Rebuild as a generic workflow engine

Rejected because n8n and external workflow systems already cover volatile orchestration, while Request Engine's differentiator is deterministic operational authority and business-safe capabilities.

### Build a separate backend for every bot/client

Rejected because booking, queueing, identity, idempotency, reminders and other operational concerns are reusable across channels and tenants. A common headless engine remains valuable.
