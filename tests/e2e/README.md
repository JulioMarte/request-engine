# End-to-end evidence suite

This directory is the production-like evidence layer for Request Engine. It is intentionally different from module and integration tests: scenarios enter through public HTTP surfaces where those surfaces exist, execute against real PostgreSQL, use production-equivalent runtime roles, and assert durable database outcomes.

The full extension contract, crash matrix, and definition-of-done checklist live in [`docs/e2e-evidence-framework.md`](../../docs/e2e-evidence-framework.md).

## Rules

- Do not replace PostgreSQL locking, RLS, constraints, idempotency, leases, or transaction behavior with mocks.
- Seed data only with the administrative fixture. Application traffic uses an ephemeral login inheriting from `request_engine_app`; worker scenarios use an independent ephemeral login inheriting from `request_engine_worker`.
- Every actor has an explicit tenant, principal, capability set, and where applicable party representation.
- Concurrency scenarios must run simultaneously, not as serialized approximations.
- A replay is successful only when the semantic response and durable side effects remain identical.
- Cross-tenant probes must use resources that really exist in the other tenant and prove both non-disclosure and non-mutation.
- Worker claims must prove fencing: stale claim tokens cannot complete, retry, or dead-letter reclaimed work.
- Crash recovery tests must model abandoned/expired leases and exercise the production reclaim path.
- An uncertain external side effect must reconcile before resend.
- Capabilities that are not reachable from the composed runtime are documented as gaps rather than mocked into a false green E2E.

## Framework primitives

- `http_surface.py` is the executable registry for every public `/v1` operation. OpenAPI must match it exactly.
- `test_http_security_matrix.py` automatically proves `401` and required-capability `403` for every registry entry and asserts no durable mutation.
- `tenant_sandbox.py` creates real isolated tenants with catalog, capacity, queues, requests, principals, and parties.
- `test_http_tenant_isolation_matrix.py` automatically exercises the declared `FILTERED`/`NOT_FOUND` isolation policy against objects that actually exist in another tenant.
- `evidence.py` centralizes durable non-mutation snapshots. Extend it when a new subsystem adds durable mutation surfaces.
- `operational_support.py` centralizes runtime-role and worker primitives.
- `test_communication_worker_resilience.py` models provider ambiguity, poison work, lease recovery, crash windows, and multiple workers contending for due communication work.

A new public endpoint that is not classified in `PUBLIC_HTTP_OPERATIONS` intentionally fails the OpenAPI guard. Do not weaken the guard; extend the framework.

## Current executable matrix

| Surface / invariant | Multi-user | Multi-tenant | Replay / fencing | Concurrency / crash | Durable evidence |
| --- | --- | --- | --- | --- | --- |
| Public HTTP authentication | all `/v1` operations | actor tenant declared | n/a | n/a | `401` + unchanged durable snapshot |
| Public HTTP capability authorization | all `/v1` operations | actor tenant declared | n/a | n/a | exact `403` capability + unchanged snapshot |
| Public HTTP tenant isolation | all `/v1` operations | two real tenants | n/a | n/a | filtered collections or foreign-resource `404`, unchanged snapshot |
| Catalog/business discovery | yes | yes | n/a | parallel reads | tenant-specific response |
| Appointment slot discovery | yes | yes | n/a | read during contention | RLS-filtered slots |
| Appointment booking | 8 patients | yes | command idempotency | same exclusive slot | exactly one confirmed reservation |
| Appointment cancellation / capacity recovery | yes | tenant-bound | command replay contract | follows booking race | cancelled reservation frees capacity |
| Appointment authority | patient representations + staff override | tenant-bound | n/a | independent principals race | authority evaluated in DB transaction |
| Queue join | 6 patients | yes | unique keys | FIFO sequence | queue entry rows |
| Queue call-next | staff + 6 patients | tenant-bound | exact same-key replay | queue lock | one `queue.entry_called.v1` per entry |
| Queue empty state | yes | tenant-bound | idempotent command | after drain | `null` response without phantom entry |
| Generic request submit | requester + staff | yes | replay + conflicting-body rejection | revision checks | request/idempotency rows |
| Generic request result / terminal lifecycle | staff | tenant-bound | command idempotency | optimistic revision | revision and terminal-state guards |
| HTTP PostgreSQL privilege boundary | all journeys | all tenants | n/a | all above | app login inherits `request_engine_app` |
| ScheduledAction claim | independent worker sessions | global tenant discovery through worker command | claim-token fencing | simultaneous workers use `SKIP LOCKED` | disjoint claimed batches |
| ScheduledAction retry / dead-letter | worker | cross-tenant worker surface | stale tokens rejected | expired lease reclaimed after simulated crash | attempt count, dead state, error class |
| ScheduledAction exhaustion | worker | yes | terminal fence | pending or expired leased work exhausted before claim | automatic `max_attempts_exhausted` dead-letter |
| Outbox claim | independent worker sessions | global tenant discovery through worker command | claim-token fencing | simultaneous workers use `SKIP LOCKED` | disjoint claimed batches |
| Outbox retry / delivery / dead-letter | worker | yes | stale tokens rejected | expired lease reclaimed after simulated crash | delivered/dead timestamps and errors |
| Runtime role DELETE boundary | app + worker | n/a | n/a | n/a | semantic lifecycle cannot be bypassed by DELETE |
| Worker SECURITY DEFINER boundary | worker | all tenants by design | fixed command contract | n/a | security-definer functions pin trusted `search_path` |
| CommunicationTask persistence | multiple recipients | yes | tenant-scoped `dedupe_key` | n/a | duplicate intent and cross-tenant contact references rejected |
| CommunicationDelivery persistence | multiple attempts | yes | provider idempotency + message correlation | n/a | unique attempt/provider keys and positive attempt number |
| Communication provider execution | worker | tenant transaction | provider idempotency | send ambiguity + reconciliation | task/delivery/action/outbox converge |
| Crash after prepare | worker | tenant transaction | reclaimed lease fenced | lookup before any resend | one delivery attempt, one terminal event |
| Crash after provider finalize before action ack | worker | tenant transaction | old claim token fenced | reclaimed action performs zero second send | one delivery + one completion outbox |
| Communication worker contention | multiple workers | global worker claim | unique provider keys | 3 workers / 12 due tasks | every task/action terminal exactly once |
| Poison ScheduledAction | worker | n/a | terminal fence | unsupported type/payload | immediate dead-letter, no recycled poison work |
| ProviderEvent ingestion | provider callbacks | yes | provider/connection/event dedupe | out-of-order distinct events accepted | immutable distinct event rows retained |
| Reminder acknowledgement persistence | patient response | tenant-bound | duplicate occurrence acknowledgement rejected | duplicate callback simulation | one acknowledgement per plan/occurrence/subject |
| Reminder plan schema boundary | n/a | tenant-bound | n/a | n/a | unsupported recurrence type rejected |
| Public API inventory | all `/v1` operations | isolation metadata required | idempotency metadata required | n/a | OpenAPI must equal executable registry |

## Required next matrix entries when their runtime surfaces are composed

The worker substrate has executable communication delivery evidence. The following business orchestration is not yet reachable through the current production composition root and must not be represented by fake HTTP mocks:

- reminder recurrence execution: occurrence materialization, DST gaps/folds, max-lateness behavior, cancellation racing a leased occurrence, and recurrence-chain crash replay;
- `SlotOpportunity -> Waitlist -> CapacityHold + SlotOffer`: candidate selection, atomic offer creation, accept, decline, expiry, hold release, and next-candidate advancement;
- booking attendance/no-show orchestration and automatic slot-opportunity generation;
- provider-event processing semantics after durable ingestion, including duplicated and out-of-order status transitions and crash recovery;
- payment verification/settlement flows when exposed by the production composition root.

When one of these capabilities becomes reachable in the production composition root, its registry/support changes and E2E scenarios are part of the feature's definition of done.
