# ADR 0010 — Reservation access belongs to Delivery, not Booking

## Status

Proposed — implementation and release evidence are being reconciled on PR #49. Promote this ADR to
Accepted only after the exact final PR SHA passes the PostgreSQL, architecture, race, privilege,
test-quality, and release gates.

## Context

Concrete product use cases require a confirmed Reservation to yield an execution/access mechanism:
a Google Meet/Zoom/Teams/LiveKit join link, a phone-call bridge, a physical location, instructions,
or another external session. Adding provider fields such as `meeting_url` directly to Booking would
make provider/execution concerns part of capacity truth.

V3 already establishes that Booking owns local Reservation/capacity truth, provider I/O occurs
after commit, runtime worker credentials are control-plane only, and deferred modules may be
reactivated only when a concrete capability proves an independent boundary.

The first PR #49 draft predated the final production worker assembly. It reused
`request_engine_worker` for `ReservationAccess` DML and represented one access key with a single
mutable row across Reservation revisions. That design is rejected: it crosses the credential
boundary, can strand a `pending` row after a crash, and can lose the evidence needed to revoke an
older external artifact during reschedule.

## Decision

Reactivate Delivery narrowly around `ReservationAccess`.

- `OfferingVersion.delivery_policy` is immutable configuration describing required access
  artifacts.
- Booking commits Reservation/capacity without Delivery participation or dependency.
- The reservation lifecycle Outbox handler maps committed Booking snapshots into Delivery's public
  contract at the worker composition boundary.
- `request_engine_worker` retains only Outbox claim/heartbeat/finalization authority.
- Delivery repositories use `domain_session_factory` / `request_engine_app`.
- The composition root reserves Reservation lifecycle Outbox event names so they cannot be injected
  through the generic unfenced internal-handler map.
- The technical Outbox `claim_token` is passed to fenced local handlers but never placed on the
  integration `OutboxEvent` published externally.

### ReservationAccess identity

One row represents one access artifact for one exact Reservation revision:

```text
(organization_id, reservation_id, reservation_revision, access_key)
```

Old revisions are retained. They are reconciled/revoked rather than overwritten when a reschedule
creates a newer revision.

Provider materialization uses a stable semantic key:

```text
reservation-access:{reservation_id}:{access_key}:r{reservation_revision}
```

The key is independent of worker attempt or event redelivery.

### Provider protocol

Provider I/O occurs outside authoritative DB transactions.

Provider adapters must provide:

1. idempotent `provision(materialization_key, ...)`;
2. non-creating `lookup(materialization_key)` for crash/ambiguous-result reconciliation;
3. idempotent `revoke(materialization_key, ...)`.

A provider error propagates and remains retryable. An unknown provider is not silently ignored.

### Pending evidence versus published authority

`pending` is intentionally non-authoritative. It may carry provider evidence while access is not yet
published.

This handles the unavoidable crash window:

```text
provider succeeds
process crashes before DB publication
```

A later claimant can `lookup` by the same materialization key or reuse already-recorded provider
evidence instead of blindly provisioning a duplicate.

Recording provider evidence on an existing `pending` row does not require the Outbox lease because
it grants no usable access authority. This is the narrow exception that makes crash reconciliation
possible without holding a PostgreSQL lock over network I/O.

Transitions to `ready` and `revoked` are different: they are authoritative and therefore require
the current Outbox claim.

### Outbox authoritative fence

Migration `027-reservation-access-delivery.sql` introduces
`request_cmd.lock_outbox_message_claim(organization_id, message_id, claim_token)`.

The function is `SECURITY DEFINER` because the app role must prove a worker-control fact without
receiving direct access to `outbox_messages`. Its threat model is deliberately narrow:

- caller tenant GUC must equal the supplied organization;
- message id, organization, status, claim token, and non-expired lease must all match;
- the matching Outbox row is locked `FOR UPDATE` for the duration of the app transaction;
- `search_path` is pinned to `pg_catalog, request_engine`;
- `PUBLIC` has no execute privilege;
- only app/admin receive execute;
- worker receives no `ReservationAccess` table/view privileges.

READY/REVOKED writes call this function inside the same `request_engine_app` transaction as the
authoritative state change. A worker that loses its lease during provider I/O can preserve
non-authoritative evidence, but cannot publish or revoke local access authority.

### Reschedule and cancellation

Before materializing the current revision, Delivery reconciles older/unwanted unrevoked rows.
Provider revocation succeeds before local `revoked` publication; if provider revocation fails, the
local row remains retryable.

A confirmed source revision is revalidated against the current Reservation and Outbox claim before
it can affect access. A stale revision therefore cannot revoke a newer READY row.

If cancellation or reschedule happens while provisioning is in flight, the late result can be
recorded as pending evidence but cannot become READY unless the Reservation revision is still
current. A current claimant then revokes/reconciles that artifact.

### Deferred scope

V2 `ServiceSession`, `Fulfillment`, `OutcomeScope`, execution corrections, queue/admission,
payments, and generalized delivery orchestration remain deferred.

## Consequences

This supports meeting booking, scheduled calls, physical appointments, and other access mechanisms
without making Booking provider-aware or giving the worker role business-table authority.

The design accepts at-least-once provider round trips. Exactly-once network calls are not claimed;
the guarantee is semantic idempotency plus reconciliation and fenced publication.

Access URIs can behave like bearer credentials. This ADR does **not** create an unrestricted
caller-facing HTTP read capability. A future `reservation_access.get` surface must reuse
Reservation Party authority and expose only explicitly authorized fields.

## Rejected alternatives

### Put `meeting_url` on Reservation

Rejected because Booking would absorb provider/execution concerns and provider lifecycle.

### Let `request_engine_worker` write ReservationAccess

Rejected because #47 deliberately separates cross-tenant control-plane credentials from
tenant-scoped authoritative domain credentials.

### Keep one mutable row per `(reservation, access_key)`

Rejected because reschedule would overwrite the evidence required to revoke the prior revision and
makes stale/new provider artifacts harder to distinguish.

### Hold an Outbox or Reservation lock during provider I/O

Rejected because it violates the database access contract and creates long-lived authoritative
transactions around network latency/failure.

### Delete pending rows on retry

Rejected as the primary recovery protocol because a provider may already have succeeded before the
process crashed. Deleting the only local evidence encourages blind duplicate provisioning.
