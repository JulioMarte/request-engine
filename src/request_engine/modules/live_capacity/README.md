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
staff projection reads
read-only intake evaluation
customer-safe ETA reads
```

It does **not** own Reservation, CapacityClaim, QueueEntry, ServiceSession, ResourceActivity, schedule or availability truth. Projection output never creates/releases capacity, rewrites planned time, mutates execution history or becomes an authoritative counter.

Cross-module inputs are restricted to supported contracts:

```text
booking.contracts.live_capacity
queue.contracts.live_capacity
delivery.contracts.live_capacity
```

Do not import Booking/Queue/Delivery adapters or persistence mappings.

The deterministic estimator baseline is defined by `docs/v3/29-live-capacity-projection-contract.md`. Unknown duration and open-ended live occupation are represented explicitly rather than replaced by arbitrary averages.

Projection values such as queue position, ETA, projected end and remaining headroom are computed from current facts on read. Initial F4 does not persist them as authoritative state.
