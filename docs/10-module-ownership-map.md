# Request Engine — module ownership map

> **Estado:** normativo para ownership del backend capability-first V3 y extensiones post-V3
> actualmente activas.
>
> `docs/v3/02-pre-sql-contract.md` conserva el baseline V3. Las extensiones post-V3 no reescriben
> esa provenance: la modifican explícitamente mediante contratos posteriores. Para F3 ver
> `docs/v3/26-live-service-operations-contract.md` y
> `docs/v3/28-live-service-operations-integration-amendment.md`.

## 1. Current summary

| Module | Status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, PartyContactPoint identity, Representation, tenant authority |
| `catalog` | baseline | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement, structured business info |
| `requests` | baseline | RequestDefinition/Version, durable Request, participants/correlation, generic extension payload/result boundary |
| `booking` | baseline + F1 | Resource, contextual Resource-at-Location supply, availability, CapacityHold/Claim, Reservation, AttendanceResponse, booking commitment/revalidation |
| `queue` | baseline + F3 | ServiceQueue/QueueEntry waiting/calling/no-show, check-in/walk-in, FIFO, WaitlistEntry/SlotOpportunity/SlotOffer |
| `communications` | baseline | CommunicationTask/Delivery, communication policy refs, ReminderPlan/Acknowledgement |
| `discovery` | active post-V3 F2 | canonical service mapping, publication, cross-tenant discovery projection, opaque discovery handoff |
| `delivery` | active post-V3 | ReservationAccess plus F3 ServiceSession, ServiceSessionInterruption, ResourceActivity and actual execution truth |
| `payments` | deferred | future pricing/payment/reconciliation domain |
| `dispatch` | deferred | future field-service dispatch/feasibility domain |
| `platform` | technical | DB, idempotency, outbox, scheduling mechanics, audit/events, observability, security plumbing |

Active modules depend across boundaries through contracts/composition, not by importing another
module's adapters/application internals.

---

## 2. Tenancy

Owns:

```text
Organization
Principal
Party
PartyContactPoint identity/normalization
Representation
```

Responsibilities:

- hard Organization boundary;
- authenticated actor identity mapping;
- on-behalf-of authority/delegation/revocation;
- minimal tenant-scoped contact identity required by operational modules.

A Party/contact point is not a CRM profile. Participant role, phone/email ownership, public IDs and
channel correlation never grant authority implicitly.

---

## 3. Catalog

Owns stable/versioned operational configuration:

```text
Location
Offering
OfferingVersion
ResourceCapability
OfferingResourceRequirement
structured public/business configuration where authoritative
```

`OfferingVersion` is immutable once referenced by authoritative state.

Catalog describes what can be offered/configured. Booking resolves that configuration to concrete
capacity. Delivery consumes immutable delivery/access configuration but does not own OfferingVersion.

---

## 4. Requests

Owns durable **new business demand requiring later processing**:

```text
RequestDefinition
RequestDefinitionVersion
Request
RequestParticipant
ExternalCorrelation
```

Typical commands/queries:

```text
requests.submit
requests.get
requests.record_result
requests.complete
requests.cancel
```

A generic Request is not a universal mutation envelope for booking, queue or delivery. Native domain
commands remain native even when initiated by an LLM, bot, n8n workflow or integration.

---

## 5. Booking

Owns planning and local capacity truth:

```text
Resource
ResourceCapability assignment
ResourceLocationAssignment + contextual availability (F1)
BookingContextTerms / commercial commitment provenance (F1)
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Current invariants:

```text
1 Reservation = 1 OfferingVersion + 1 subject Party + 1 interval
Resource = booking capacity serialization root
CapacityClaim = Hold/Reservation consumption truth
Discovery never becomes capacity authority
```

Booking records what was committed. F3 actual execution never rewrites Reservation interval,
OfferingVersion or CapacityClaim merely because reality differed from the plan.

F2 may pass opaque discovery provenance into Booking, but Booking performs authoritative revalidation
and commitment.

Typical capabilities:

```text
appointments.find_slots
appointments.hold
appointments.book
appointments.cancel
appointments.reschedule
appointments.confirm_attendance
appointments.get
```

If execution needs a Resource different from the booked Resource, that is an execution fact owned by
Delivery; it does not silently retarget Booking capacity history.

---

## 6. Queue

Queue owns two distinct concerns.

### 6.1 ServiceQueue — waiting now

Owns:

```text
ServiceQueue
QueueEntry
```

Current Queue responsibilities:

```text
subject-facing join/status/leave
operator check-in / walk-in
arrival/admission facts
FIFO CallNext
CALLED state
MarkNoShow
customer-safe queue projection
staff live-queue projection
expected workload classification reference on QueueEntry
```

FIFO remains:

```text
(admitted_at, id)
```

F3 current state machine:

```text
WAITING --CallNext--> CALLED --service_session.start--> SERVING --service_session.complete--> COMPLETED
   |                    |
   +--cancel------------+--queue.mark_no_show--> NO_SHOW
```

Queue does **not** own actual service execution. Delivery's StartService/CompleteService write the
QueueEntry `serving/completed` states and compatibility timestamps atomically with ServiceSession.
Those mirrored Queue fields do not create a second execution authority.

Reservation-backed check-in references planning without mutating it. Walk-in uses
`reservation_id = NULL`; Queue must not fabricate a Reservation.

### 6.2 Waitlist / released-slot recovery

Owns:

```text
WaitlistEntry
SlotOpportunity
SlotOffer
```

Waitlist represents future interest and never consumes capacity. A SlotOffer is backed by a short
Booking CapacityHold before notification. Queue coordinates acceptance/decline/expiry while Booking
remains capacity authority.

Do not collapse ServiceQueue and Waitlist into a generic priority/scoring engine.

---

## 7. Communications

Owns transactional communication intent, delivery facts and recurring reminder intent:

```text
CommunicationTask
CommunicationDelivery
purpose/channel policy
stable template/content key + version/snapshot contract
ReminderPlan
ReminderAcknowledgement when required
```

Provider delivery state cannot directly mutate Booking, Queue, Request or Delivery truth. Inbound
responses route to supported semantic commands.

Provider I/O happens outside the originating authoritative business transaction.

---

## 8. Delivery — active post-V3

Delivery now owns **two separate subdomains**.

### 8.1 ReservationAccess

Owns post-commit access artifacts required to execute a confirmed Reservation without making Booking
provider-aware:

```text
ReservationAccess
OfferingVersion.delivery_policy interpretation
provider-neutral access materialization/revocation
provider reconciliation identity
```

Booking owns Reservation/capacity. Delivery owns access evidence and provider reconciliation.

### 8.2 F3 live service execution

Owns:

```text
ServiceSession
ServiceSessionInterruption
ResourceActivity
actual Resource/Location used for execution
actual workload classification on ServiceSession
actual execution timestamps
```

F3 boundary:

```text
Reservation  = planned commitment / capacity history        -> booking
QueueEntry   = arrival, waiting, call/no-show state          -> queue
ServiceSession = what actually happened                      -> delivery
```

Normative rule:

> Booking records what was committed, Queue records who is waiting/called, and Delivery records
> what actually happened. No layer rewrites another layer merely to make history look consistent.

`service_session.start` and `service_session.complete` are cross-module compositions executed inside
one PostgreSQL transaction so Queue compatibility state and Delivery execution state commit together
or not at all.

Pause/resume owns durable interruption history. QueueEntry remains `SERVING` while paused.

ResourceActivity represents non-patient occupation such as break/emergency/administrative time. It
never creates a fake Party, Reservation, QueueEntry or ServiceSession.

Current resource occupation policy:

- at most one active/paused ServiceSession per Resource;
- at most one open ResourceActivity per Resource;
- they conflict in both directions;
- Resource serializes the competing starts;
- parallel/group service requires a future explicit policy.

Current capabilities:

```text
service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read
resource_activity.start
resource_activity.end
```

Delivery remains intentionally narrower than a universal Fulfillment domain. F3 does not activate
OutcomeScope, clinical records, generic workflow or payment accounting.

---

## 9. Payments — deferred

Financial distinctions remain design knowledge, not current baseline dependencies.

Re-entry requires explicit product policies such as deposits, deadlines, capture/refund and
reconciliation. Financial truth must remain separate from booking and execution truth.

---

## 10. Dispatch — deferred

Field-service destination, feasibility, routing and workforce planning remain outside current scope.
`PlanningRevision` and related V2 concepts are not reproduced without a concrete field-service
capability.

---

## 11. Discovery — active post-V3 F2

Discovery owns the minimum semantics required to expose tenant-authorized supply across
Organizations:

```text
ServiceClassification mapping semantics
OfferingServiceClassification provenance
DiscoveryPublication lifecycle
published cross-tenant candidate projection
objective geospatial filter/order contract
opaque discoopt_v1 handoff issuance state
```

It does not own:

```text
Organization / Representation authority       -> tenancy
Location / Offering / OfferingVersion truth   -> catalog
Resource / schedule / contextual terms        -> booking
Reservation / CapacityClaim                   -> booking
live execution / ServiceSession               -> delivery
GlobalIdentity / SharedCapacityIdentity       -> private shared-capacity machinery
```

Public Discovery uses its dedicated restricted runtime. Booking remains the commitment boundary.

---

## 12. Platform

Platform is technical infrastructure, never a business catch-all.

### `platform/db`

Engine/session factories, transaction plumbing, PostgreSQL technical error translation and runtime
tenant context.

### `platform/idempotency`

Idempotency acquire/complete/replay mechanics and canonical command fingerprinting. Business command
semantics remain module-owned.

### `platform/outbox`

Outbox persistence/claim, lease/fencing, retry/dead-letter/manual replay and publisher mechanics.
Event vocabulary remains emitting-module-owned.

### `platform/scheduling`

ScheduledAction persistence, clock, claim batching, lease/fencing and retry mechanics. Platform does
not decide why a reminder, SlotOffer expiry or business deadline exists.

### `platform/audit` / `platform/events`

Append/serialization mechanics. Audit is durable business provenance, not telemetry.

### `platform/observability`

Tracing, metrics and logs. Observability never replaces audit.

### `platform/security`

Authentication/runtime role/RLS-context plumbing. Representation/business authority remains
Tenancy/application policy.

---

## 13. Cross-module transaction examples

### BookAppointment

Owner: Booking. Reservation and claims commit atomically. Discovery provenance, when present, is
revalidated as a prerequisite, not promoted to capacity authority.

### RescheduleReservation

Owner: Booking. Old/new claims replace atomically. Downstream communications/access reconciliation
occurs after commit through durable facts.

### CheckIn / WalkIn

Owner: Queue. Reservation-backed check-in validates planning without changing it. Walk-in creates
QueueEntry without Reservation.

### CallNext

Owner: Queue. ServiceQueue serializes deterministic FIFO selection.

### StartService

Composition: Queue + Delivery; execution owner: Delivery.

```text
lock ServiceQueue
-> lock QueueEntry
-> lock Resource
-> validate execution assignment/occupation
-> create ServiceSession
-> QueueEntry serving compatibility mirror
-> audit/outbox/idempotency
-> one commit
```

### Pause / Resume

Owner: Delivery. ServiceSession + ServiceSessionInterruption commit atomically; Queue remains serving.

### CompleteService

Composition: Queue + Delivery; execution owner: Delivery. Session and Queue completion share the same
DB-authoritative completion timestamp and commit together.

### MarkNoShow

Owner: Queue. Only a `called` QueueEntry with no ServiceSession may become `no_show`.

### ResourceActivity

Owner: Delivery. Competes with live ServiceSession through the Resource serialization root.

### Reservation cancellation → standby recovery

```text
booking cancel commit
→ reservation.cancelled outbox
→ queue create/get SlotOpportunity
→ queue selects candidate
→ booking CapacityHold
→ SlotOffer
→ communications notification
```

Only Booking claims capacity.

---

## 14. Ownership change gate

Moving a concept between top-level modules or activating a deferred module requires updating:

- capability contracts or a normative post-V3 amendment;
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
