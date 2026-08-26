# Request Engine — module ownership map

> **Estado:** normativo para ownership del backend capability-first V3 y extensiones post-V3 actualmente activas.
>
> `docs/v3/02-pre-sql-contract.md` conserva el baseline V3. Las extensiones post-V3 lo modifican explícitamente mediante contratos posteriores. F3: `26` + `28`. F4 projection ownership: `29-live-capacity-projection-contract.md`.

## 1. Current summary

| Module | Status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, PartyContactPoint identity, Representation, tenant authority |
| `catalog` | baseline | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement, structured business info |
| `requests` | baseline | RequestDefinition/Version, durable Request, participants/correlation, generic extension payload/result boundary |
| `booking` | baseline + F1 | Resource, contextual Resource-at-Location supply, availability, CapacityHold/Claim, Reservation, AttendanceResponse, booking commitment/revalidation |
| `queue` | baseline + F3 | ServiceQueue/QueueEntry waiting/calling/no-show, check-in/walk-in, FIFO, expected workload, WaitlistEntry/SlotOpportunity/SlotOffer |
| `communications` | baseline | CommunicationTask/Delivery, communication policy refs, ReminderPlan/Acknowledgement |
| `discovery` | active post-V3 F2 | canonical service mapping, publication, cross-tenant discovery projection, opaque discovery handoff |
| `delivery` | active post-V3 F3 | ReservationAccess, ServiceSession, ServiceSessionInterruption, ResourceActivity and actual execution truth |
| `live_capacity` | active feature F4 | projection-scope/estimate policy and deterministic live-capacity/ETA/intake-evaluation semantics over published Booking/Queue/Delivery facts |
| `payments` | deferred | future pricing/payment/reconciliation domain |
| `dispatch` | deferred | future field-service dispatch/feasibility domain |
| `platform` | technical | DB, idempotency, outbox, scheduling mechanics, audit/events, observability, security plumbing |

Active modules depend across boundaries through contracts/composition, not by importing another module's adapters/application internals.

---

## 2. Tenancy

Owns Organization, Principal, Party, PartyContactPoint identity/normalization and Representation. It remains the hard tenant/authority boundary. A Party/contact point is not a CRM profile and identifiers never grant authority implicitly.

---

## 3. Catalog

Owns stable/versioned operational configuration including Location, Offering/OfferingVersion, ResourceCapability and OfferingResourceRequirement. Catalog describes what can be offered/configured; Booking resolves that configuration to concrete capacity.

---

## 4. Requests

Owns durable new business demand requiring later processing. A generic Request is not a universal mutation envelope for Booking, Queue, Delivery or Live Capacity.

---

## 5. Booking

Owns planning and local capacity truth:

```text
Resource
ResourceCapability assignment
ResourceLocationAssignment + contextual availability
BookingContextTerms / commercial commitment provenance
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Core rules:

```text
Resource = booking capacity serialization root
CapacityClaim = Hold/Reservation consumption truth
Reservation = planned commitment/history
```

F3 execution never rewrites Reservation/CapacityClaim because reality differed from plan. F4 consumes effective planning availability and same-day commitment facts but cannot become capacity authority.

Booking must publish a narrow F4 planning/read contract rather than permit `live_capacity` to import Booking DB/application internals.

---

## 6. Queue

### 6.1 ServiceQueue — waiting now

Owns ServiceQueue and QueueEntry, including subject join/status/leave, operator check-in/walk-in, arrival/admission facts, FIFO CallNext, called/no-show state, customer/staff queue projections and expected workload classification reference.

FIFO remains `(admitted_at, id)` and position remains derived.

Queue does not own actual service execution. Delivery writes QueueEntry serving/completed compatibility state atomically with ServiceSession transitions.

For F4, Queue publishes only the live waiting/called facts required for projection. `live_capacity` must not use a staff identity DTO as its internal capacity source merely because that DTO already exists.

### 6.2 Waitlist / released-slot recovery

Owns WaitlistEntry, SlotOpportunity and SlotOffer. Waitlist is future interest and never consumes capacity. Booking remains CapacityHold/Claim authority.

---

## 7. Communications

Owns transactional communication intent, delivery facts and reminder intent. Provider delivery state cannot directly mutate Booking, Queue, Delivery or Live Capacity truth.

---

## 8. Delivery — active post-V3 F3

### 8.1 ReservationAccess

Owns post-commit access artifacts required to execute a confirmed Reservation without making Booking provider-aware.

### 8.2 Live service execution

Owns:

```text
ServiceSession
ServiceSessionInterruption
ResourceActivity
actual Resource/Location used for execution
actual workload classification
actual execution timestamps
```

Boundary:

```text
Reservation     = planned commitment/capacity history -> booking
QueueEntry      = arrival/wait/call state             -> queue
ServiceSession  = what actually happened              -> delivery
```

Service start/complete compose Queue + Delivery in one PostgreSQL transaction. Pause/resume owns durable interruption history. ResourceActivity represents non-patient occupation and never fabricates a Party/Reservation/QueueEntry/ServiceSession.

For F4, Delivery may publish current Resource occupation and bounded completed-session history. F4 consumes those facts; it does not rewrite them or use historical observations to silently mutate Delivery/Queue policy.

---

## 9. Live Capacity — active F4 feature

`live_capacity` owns **projection semantics**, not capacity commitment or live execution truth.

Owns conceptually:

```text
LiveCapacityProjectionPolicy / projection scope
WorkloadEstimatePolicy
workload-estimate resolution/fallback/provenance
remaining-workload composition
projection over effective operational intervals
staff live-capacity projection
customer-safe self-relative ETA projection
read-only intake evaluation
projection uncertainty/blocking semantics
```

Initial scope is explicit:

```text
one ServiceQueue + one Resource + one Location
```

This is projection configuration, not automatic Resource assignment.

Consumes through published contracts/read surfaces:

```text
booking
  effective remaining Resource/Location availability
  same-day planning/commitment facts

queue
  waiting/called entries + expected workload

delivery
  current execution/occupation + bounded completed historical observations
```

Does **not** own:

```text
Reservation / CapacityClaim                 -> booking
ServiceQueue / QueueEntry                   -> queue
ServiceSession / interruption/activity      -> delivery
OperationalWorkloadClassification identity -> queue/F3 configuration
Resource schedule truth                     -> booking
Location schedule truth                     -> catalog/booking composition
```

Hard rules:

- projection is advisory and relative to a DB observation instant;
- scheduled capacity and live intake capacity remain distinct;
- the same workload is deduplicated across Reservation → QueueEntry → ServiceSession representations;
- observed durations may influence a projection but never silently mutate configured policy;
- ETA, queue position and remaining live capacity are not authoritative persisted counters;
- unknown/open-ended inputs produce explicit partial/indeterminate state rather than fabricated precision;
- initial F4 does not perform multi-resource queue optimization, automatic provider assignment, stop-intake, recovery or communications.

Typical target capabilities:

```text
live_capacity.read
live_capacity.evaluate_intake
live_capacity.customer_read
```

Configuration capability names are finalized with implementation but remain operator-only, revisioned/idempotent/audited under normal mutation rules.

---

## 10. Payments — deferred

Financial distinctions remain design knowledge, not current baseline dependencies. Re-entry requires explicit product policy.

---

## 11. Dispatch — deferred

Field-service destination, feasibility, routing and workforce planning remain outside current scope.

---

## 12. Discovery — active post-V3 F2

Discovery owns tenant-authorized published-supply search and opaque handoff semantics. It does not own Organization authority, Catalog truth, Booking capacity, Delivery execution or Live Capacity projection.

---

## 13. Platform

Platform is technical infrastructure, never a business catch-all: DB/transactions, idempotency, outbox, scheduling mechanics, audit/events, observability and security plumbing.

---

## 14. Cross-module transaction/read examples

### BookAppointment

Owner: Booking. Reservation and claims commit atomically. Advisory discovery/live-capacity state never substitutes for commitment-time validation.

### CheckIn / WalkIn

Owner: Queue. Reservation-backed check-in validates planning without changing it. Walk-in creates QueueEntry without Reservation.

### CallNext

Owner: Queue. ServiceQueue serializes deterministic FIFO selection.

### StartService / CompleteService

Composition: Queue + Delivery; execution owner: Delivery. Queue compatibility state and ServiceSession execution state commit together.

### Pause / Resume / ResourceActivity

Owner: Delivery.

### BuildLiveCapacityProjection

Owner: Live Capacity; **read-only composition**.

```text
one DB observation snapshot
-> published Booking planning/availability facts
-> published Queue live workload facts
-> published Delivery execution/occupation/history facts
-> deterministic deduplication + estimate resolution
-> project workload over remaining effective intervals
-> return advisory result/provenance
```

This read does not acquire Booking/Queue mutation locks merely to compute ETA and does not mutate source facts.

### EvaluateIntake

Owner: Live Capacity; read-only advisory evaluation of one specified additional workload against the current projection. It does not create QueueEntry/Reservation/CapacityClaim or stop intake.

---

## 15. Ownership change gate

Moving a concept between top-level modules or activating a deferred/new module requires updating:

- capability contracts or normative post-V3 contract/amendment;
- pre-SQL/current transaction contracts when invariants change;
- this ownership map;
- affected module READMEs/contracts/tests;
- DB/read/cmd mapping;
- an ADR when the decision is hard to reverse.

Never infer:

```text
table → domain entity → repository → endpoint
```

The north star remains:

```text
one public operational API
        ≠
one universal bounded context
```
