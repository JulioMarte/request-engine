# Request Engine — module ownership map

> **Estado:** normativo para ownership del backend capability-first V3.
>
> `docs/v3/02-pre-sql-contract.md` define cardinalidades, serialization roots, transacciones e invariantes. ADR 0009 refines the original V3 boundary by moving future-capacity waitlist recovery from `queue` to `booking`.

## 1. Summary

| Module | V3 status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, PartyContactPoint identity, Representation, tenant authority |
| `catalog` | baseline | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement, structured business info |
| `requests` | baseline | RequestDefinition/Version, durable Request, participants/correlation, generic extension payload/result boundary |
| `booking` | baseline | Resource, capability assignment, availability, CapacityHold/Claim, Reservation, AttendanceResponse, WaitlistEntry, SlotOpportunity, SlotOffer |
| `queue` | baseline | live ServiceQueue/QueueEntry only |
| `communications` | baseline | CommunicationTask/Delivery, communication policy refs, ReminderPlan/Acknowledgement |
| `delivery` | deferred | future ServiceSession/Fulfillment/outcome execution domain |
| `payments` | deferred | future pricing/payment/reconciliation domain |
| `dispatch` | deferred | future field-service dispatch/feasibility domain |
| `platform` | technical | DB, idempotency, outbox, scheduling mechanics, audit/events, observability, security plumbing |

Baseline modules must not depend on deferred modules without a concrete product use case and accepted architecture change.

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
- minimal tenant-scoped contact identity needed by operational modules.

A Party/contact point is not a CRM profile. Participant role, phone/email ownership, public IDs and channel correlation never grant authority implicitly.

`communications` owns channel delivery/purpose/preference policy; `tenancy` owns the Party/contact identity being addressed.

---

## 3. Catalog

Owns stable/versioned operational configuration:

```text
Location
Offering
OfferingVersion
ResourceCapability
OfferingResourceRequirement
structured business/public-hours information where authoritative
```

`OfferingVersion` is immutable once referenced by authoritative state.

A baseline `OfferingResourceRequirement` is an immutable child/configuration of OfferingVersion:

```text
one mandatory ResourceCapability
+ units quantity
```

Multiple rows are ANDed. There is no baseline reusable requirement template, OR/k-of-n expression graph, CapacityPool or late-binding optimizer.

Expected queries:

```text
GetBusinessInfo
SearchOfferings
GetOfferingDetails
GetLocations
```

Booking consumes catalog configuration through stable references/read surfaces and resolves requirements to concrete Resources. Runtime claims never mutate catalog history.

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

Examples:

```text
request_quote
request_callback
request_service
website_contact
```

`RequestDefinitionVersion` supplies the exact versioned generic input/result contract. Validated extensibility payload/result may use JSONB here.

No baseline:

```text
RequestType as mutation-command taxonomy
IntakeDefinition / IntakeSubmission parallel lifecycle
OfferingSelection / RequestItem generic graph
OutcomeScope
universal Workflow
```

A form representing new demand submits a Request directly against a RequestDefinitionVersion. Cancel/reschedule/attendance/queue mutations remain commands of their native domains.

Commands/queries:

```text
CreateRequest / requests.submit
RecordRequestResult
CompleteRequest
CancelRequest
GetRequestStatus
```

n8n/provider callbacks use authenticated tenant-bound idempotent semantic commands, never generic status mutation.

---

## 5. Booking

Booking owns **local appointment capacity, reservations and future appointment-capacity recovery**.

Core ownership:

```text
Resource
Resource ↔ ResourceCapability assignment
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse history/current projection
```

Future-capacity recovery ownership (ADR 0009):

```text
WaitlistEntry
SlotOpportunity
SlotOffer
released-slot candidate selection policy
accept/decline/expire offer orchestration
```

Initial capacity models:

```text
exclusive
units
```

Closed baseline decisions:

```text
1 Reservation = 1 OfferingVersion + 1 subject Party + 1 interval
Resource = capacity serialization/lock root
CapacityClaim = common Hold/Reservation consumption truth
WaitlistEntry = future interest; never capacity consumption
SlotOpportunity = recovery coordination root; never capacity authority
SlotOffer = one candidate offer backed by a short CapacityHold
```

No baseline:

```text
ReservationItem
CapacityAuthority one-to-one indirection
ResourceAllocation duplicate claim truth
CapacityPool
PlanningRevision
external capacity commitments
field-service feasibility
```

If future execution assignment becomes independently mutable from capacity consumption, introduce a proven `ResourceAssignment` then.

Appointment commands/queries:

```text
FindAppointmentSlots
AcquireCapacityHold
BookAppointment
ConfirmCapacityHold
CancelReservation
RescheduleReservation
GetReservationStatus
ConfirmAttendance
DeclineAttendance
ChangeResourceAvailability
ChangeScheduleException
```

Waitlist/recovery commands/queries:

```text
JoinWaitlist
LeaveWaitlist
GetWaitlistStatus
CreateSlotOpportunity           # internal/event-driven
OfferNextWaitlistCandidate      # internal
AcceptSlotOffer
DeclineSlotOffer
ExpireSlotOffer                 # ScheduledAction target
```

### Why waitlist belongs here

The strongest invariants are capacity invariants, not live-queue invariants. `AcceptSlotOffer` must atomically validate/promote booking-owned Hold/claims into a Reservation while closing the offer/opportunity. Keeping these concepts in `booking` avoids leaking transaction/session mechanics through a cross-module contract or allowing queue to mutate booking-owned state.

Public capabilities remain `waitlist.*`; public API taxonomy does not dictate Python module ownership.

Booking owns self-overlap-safe reschedule according to `docs/v3/02-pre-sql-contract.md`. Attendance confirmation remains distinct from Reservation confirmation; no-response/decline consequences require explicit versioned booking policy.

---

## 6. Queue

`queue` owns the **live service queue only**:

```text
ServiceQueue
QueueEntry
```

It represents subjects waiting to be served now. Baseline `CallNext` is FIFO by `(admitted_at, id)` under ServiceQueue serialization.

Commands/queries:

```text
JoinQueue
LeaveQueue
CallNext
StartServing
CompleteQueueEntry
MarkNoShow
GetQueueStatus
```

Queue position is derived, not mutable authoritative counter state.

Queue does not own appointment waitlists merely because candidate selection happens to be FIFO. Future-capacity interest and released-slot recovery belong to booking under ADR 0009.

---

## 7. Communications

Owns transactional communication intent, delivery facts and recurring reminder business intent:

```text
CommunicationTask
CommunicationDelivery
communication purpose/channel policy
stable template/content key + version/snapshot contract
ReminderPlan
ReminderAcknowledgement when required
```

No mandatory tenant-editable CommunicationTemplate entity exists in baseline; add one only when product functionality requires template lifecycle.

Typical purposes:

```text
appointment_confirmation
appointment_reminder
attendance_confirmation_request
reservation_changed
reservation_cancelled
queue_turn_approaching
slot_offer_available
request_completed
medication_reminder
```

Commands:

```text
CreateCommunicationTask
RecordDeliveryAttempt/Result
RecordProviderDeliveryCallback
CreateReminderPlan
UpdateReminderPlan
CancelReminderPlan
AcknowledgeReminder
```

Provider I/O happens after the originating business transaction commits. Provider delivery state cannot directly mutate booking/queue/request truth. An inbound response with business meaning invokes the owning semantic command.

Medication reminders execute an authorized plan; communications does not infer dosage/treatment decisions.

---

## 8. Delivery — deferred

Future `ServiceSession`, Fulfillment/outcome evidence and corrections remain deferred until a real execution vertical needs independent policy/lifecycle. No baseline module may depend on delivery to complete V3 proof flows.

---

## 9. Payments — deferred

V2 financial distinctions remain design knowledge, not baseline dependencies.

Re-entry requires concrete product policies such as:

```text
pay/deposit before confirm
reserve now / pay before deadline
no payment prerequisite
```

Financial truth remains separate from booking/execution truth when reactivated.

---

## 10. Dispatch — deferred

Field-service destination, feasibility, planning and routing are outside baseline. `PlanningRevision` and related V2 concepts are not reproduced in clean V3 SQL unless a field-service capability proves the need.

---

## 11. Platform

Platform is technical infrastructure, never a business catch-all.

### `platform/db`

```text
engine/session factories
transaction plumbing
PostgreSQL technical error translation
runtime tenant-context plumbing
```

### `platform/idempotency`

```text
idempotency acquire/complete/replay mechanics
canonical command fingerprinting support
```

Business command semantics remain module-owned.

### `platform/outbox`

```text
outbox persistence/claim
lease/fencing
bounded retry/dead-letter/manual replay plumbing
publisher runtime
```

Event vocabulary/payload production remains emitting-module-owned.

### `platform/scheduling`

```text
ScheduledAction persistence contract
clock abstraction
claim batching
lease/fencing
bounded retry/dead-letter/manual replay
scheduling lag telemetry
```

Platform does not decide why a reminder, SlotOffer expiry or deadline exists.

### `platform/audit` / `platform/events`

Append/serialization mechanics only. Do not grow a universal business event bus abstraction before needed.

### `platform/observability`

Tracing/metrics/logging. Audit is not telemetry.

### `platform/security`

Authentication/runtime role/RLS-context plumbing. Representation/business authority remains tenancy/application policy.

---

## 12. Transaction/event examples

### BookAppointment / RescheduleReservation

Owner: `booking`. Resource/Reservation/claims commit atomically. Communications are consequences after commit.

### ConfirmAttendance

Owner: `booking`. Communications/provider adapters may route an inbound response into this command but never mutate Reservation directly.

### JoinQueue / CallNext

Owner: `queue`. Queue completion means only that live queue service ended; it does not imply universal Fulfillment or Request completion.

### Reservation cancellation → standby recovery

```text
booking cancel commit
→ outbox reservation.cancelled
→ booking create/get SlotOpportunity
→ booking selects eligible WaitlistEntry
→ booking creates short CapacityHold
→ booking creates SlotOffer
→ commit
→ communications notification
```

Only booking owns capacity and the standby coordination state.

### AcceptSlotOffer

Owner: `booking`.

```text
SlotOpportunity
→ SlotOffer
→ CapacityHold
→ Resources sorted
→ promote held claims / create Reservation
→ fulfill WaitlistEntry
→ mark offer accepted + opportunity filled
→ audit/outbox
→ commit
```

This is one local transaction without a cross-module Python UnitOfWork surface.

### Appointment communication

Booking emits durable fact after commit. Communications owns task/reminder policy. `platform/scheduling` owns lease/clock/retry mechanics only.

### Generic quote Request via n8n

```text
requests.submit
→ commit/outbox
→ n8n
→ authenticated idempotent requests.record_result
→ requests.complete
```

---

## 13. Cross-module database rule

In the shared PostgreSQL modular monolith, distinguish three surfaces:

1. **tenant-safe relational reference** — an FK/correlation may cross conceptual owners when the relationship itself is a documented invariant;
2. **semantic cross-module call** — Python uses the target module's supported `contracts` surface and requires an explicitly approved dependency edge;
3. **direct mutation of another owner's authoritative rows** — forbidden unless an explicit architecture decision defines a shared atomic protocol.

Do not manufacture Python services simply to replace a stronger FK. Conversely, do not use “shared database” as permission for arbitrary cross-owner mutation.

---

## 14. Ownership change gate

Moving a concept between top-level modules or activating a deferred module requires updating:

- `docs/v3/01-capability-contracts.md` when external semantics change;
- `docs/v3/02-pre-sql-contract.md` when cardinality/transaction/invariants change;
- this map;
- `docs/v3/capability-manifest.toml`;
- affected module READMEs/contracts/tests;
- DB/read/cmd mapping;
- an ADR when hard to reverse.

Never infer:

```text
table → domain entity → repository → endpoint
```

The V3 north star remains:

```text
one public operational API
        ≠
one universal bounded context
```
