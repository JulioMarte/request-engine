# 0001 — Modular monolith

**Status:** Accepted

## Context

Request Engine has strongly related transactional capabilities (requests, booking/capacity, delivery, payments, dispatch) that sometimes must coordinate inside one authoritative PostgreSQL transaction. Splitting them into services would add distributed consistency, deployment and observability cost before independent scaling/ownership needs are demonstrated.

## Decision

Keep Request Engine as one deployable modular monolith. Business boundaries are enforced in code and tests, not by network calls. Cross-module atomicity is allowed when required by the domain contract.

## Consequences

- One PostgreSQL database/transaction may span multiple business modules.
- Module boundaries must remain explicit to avoid a distributed-monolith-shaped codebase inside one process.
- A future service extraction requires measured operational/organizational need and an explicit consistency design.

## Rejected alternatives

- Microservice per domain noun/table.
- Global horizontal monolith with no business-module ownership.
