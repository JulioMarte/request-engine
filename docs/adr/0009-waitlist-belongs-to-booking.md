# ADR 0009 — Waitlist and released-slot recovery belong to booking

- **Status:** Accepted for the V3 pre-baseline candidate
- **Date:** 2026-08-12

## Context

V3 originally placed both `ServiceQueue` and future-capacity `Waitlist` concepts in the `queue` module. This grouped them because both contain ordered customer flow.

The adversarial vertical review exposed a harder boundary: accepting a `SlotOffer` must atomically validate an unexpired `CapacityHold`, promote held `CapacityClaim`s into a `Reservation`, mark the offer accepted, close/fill the `SlotOpportunity`, and fulfill the selected `WaitlistEntry`.

With queue owning `WaitlistEntry`/`SlotOpportunity`/`SlotOffer` and booking owning Hold/Claim/Reservation, the invariant creates an awkward `queue |-| booking` transaction. The current booking handlers intentionally own one PostgreSQL transaction internally. Satisfying atomicity across the old module boundary would require one of the following:

1. leak SQLAlchemy `Session`/UnitOfWork mechanics into a cross-module contract;
2. create a broad shared transaction/UoW abstraction;
3. let queue mutate booking-owned tables directly;
4. split an invariant that requires strong local atomicity into asynchronous steps.

All four are worse than moving the ownership boundary.

## Decision

`ServiceQueue` remains owned by `queue`.

The following concepts move to `booking` ownership:

```text
WaitlistEntry
SlotOpportunity
SlotOffer
released-slot candidate selection policy
short CapacityHold used by an active SlotOffer
accept/decline/expire offer orchestration
```

The public capability namespace remains `waitlist.*`. Public API taxonomy is not required to mirror internal bounded-module names.

`booking` therefore owns the complete future-capacity recovery invariant:

```text
released capacity
  -> SlotOpportunity
  -> eligible WaitlistEntry
  -> short CapacityHold
  -> SlotOffer
  -> accept
  -> Reservation
```

Communications remains an asynchronous consequence after the offer transaction commits.

## Why this is simpler

The dominant invariants are capacity/booking invariants, not queue-position invariants:

- a WaitlistEntry never consumes capacity;
- SlotOpportunity never proves availability;
- an offered SlotOffer is backed by a live CapacityHold;
- only one active offer exists per opportunity;
- acceptance is atomic with Reservation confirmation and held-claim promotion;
- decline/expiry atomically releases the Hold before another candidate can be offered.

FIFO is merely the baseline candidate-selection policy. Having an ordered selection policy is not sufficient reason to put the aggregate in the live ServiceQueue bounded context.

## Consequences

### Positive

- removes the hardest planned synchronous `queue -> booking` dependency;
- avoids leaking transaction/session mechanics across modules;
- keeps Hold/Claim/Reservation/SlotOffer correctness in one transactional owner;
- ServiceQueue can evolve independently as a live operational queue;
- public `waitlist.*` API remains stable even if internal module ownership changes.

### Negative

- `booking` becomes broader: appointments plus future appointment standby/recovery;
- documentation and existing SQL comments/ownership maps must be updated;
- if a future non-booking waitlist appears, it may justify a separate module later.

## Rejected alternatives

### Generic cross-module UnitOfWork

Rejected because SQLAlchemy Session is already the technical unit of work and exposing a generic shared transaction facade would add abstraction without removing domain complexity.

### Queue directly mutates booking tables

Rejected because it destroys authoritative ownership and makes future reasoning about capacity mutations harder.

### Eventual-consistency acceptance

Rejected because `AcceptSlotOffer` must not produce accepted offer state without the corresponding Reservation, or vice versa.

### Separate waitlist microservice/module

Rejected for baseline because it preserves the same atomic cross-owner problem without an independent scaling/security/deployment reason.

## Revisit when

Reconsider this boundary if product evidence introduces waitlists that are not fundamentally future booking/capacity demand, or if operational assignment/capacity becomes externally owned and the transaction model changes materially.
