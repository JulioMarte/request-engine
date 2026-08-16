# ADR 0010 — Reservation access belongs to Delivery, not Booking

## Status

Proposed — tentative direction. The boundary decision (access belongs to Delivery, not Booking) still needs to be validated before it is treated as accepted: whether Delivery should own this at all, whether provider/access concerns belong elsewhere, and whether the proposed reconciliation/idempotency model is the right one.

## Context

Concrete product use cases now require a confirmed Reservation to yield an execution/access mechanism: a Google Meet/Zoom/Teams/LiveKit join link, a phone-call bridge, a physical location, or instructions. Adding `meeting_url` directly to Booking would make provider/execution concerns part of capacity truth.

Current V3 already states that Booking owns only local reservability/capacity/Reservation truth, provider I/O occurs after commit, and Delivery may be reactivated when a concrete execution vertical proves an independent boundary.

## Decision

Reactivate Delivery narrowly around `ReservationAccess`.

- `OfferingVersion.delivery_policy` is immutable configuration describing required access artifacts.
- Booking commits Reservation/capacity without Delivery participation or dependency.
- The reservation lifecycle worker maps committed Booking snapshots into Delivery's own contract.
- Provider adapters materialize or revoke external sessions outside DB transactions.
- Static physical/instruction access can materialize without a provider.
- `ReservationAccess` is keyed by `(organization, reservation, access_key)` and records the Reservation revision it represents.
- A reschedule revision can therefore re-materialize stale provider access deterministically.
- Provider idempotency identity is semantic (`reservation + access_key + reservation revision`), not tied to an arbitrary retry/event attempt.
- Cancellation revocation calls the provider before marking local state revoked so provider failure remains retryable.
- V2 ServiceSession/Fulfillment/OutcomeScope remain deferred.

## Consequences

This supports meeting booking, scheduled calls, physical appointments and future access mechanisms without making Booking provider-aware. Provider-specific behavior remains replaceable.

Access URIs can behave like bearer credentials. This ADR does **not** publish an unrestricted end-user HTTP read capability. A later `reservation_access.get` surface must reuse Reservation Party authority and expose only the access fields authorized for the caller.
