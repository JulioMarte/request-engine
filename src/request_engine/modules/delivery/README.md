# Delivery module

> **Current status: active post-V3.**
>
> Delivery owns both Reservation access artifacts and the F3 live execution model. The historical
> V3 baseline did not require ServiceSession; F3 activates it narrowly without activating a generic
> Fulfillment/Outcome system. See `docs/v3/26-live-service-operations-contract.md` and
> `docs/v3/28-live-service-operations-integration-amendment.md`.

## Current ownership

Delivery owns two distinct capabilities.

### Reservation access

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
Meet / Zoom / Teams / LiveKit / phone bridge / physical instructions / other provider
```

Delivery owns:

- `OfferingVersion.delivery_policy` interpretation for access artifacts;
- `ReservationAccess` materialization/revocation;
- provider-neutral access kinds;
- semantic provider materialization identity and reconciliation.

Booking remains the sole owner of Reservation and capacity truth.

### Live service execution — F3

```text
QueueEntry CALLED
        |
        | service_session.start
        v
ServiceSession ACTIVE
        |
        +-- pause --> PAUSED + ServiceSessionInterruption
        |               |
        |               `-- resume --> ACTIVE
        |
        `-- complete --> COMPLETED
```

Delivery owns:

```text
ServiceSession
ServiceSessionInterruption
ResourceActivity
actual execution Resource/Location
actual workload classification on ServiceSession
execution timestamps
```

Queue owns waiting/admission/calling/no-show. Delivery owns actual execution. QueueEntry `serving`,
`completed`, `service_started_at` and `completed_at` are compatibility mirrors written atomically
with ServiceSession; they are not independent execution truth.

F3 does **not** activate:

```text
universal Fulfillment
OutcomeScope
clinical notes/diagnosis/treatment state
payments/reconciliation
universal workflow
```

## Live execution invariants

`service_session.start` is one PostgreSQL transaction:

1. acquire idempotency;
2. lock ServiceQueue;
3. lock QueueEntry and verify expected revision + `called`;
4. lock Resource;
5. validate execution-time ResourceLocationAssignment and resource occupation;
6. insert ServiceSession with DB time;
7. move QueueEntry to `serving` using the same start timestamp;
8. append audit/outbox;
9. complete idempotency;
10. commit.

`service_session.complete` similarly completes Session and QueueEntry atomically using one database
completion timestamp. Completion while paused is rejected.

Pause creates one durable interruption and changes `active -> paused`. Resume closes the exact open
interruption and changes `paused -> active`. QueueEntry remains `serving` throughout pause/resume.

Canonical live-operation lock order:

```text
ServiceQueue -> QueueEntry -> Resource -> ServiceSession -> open interruption/activity
```

## ResourceActivity

ResourceActivity represents non-patient occupation such as:

```text
break
emergency
administrative
other_operational
```

It never creates a fake Party, QueueEntry, Reservation or ServiceSession.

Current F3 policy is conservative:

- at most one active/paused ServiceSession per Resource;
- at most one open ResourceActivity per Resource;
- open ResourceActivity conflicts with live ServiceSession;
- live ServiceSession conflicts with starting ResourceActivity;
- both paths serialize through the Resource row.

Parallel/group execution requires a future explicit policy change.

## Live execution capabilities

```text
service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read
resource_activity.start
resource_activity.end
```

Every externally retryable mutation requires Idempotency-Key. Commands targeting an existing
mutable object require expected revision; creation commands use idempotency plus authoritative
locking instead.

## Delivery policy contract

`OfferingVersion.delivery_policy` remains immutable operational configuration for ReservationAccess.
The canonical shape is:

```json
{
  "access": [
    {
      "key": "video",
      "kind": "video_link",
      "provider": "meeting",
      "provisioning": "immediate",
      "public_data": {}
    }
  ]
}
```

Rules:

- top-level value is an object;
- `access`, when present, is an array of objects;
- each entry has one non-empty, trimmed, unique `key`;
- `kind` is one of Delivery's `AccessKind` values;
- `provider`, when present, is a non-empty, trimmed provider key;
- `provisioning` is `immediate` or `manual` and defaults to `immediate`;
- `public_data` is an object and defaults to `{}`;
- immediate static access without a provider contains non-empty `public_data`.

`parse_delivery_policy(...)` remains the canonical application parser. Database checks provide
provider-independent defense in depth; deployment-specific provider registration remains application
configuration.

## ReservationAccess worker authority

`request_engine_worker` owns only Outbox control-plane leasing. It has no direct business DML
ownership over ReservationAccess. Delivery repositories use the domain session and validate the
current Outbox claim token before READY/REVOKED transitions.

Provider/network I/O never runs while authoritative database locks are held.

Each provider-backed access row has stable materialization identity:

```text
reservation-access:{reservation_id}:{access_key}:r{reservation_revision}
```

Crash recovery performs non-creating lookup before provisioning when local evidence is missing.
Provider provisioning and revoke operations must remain semantically idempotent.

## Read boundaries

ReservationAccess read projections may contain bearer-like access data and are not automatically
public HTTP surfaces.

F3 uses separate read models:

- customer queue status: subject-safe queue state only;
- staff live queue: operational identity + expected/actual execution context;
- ServiceSession read: Delivery execution facts.

No read DTO should collapse planning, waiting and execution into one universal record.
