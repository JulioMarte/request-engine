# End-to-end evidence suite

This directory is Request Engine's production-like evidence layer. E2E scenarios cross the same HTTP, PostgreSQL, RLS, transaction, idempotency, worker-role, lease, fencing, and crash boundaries used by runtime code.

The HTTP tests inject a deterministic `ActorResolver`; they prove the behavior after the deployment authentication adapter accepts or rejects a credential. They do not prove any particular JWT/OIDC/API-key adapter. Each deployment adapter requires its own signature, issuer, audience, expiry and key-rotation tests before production use.

The extension contract and definition-of-done checklist live in [`docs/e2e-evidence-framework.md`](../../docs/e2e-evidence-framework.md).

## Non-negotiable rules

- PostgreSQL locking, RLS, constraints, idempotency, leases, and transactions are never mocked.
- Fixture/bootstrap credentials only seed/inspect state. HTTP traffic uses an ephemeral login inheriting `request_engine_app`; worker traffic uses an independent login inheriting `request_engine_worker`.
- Cross-tenant probes target data that really exists in another tenant and prove non-disclosure plus unchanged durable state.
- Concurrency tests execute concurrently; serialized approximations do not count.
- Crash recovery tests abandon/expire real leases and exercise the production reclaim path.
- An uncertain external side effect reconciles before resend.
- Planned or internal-only capabilities are not invented as public HTTP routes.
- Rejected state-changing journeys prove important absence of partial effects, preferably with an authoritative durable-state fingerprint when the scope is broad.

## Framework primitives

- `http_surface.py` classifies every currently composed public `/v1` operation. Internal-only commands remain absent from the public registry.
- `test_public_surface_contract.py` forces OpenAPI to equal the registry and binds every idempotent command to a required `Idempotency-Key` header.
- `test_http_security_matrix.py` proves authentication/capability behavior for the composed public operation surface.
- `tenant_sandbox.py` creates real Organizations with catalog, capacity, queues, requests, principals, parties, and signed appointment options.
- `evidence.py` fingerprints every authoritative table, including row content, so rejected-operation proofs can detect partial mutation rather than checking only row counts.
- `test_http_tenant_isolation_matrix.py` exercises the production tenant/Party boundary using real foreign resources and durable before/after state.
- `test_multi_user_journeys.py` proves exclusive-slot contention/recovery, tenant isolation, FIFO queue replay, and the public Request lifecycle.
- `test_contextual_booking_journey.py` proves the F1 public contextual chain `business -> catalog -> find_slots -> aptopt_v2 -> book`, exact assignment/commercial provenance, stale-option 409 behavior, and fail-closed contextual reschedule with no partial mutation.
- `test_contextual_location_separation.py` proves the same Resource may have two Location contexts with distinct schedule/price/duration without cross-context leakage.
- communication/worker E2E files prove provider ambiguity, poison work, reclaim/fencing, crash windows, ordering and multi-worker contention.
- `test_worker_scheduling_semantics.py` and `test_outbox_semantics.py` prove `SKIP LOCKED`, lease reclaim, token fencing, retry exhaustion, runtime privilege and durable outbox semantics.
- `test_delivery_persistence_semantics.py` proves durable dedupe/correlation constraints.

## Current-product CI ownership

`tests/e2e/` belongs to the current-product proof, not to historical V3 provenance. The canonical current PostgreSQL runner (`scripts/ci/run_current_product.sh`) executes this directory against the repository's current Alembic head.

Historical V3 reproducibility may separately execute the released V3 source against its released schema, but that lane must never be the only place production-like current journeys run.

## Adding a feature

A feature PR that adds a public endpoint must update the public-operation registry in the same PR. If the OpenAPI surface changes without classification, CI fails. `DurableSnapshot` fingerprints authoritative tables automatically, so rejected operations should preserve durable content as well as cardinality. A new external side effect must add crash-window evidence. A new worker must prove claim disjointness, stale-token fencing, retry/dead-letter behavior, and reclaim after lease expiry.

Public features that change the meaning of an existing route still need a production-like journey even when no new endpoint is added. Use narrow integration tests for deterministic races/invariants and E2E for the composed externally observable chain; neither layer substitutes for the other.

Do not weaken these guards to make a new feature pass; extend the evidence framework.
