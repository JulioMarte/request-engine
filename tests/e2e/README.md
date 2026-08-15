# End-to-end evidence suite

This directory is the production-like evidence layer for Request Engine. It is intentionally different from module and integration tests: scenarios enter through public HTTP surfaces where those surfaces exist, execute against real PostgreSQL, use runtime credentials that inherit from the production `request_engine_app` role, and assert durable database outcomes.

## Rules

- Do not replace PostgreSQL locking, RLS, constraints, idempotency, or transaction behavior with mocks.
- Seed data only with the administrative fixture. Application traffic must use the ephemeral `request_engine_app` login.
- Every actor has an explicit tenant, principal, capability set, and where applicable party representation.
- Concurrency scenarios must run simultaneously, not as serialized approximations.
- A replay is successful only when the semantic response and durable side effects remain identical.
- Cross-tenant probes must prove both non-disclosure and non-mutation.
- Capabilities that are not reachable from the composed runtime are documented as gaps rather than mocked into a false green E2E.

## Current executable matrix

| Surface / invariant | Multi-user | Multi-tenant | Replay | Concurrency | Durable evidence |
| --- | --- | --- | --- | --- | --- |
| Catalog/business discovery | yes | yes | n/a | parallel reads | tenant-specific response |
| Appointment slot discovery | yes | yes | n/a | read during contention | RLS-filtered slots |
| Appointment booking | 8 patients | yes | covered by integration + E2E command keys | same exclusive slot | exactly one confirmed reservation |
| Appointment cancellation / capacity recovery | yes | tenant-bound | unique command replay contract | follows booking race | cancelled reservation frees capacity |
| Appointment authority | patient representations + staff override | tenant-bound | n/a | race uses independent principals | authority evaluated in DB transaction |
| Queue join | 6 patients | yes | unique keys | FIFO sequence | queue entry rows |
| Queue call-next | staff + 6 patients | tenant-bound | exact same-key replay | serialized queue lock | one `queue.entry_called.v1` per entry |
| Queue empty state | yes | tenant-bound | idempotent command | after drain | `null` response without phantom entry |
| Generic request submit | requester + staff | yes | same-body replay + conflicting-body rejection | revision checks | request/idempotency rows |
| Generic request result | staff | tenant-bound | command idempotency | optimistic revision | revision increment |
| Generic request complete | staff | tenant-bound | command idempotency | stale revision rejected | terminal state |
| Mutation after terminal request | staff | tenant-bound | n/a | state-machine guard | rejected without state regression |
| PostgreSQL runtime privilege boundary | all HTTP journeys | all tenants | n/a | all above | application uses member of `request_engine_app` |

## Required next matrix entries when their runtime surfaces are composed

These are real product capabilities, but they are not currently all reachable through `request_engine.entrypoints.http.app.create_app`. They must not be represented by fake HTTP mocks in this suite.

- communications delivery provider success, retry, permanent failure, and duplicate provider callback
- reminder scheduling, acknowledgement, cancellation, late acknowledgement, and no-show transition
- SlotOpportunity / Waitlist / CapacityHold / SlotOffer accept, decline, expiry, and next-candidate advancement
- worker crash after claim and before acknowledgement, lease expiry, recovery, and duplicate execution protection
- provider events and webhook replay/out-of-order delivery
- payment verification/settlement flows when exposed by the production composition root

When one of these capabilities becomes reachable in the production composition root, adding its E2E scenario is part of the feature's definition of done.
