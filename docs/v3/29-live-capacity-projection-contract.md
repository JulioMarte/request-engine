# Request Engine — F4 Live Capacity Projection Contract

Status: **normative feature contract for `feature/live-capacity-projection`**.

This contract defines the intended semantics and implementation boundaries of F4. Until implementation/evidence closes a requirement, this document is a target contract rather than a claim that the behavior already exists.

F4 builds on F1 contextual supply and F3 live-service facts. It does not replace Booking, Queue or Delivery authority.

## 1. Product goal

F4 answers the operational question:

> Given what is planned, what is actually happening now, and the effective operating time that remains today, how much work remains, when is service likely to start, and can another known workload plausibly fit?

The central model is:

```text
live capacity projection
=
remaining workload
projected over
remaining effective operational time
```

A patient count or free-slot count alone is not sufficient because workloads have different durations and live execution may diverge from the schedule.

## 2. Authority split

F4 is advisory/read-model authority only.

```text
Booking
  Reservation + CapacityClaim + schedule/availability truth

Queue
  who is actually waiting/called now + expected workload

Delivery
  what is actually being served + interruptions/resource occupation

Live Capacity
  deterministic projection over those authoritative facts
```

F4 MUST NOT create, release or reinterpret a CapacityClaim merely because a projection changes. It MUST NOT rewrite Reservation planned time, Queue facts, ServiceSession facts, configured schedule or workload classification history.

A projection becoming stale is normal. Authoritative mutations continue to revalidate against their owning module.

## 3. Scheduled capacity vs live intake capacity

These concepts are distinct.

```text
scheduled_capacity
  remaining planning supply from effective schedule/availability and commitments

live_intake_capacity
  today's projected headroom after incorporating current execution and live queue workload
```

`scheduled_capacity` does not become false because a clinic is running late. `live_intake_capacity` may deteriorate while scheduled planning facts remain unchanged.

F4 MUST preserve both views rather than overwrite planning truth with live estimates.

## 4. Projection scope

The initial F4 baseline is intentionally explicit and conservative:

```text
one projection scope
  -> one ServiceQueue
  -> one Resource
  -> one Location
```

A projection policy/configuration explicitly associates the queue with the Resource and Location whose remaining operational time is being evaluated.

This association is projection configuration. It is not automatic Queue ownership, automatic Resource assignment, or a promise that every waiting entry will ultimately be served by that Resource.

Multi-resource queue scheduling, load balancing and automatic provider assignment are outside initial F4 scope. F4 MUST NOT hide an optimizer behind ETA calculation.

## 5. Inputs

A projection may consume:

```text
ServiceQueue / QueueEntry live state
QueueEntry expected workload classification
ServiceSession current execution state
ServiceSession actual workload classification
ServiceSession interruption intervals
ResourceActivity occupation intervals
completed historical ServiceSession observations
Resource effective availability
Resource-at-Location assignment availability/exceptions
Location hours/exceptions
same-day Reservations / commitments
configured workload-estimate policy
```

Inputs remain owned by their source modules. `live_capacity` consumes published contracts or narrow database read projections; it MUST NOT import another module's private application/adapters internals.

## 6. Workload identity vs duration policy

`OperationalWorkloadClassification` remains an operational vocabulary. F4 MUST NOT redefine it into a mutable prediction record.

Keep separate:

```text
workload identity
  e.g. follow_up, initial_consultation

configured estimate policy
  e.g. follow_up -> 20 minutes

observed execution evidence
  completed ServiceSession active-service durations

projection estimate
  the duration F4 selected for this calculation
```

F4 therefore introduces a separate workload-estimate policy/configuration rather than adding predictive duration semantics to F3 classification identity.

Policy mutation is explicit, authorized, revision-controlled, idempotent where externally retryable, and auditable according to repository mutation rules.

## 7. Historical duration estimation

Observed execution may improve projections but MUST NOT silently mutate configured policy.

The initial estimator MUST be deterministic, explainable and bounded. It should prefer robust statistics over opaque learning. The implementation contract must fix and test:

```text
history lookback boundary
maximum sample count
minimum sample count
sample eligibility
workload matching
Resource-specific vs tenant fallback order
statistic used
rounding
outlier policy, if any
```

Completed `ServiceSession` observations use active service time, excluding interruption time, rather than blindly treating wall-clock elapsed time as productive workload.

The projection result MUST retain enough provenance to explain whether an estimate came from Resource history, broader tenant workload history, configured policy, planned contextual duration, or remained unknown.

## 8. Estimate fallback semantics

The baseline fallback order is conceptually:

```text
sufficient same-Resource + actual-workload history
  -> robust observed estimate
else sufficient tenant workload history
  -> robust observed estimate
else configured workload-estimate policy
  -> configured estimate
else applicable planned/contextual duration
  -> planned fallback
else
  -> unknown
```

The exact eligibility and fallback rules are frozen by implementation tests before promotion.

F4 MUST NOT fabricate a duration merely to return an ETA. Unknown inputs produce explicit partial/unknown projection state.

## 9. Remaining workload semantics

For waiting/called work:

```text
expected workload
  -> resolved estimate
  -> projected full remaining workload
```

For a currently active service:

```text
resolved estimated total workload
-
already observed active_service_seconds
=
estimated remaining workload
```

with a floor of zero.

Completed/no-show work contributes zero remaining live workload.

Actual workload recorded during execution may inform historical observations without rewriting the earlier expected workload.

## 10. Reservation / Queue / ServiceSession deduplication

The same real-world service MUST NOT be counted multiple times merely because it appears in planning and live representations.

Canonical rule:

```text
same-day Reservation not yet represented live
  -> may contribute planned future workload

Reservation with a live QueueEntry
  -> live QueueEntry representation wins for remaining-work projection

QueueEntry with active ServiceSession
  -> current execution representation wins for remaining-work projection

completed/no-show terminal work
  -> zero remaining workload
```

Reservation remains historical/planning provenance even when the live representation wins for projection.

Walk-ins can contribute live workload without a Reservation.

## 11. Effective operational time

F4 does not calculate `closing_time - now` as a shortcut.

Remaining operational time derives from the effective contextual availability already owned by F1/Booking, including as applicable:

```text
Resource availability
Resource-at-Location assignment schedule
assignment exceptions
Resource-wide exceptions
Location hours
Location exceptions
same-day effective boundaries
existing commitments
```

Projection operates over actual remaining availability intervals, which may be discontinuous.

F4 consumes this composition through a narrow published contract/read surface rather than duplicating Booking's availability algorithm.

## 12. Current interruptions and ResourceActivity

A closed interruption is factual elapsed non-service time and is excluded from active service duration.

An open interruption has no known end. F4 MUST NOT invent its end time from historical averages unless a later explicit policy contract authorizes such forecasting.

Likewise, an open `ResourceActivity` without a known end can make downstream start/end projections indeterminate.

The result must expose an explicit state/reason such as an open interruption or open resource occupation instead of presenting false precision.

## 13. Temporal snapshot consistency

A projection is valid only relative to an observation instant.

The authoritative `observed_at` MUST come from PostgreSQL time. Reads composing one projection should execute under one coherent read-only database snapshot, preferably `REPEATABLE READ`, so Queue, Delivery and Booking facts are not silently mixed from unrelated instants.

Projection reads MUST NOT acquire capacity/queue mutation locks merely to calculate advisory state.

The result exposes `observed_at` so consumers can reason about staleness.

## 14. Projection outputs

Depending on known inputs, F4 may derive:

```text
entries ahead
queue position
estimated wait
estimated service start
estimated service end
remaining current-service workload
remaining queue workload
remaining planned same-day workload
total projected remaining workload
remaining effective operational time
projected end-of-day
scheduled capacity/headroom
live intake headroom
whether a specified additional workload fits
estimate provenance / sample metadata
projection completeness or blocking reason
```

These are projections, not authoritative persisted counters.

Time/workload is the primary capacity unit. A generic `remaining_patients` value is not authoritative because different workloads consume different time.

## 15. Evaluate intake

F4 provides a read-only intake evaluation for a specified workload classification (and projection scope).

Conceptually it answers:

```text
If one more workload of this known type entered now,
where would it project to start/end,
and would it fit within effective remaining availability?
```

The operation may return:

```text
observed_at
resolved estimated duration
estimated start/end
fits_within_effective_availability
estimate source/provenance
projection completeness/blocking reason
```

It MUST NOT automatically check in a subject, create a Reservation, create a CapacityClaim, stop intake, extend hours or mutate policy.

## 16. Staff and customer privacy

Staff and customer projections are separate contracts.

Staff projection may expose operational identifiers and details necessary to operate the queue under appropriate authority.

Customer-facing projection may expose only the caller/subject's approved status, such as:

```text
entries ahead
own estimated wait
own estimated start
observed_at
```

It MUST NOT reveal names, Party identifiers, workloads, queue-entry identifiers or internal operational causes belonging to other customers. It MUST NOT expose private ResourceActivity reasons or historical samples.

A staff DTO is not made customer-safe by merely omitting a few fields at serialization time; the customer read surface is independently contracted.

## 17. Persistence model

Initial F4 MUST NOT persist changing projection values such as:

```text
queue_position
estimated_wait
estimated_start
remaining_capacity
projected_end_of_day
```

as authoritative state.

The initial model computes from current facts on read.

Persistence introduced by F4 is limited to configuration/policy and supporting relational/read structures required to derive projections safely and efficiently.

Caching may be added later as a non-authoritative optimization with explicit staleness semantics.

## 18. Module ownership

F4 introduces a dedicated bounded context:

```text
src/request_engine/modules/live_capacity/
```

Ownership:

```text
Booking
  commitments and effective planning availability

Queue
  waiting/called live state and expected workload

Delivery
  actual execution, interruptions and Resource occupation

Live Capacity
  estimate policy + projection semantics + projection read APIs
```

`live_capacity` may depend only on published cross-module contracts/read surfaces. Circular ownership is prohibited.

## 19. Migration and database requirements

F4 starts from the real Alembic predecessor head, including F3 historical-fact hardening. Any F4 migration must declare that actual predecessor rather than relying on stale documentation.

Expected F4 database work may include:

```text
projection-scope policy/configuration
workload-estimate policy/configuration
RLS + FORCE RLS
least-privilege grants
supporting indexes
narrow read views/functions where justified
```

Projection-state tables are not part of the initial design.

Indexes for historical estimation are added from demonstrated query shape/query plans rather than speculative indexing.

## 20. Authority and mutation behavior

Projection reads require explicit tenant/customer authority appropriate to the surface.

Configuration mutations follow normal Request Engine rules:

```text
tenant isolation
explicit capability
authoritative validation
optimistic concurrency where mutable
idempotency for externally retryable mutations
audit/outbox semantics where required
no partial durable effect on rejection
```

Knowing another tenant's identifiers never grants projection/history access.

## 21. Failure and uncertainty semantics

F4 distinguishes at least:

```text
known projection
partial projection
indeterminate projection
invalid configuration/input
unauthorized/opaque resource
```

Uncertainty is data, not an exception to be hidden.

Examples that may make a projection partial/indeterminate include:

```text
unknown workload duration
open interruption with unknown end
open ResourceActivity with unknown end
missing/invalid projection scope
no effective remaining availability
```

The API contract must return stable semantic failure/reason codes rather than force clients to parse prose.

## 22. Performance and consistency

Correctness precedes premature caching.

Initial implementation may calculate on demand, but must bound historical reads and same-day projection scope. Projection queries must avoid unbounded tenant history scans and must not materially interfere with transactional Booking/Queue/Delivery paths.

Any later batching/cache/materialization must preserve identical authority, deduplication, temporal and projection semantics.

## 23. Durable guarantees introduced by F4

F4 is expected to add durable guarantees equivalent to:

```text
INV-LIVE-CAPACITY-SEPARATION-001
  planning/commitment truth and live projection remain distinct

INV-LIVE-CAPACITY-PROJECTION-001
  projections derive from authoritative facts and never become commitment authority

INV-LIVE-CAPACITY-WORKLOAD-001
  configured, expected, actual and observed workload semantics remain distinguishable

INV-LIVE-CAPACITY-TEMPORAL-001
  projections respect effective operational intervals and one observation snapshot

INV-LIVE-CAPACITY-DEDUP-001
  one real workload is not double-counted across Reservation/Queue/ServiceSession

INV-LIVE-CAPACITY-PRIVACY-001
  staff/customer and cross-tenant projection boundaries remain least-privilege
```

Final guarantee IDs/text are reconciled with `docs/testing/current-guarantees.toml` during implementation.

## 24. Required evidence

F4 evidence must include real PostgreSQL 18 where database semantics matter and must be capable of failing under plausible defects.

Required proof areas include:

```text
planned capacity != live capacity
projection creates no CapacityClaim
projection does not mutate Reservation/Queue/Delivery facts
Reservation + Queue + ServiceSession deduplication
walk-in workload
future same-day Reservation workload
current-session remaining workload
interruption exclusion
open interruption/activity uncertainty
Resource/Location exceptions and discontinuous availability
historical estimator and deterministic fallback
observed history never mutates configured policy
unknown workload does not fabricate ETA
tenant opacity
customer privacy
DB-sourced observed_at and coherent snapshot
no unnecessary capacity locks
concurrent live mutations remain safe
configuration revision races
fresh bootstrap through F4 migration
upgrade from actual predecessor migration head
```

Race proofs assert winner/loser/final authoritative state when mutation concurrency is involved.

## 25. Acceptance journey

A representative E2E journey should build a real operational day with:

```text
Location effective hours
Resource effective availability + exception
one current ServiceSession
waiting entries with different expected workloads
one walk-in
one future same-day Reservation not yet checked in
historical completed sessions
```

The projection must derive queue starts, remaining workload, projected end-of-day and intake fit.

Then an open interruption is started and the projection must explicitly become partial/indeterminate where appropriate. After resume/completion it must recompute from the new facts without rewriting planning history or configured estimate policy.

## 26. Explicit non-goals / F5 boundary

F4 does not implement:

```text
automatic stop-intake
patient delay notifications
automatic schedule extension
automatic rescheduling
replacement-provider search
recovery workflows
communications
risk severity classification
ML/opaque duration prediction
clinical triage or medical priority scoring
multi-resource queue optimization
automatic Resource assignment
automatic estimate-policy mutation
```

F4 may expose facts such as `projected_end_at > effective_availability_end` or `fits=false`. F5 owns recovery/risk interpretation and communications.

## 27. Definition of Done

F4 is complete only when Request Engine can explain a projection from authoritative facts and prove that the projection itself did not become authority.

A successful result should be able to explain, conceptually:

```text
observed at: 14:05:12
remaining effective operational time: 2h25m
current + queued + planned remaining workload: 1h52m
projected end: 15:57
additional follow_up estimate: 20m
additional follow_up fits: true
estimate source: configured/history with explicit provenance
```

while durable evidence proves that Reservation planned time, CapacityClaims, schedule policy, Queue facts, ServiceSession history and configured workload policy were not silently rewritten.
