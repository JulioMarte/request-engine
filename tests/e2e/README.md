# End-to-end evidence suite

This directory is Request Engine's production-like evidence layer. E2E scenarios cross the same HTTP, PostgreSQL, RLS, transaction, idempotency, worker-role, lease, fencing, and crash boundaries used by runtime code.

The extension contract and definition-of-done checklist live in [`docs/e2e-evidence-framework.md`](../../docs/e2e-evidence-framework.md).

## Non-negotiable rules

- PostgreSQL locking, RLS, constraints, idempotency, leases, and transactions are never mocked.
- Fixture/bootstrap credentials only seed/inspect state. HTTP traffic uses an ephemeral login inheriting `request_engine_app`; worker traffic uses an independent login inheriting `request_engine_worker`.
- Cross-tenant probes target data that really exists in another tenant and prove non-disclosure plus unchanged durable state.
- Concurrency tests execute concurrently; serialized approximations do not count.
- Crash recovery tests abandon/expire real leases and exercise the production reclaim path.
- An uncertain external side effect reconciles before resend.
- Planned or internal-only capabilities are not invented as public HTTP routes.

## Framework primitives

- `http_surface.py` classifies every currently composed public `/v1` operation. The Phase-5 development composition currently contains **24 operations** including capability discovery, attendance, waitlist, and ReminderPlan APIs; internal Request result/complete/fail commands are intentionally absent.
- `test_public_surface_contract.py` forces OpenAPI to equal the registry and binds every idempotent command to a required `Idempotency-Key` header.
- `test_http_security_matrix.py` proves authentication for all 24 operations, capability `403` for every capability-gated operation, and the special authenticated-but-not-capability-gated contract for `/v1/capabilities`.
- `tenant_sandbox.py` creates two real organizations with catalog, capacity, queues, requests, principals, parties, and signed appointment options.
- `test_http_tenant_isolation_matrix.py` exercises the production tenant/Party boundary using real foreign resources and verifies `200` filtering/context, `403` Party authority, or non-disclosure `404` as appropriate, always with a durable before/after snapshot.
- `evidence.py` snapshots reservations, claims, holds, queues, waitlists, slot offers, requests, ReminderPlans, outbox, scheduling, communication deliveries, and provider events. Add every new durable mutation surface here.
- `test_multi_user_journeys.py` proves exclusive-slot contention/recovery, tenant isolation, FIFO queue replay, and the **public** Request submit/read/cancel lifecycle. Internal Request processing commands belong to trusted integration tests, not public E2E.
- `test_communication_worker_resilience.py` proves provider ambiguity, poison work, reclaim/fencing, crash-after-prepare, crash-after-finalize-before-ack, and multi-worker contention.
- `test_worker_scheduling_semantics.py` and `test_outbox_semantics.py` prove `SKIP LOCKED`, lease reclaim, token fencing, retry exhaustion, and runtime privilege boundaries.
- `test_delivery_persistence_semantics.py` proves durable dedupe/correlation constraints.

## Adding a feature

A feature PR that adds a public endpoint must update `PUBLIC_HTTP_OPERATIONS` in the same PR. If the OpenAPI surface changes without classification, CI fails. A new mutating table must extend `DurableSnapshot`. A new external side effect must add crash-window evidence. A new worker must prove claim disjointness, stale-token fencing, retry/dead-letter behavior, and reclaim after lease expiry.

Do not weaken these guards to make a new feature pass; extend the evidence framework.
