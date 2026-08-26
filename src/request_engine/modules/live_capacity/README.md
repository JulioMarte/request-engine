# Live Capacity module

> **F4 active feature module. Advisory projection only.**

Live Capacity answers how known remaining workload projects over the Resource's remaining effective operational intervals for one configured ServiceQueue + Resource + Location scope.

It owns:

```text
projection-scope configuration
workload-estimate policy
estimate provenance/fallback semantics
remaining-work deduplication
interval projection
scheduled-vs-live advisory comparison
staff projection reads
read-only intake evaluation
customer-safe ETA reads
```

It does **not** own Reservation, CapacityClaim, QueueEntry, ServiceSession, ResourceActivity, schedule or availability truth. Projection output never creates/releases capacity, rewrites planned time, mutates execution history or becomes an authoritative counter.

The staff projection deliberately exposes two different views:

```text
scheduled_committed_workload_seconds / scheduled_headroom_seconds
    Booking planning/commitment view.

live_intake_headroom_seconds
    F4 projection of current operational reality.

live_vs_scheduled_headroom_delta_seconds
    live_intake_headroom_seconds - scheduled_headroom_seconds.
```

`live_headroom_seconds` remains a compatibility alias for the live-intake value. A negative delta means live reality is consuming more projected work than the schedule alone implies; a positive delta means current operational reality is ahead of the still-preserved planning view.

Cross-module inputs are restricted to supported contracts:

```text
booking.contracts.live_capacity
queue.contracts.live_capacity
delivery.contracts.live_capacity
```

Do not import Booking/Queue/Delivery adapters or persistence mappings.

The deterministic estimator baseline is defined by `docs/v3/29-live-capacity-projection-contract.md`. Unknown duration and open-ended live occupation are represented explicitly rather than replaced by arbitrary averages. Estimate precedence is Resource history, tenant history, configured policy, applicable planned duration, then unknown.

Reservation/QueueEntry/ServiceSession composition counts one real service at most once. When a Reservation has checked in, its planned duration may follow the winning live representation only as estimate provenance. When a reservation-backed QueueEntry has already completed before its scheduled start, Queue publishes that bounded terminal fact so the Reservation remains visible in scheduled planning truth but does not reappear as unfinished live workload.

Projection values such as queue position, ETA, projected end and remaining headroom are computed from current facts on read. Initial F4 does not persist them as authoritative state.
