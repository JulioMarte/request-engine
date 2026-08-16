# Delivery module

> **V3 status: narrowly reactivated/incubating for `ReservationAccess`.**
> Advanced execution/fulfillment concepts remain deferred and are not baseline dependencies.

Delivery owns the post-commit access artifacts required to execute a confirmed Reservation without
making Booking provider-aware. The currently admitted capability is deliberately small:

```text
Booking Reservation commit
        |
        | reservation.* outbox fact
        v
Reservation lifecycle worker
        |
        | Delivery contract
        v
ReservationAccess
        |
        | provider port (optional)
        v
Meet / Zoom / Teams / LiveKit / phone bridge / other access provider
```

## Ownership boundary

Delivery currently owns:

- `OfferingVersion.delivery_policy` interpretation for access artifacts;
- `ReservationAccess` materialization/revocation;
- provider-neutral access kinds (`video_link`, `phone`, `physical_location`, `instructions`,
  `external_session`);
- semantic provider materialization identity and reconciliation.

Delivery still does **not** activate the former V2 `ServiceSession`, `Fulfillment`, `OutcomeScope`,
correction, admission, queue, or payment models. Queue ownership remains in `queue`. Booking remains
the sole owner of Reservation/capacity truth.

Baseline modules must not import Delivery. Composition happens in
`entrypoints/worker/reservation_lifecycle.py`, which depends on the public contracts of both sides.

## Database and worker authority

`request_engine_worker` owns only the Outbox control-plane lease. It has no SELECT/DML authority on
`request_engine.reservation_access` and does not receive its read view.

Delivery repositories are constructed from `domain_session_factory` and authenticate through the
`request_engine_app` role. READY and REVOKED transitions validate the current Outbox `claim_token`
inside the same app transaction through `request_cmd.lock_outbox_message_claim(...)`.

The Outbox token is a technical capability. It is passed only to explicitly fenced internal
handlers and is never added to the published `OutboxEvent`.

## Provider I/O and crash recovery

Provider/network I/O never runs while authoritative database locks are held.

Each access row is scoped to:

```text
organization + reservation + reservation_revision + access_key
```

and has a stable provider identity:

```text
reservation-access:{reservation_id}:{access_key}:r{reservation_revision}
```

Provider adapters must make `provision` semantically idempotent by that key, expose a non-creating
`lookup`/reconciliation operation for ambiguous crash outcomes, and make `revoke` idempotent.

`pending` is recovery evidence, not usable access authority. A stale process may record provider
evidence after it loses its Outbox lease so a new claimant can recover without blindly creating a
second provider artifact. Only a holder of the current Outbox lease can publish `ready` or
`revoked`.

A reschedule creates access for the new Reservation revision only after older unrevoked revisions
are reconciled/revoked. Old rows are retained as audit/recovery evidence rather than overwritten.
A stale Reservation revision is rejected before it can revoke current access.

## Read surface

`request_read.reservation_access_v1` is an internal app/admin projection. Access URIs can be bearer
credentials, so this change does not create a public HTTP endpoint. Any future caller-facing read
capability must reuse Reservation Party authority and explicitly constrain which access fields are
returned.
