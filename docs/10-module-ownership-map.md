# Request Engine — module ownership map

> **Estado:** normativo para ownership del código Python durante la transición capability-first V3.
>
> El modelo relacional definitivo se rediseñará después de cerrar este ownership map. Este documento responde: **¿dónde pertenece un cambio?** No implica una entidad/repository/endpoint por tabla.

## 1. Summary

| Module | V3 status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, Representation, tenant authority |
| `catalog` | baseline | Offering/version, structured business/location/service information |
| `requests` | baseline | durable business-demand Request, participants/correlation, generic intake/extension boundary |
| `booking` | baseline | Resource, availability, local capacity, Hold, Reservation, attendance policy/state |
| `queue` | baseline | ServiceQueue/QueueEntry, Waitlist/WaitlistEntry, SlotOffer |
| `communications` | baseline | transactional communication intent/delivery, channel preference/endpoint contracts, ReminderPlan |
| `delivery` | deferred | advanced execution/ServiceSession/Fulfillment concepts retained only as V2 design knowledge |
| `payments` | deferred | pricing/payment/reconciliation concepts retained only as V2 design knowledge |
| `dispatch` | deferred | field-service dispatch/feasibility concepts retained only as V2 design knowledge |
| `platform` | technical | DB, idempotency, outbox, scheduling mechanics, audit/events, observability, security plumbing |

Baseline modules must not depend on deferred modules without a new accepted decision and concrete product use case.

---

## 2. Tenancy

Owns:

```text
Organization
Principal
Party
Representation
```

Responsibilities:

- hard tenant boundary;
- authenticated actor identity mapping;
- on-behalf-of authority/delegation/revocation semantics;
- tenant-scoped contact identity references needed by operational modules.

Participant role, public IDs, external correlations and possession of a conversation/thread never grant authority by implication.

Other modules consume intentionally small tenancy contracts.

---

## 3. Catalog

Owns:

```text
Organization/business profile projection inputs
Location
Offering
OfferingVersion
reusable offering configuration
opening/service-hour configuration where authoritative
```

The catalog provides structured operational truth for agents and applications. It is not a CMS/RAG platform.

Expected queries:

```text
GetBusinessInfo
SearchOfferings
GetOfferingDetails
GetLocations
```

Booking may consume offering/resource requirement configuration through catalog contracts. Runtime commitment state never mutates catalog history.

---

## 4. Requests

Owns `Request` as a durable envelope of **new business demand that requires later processing**.

Examples:

```text
request_quote
request_callback
request_service
submit_intake
```

By default it does **not** own cancellation/reschedule/attendance/queue mutation semantics merely because those actions originated in a chat.

Owns:

```text
Request
RequestType
RequestParticipant
ExternalCorrelation
OfferingSelection/RequestItem when required by demand scope
IntakeDefinition
IntakeSubmission
Request result/status semantics for extension workflows
```

Generic intake remains here while small. If intake develops independent lifecycle/policy/scale, it may become its own module through the new-module gate.

Initial commands/queries:

```text
CreateRequest
SubmitIntake
RecordRequestResult
CompleteRequest
CancelRequest
GetRequestStatus
```

n8n/provider callbacks into a Request must use semantic authenticated/idempotent commands owned here, never generic status mutation.

`OutcomeScope` and universal Workflow ownership are removed from the V3 baseline.

---

## 5. Booking

Owns local reservation authority:

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityClaim
CapacityHold
Reservation
AttendanceResponse / reservation-attendance policy
```

Initial capacity models:

```text
exclusive
units
```

Initial commands/queries:

```text
FindAppointmentSlots
AcquireCapacityHold (internal/public only when product needs it)
BookAppointment
CancelReservation
RescheduleReservation
GetReservationStatus
ConfirmAttendance
DeclineAttendance
ChangeResourceAvailability
ChangeScheduleException
```

### 5.1 Reschedule authority

Booking owns the self-overlap-safe atomic reschedule transaction:

```text
lock Reservation
lock old/new capacity sources in canonical order
validate final state excluding claims replaced by this operation
replace claims atomically
commit
```

A replacement Hold may be used for non-overlapping flows when useful, but must not be a universal prerequisite that conflicts with the Reservation being replaced.

### 5.2 Capacity simplification

`ResourceAllocation`, CapacityPool, external commitments and PlanningRevision are not baseline promises. Before V3 SQL baseline, determine whether Reservation consumption can be represented directly by `CapacityClaim` without duplicate 1:1 state.

### 5.3 Attendance

Booking owns the authoritative relationship between Reservation and attendance response because downstream capacity consequences depend on booking policy.

Do not conflate:

```text
Reservation confirmed
with
attendance accepted
```

No-response consequences require explicit policy.

---

## 6. Queue

The `queue` module owns two distinct capabilities that share customer-flow language but not semantics.

### 6.1 ServiceQueue

Represents subjects waiting to be served now.

Owns:

```text
ServiceQueue
QueueEntry
```

Initial states:

```text
waiting
called
serving
completed
cancelled
no_show
```

Initial policy is deterministic FIFO among eligible entries.

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

### 6.2 Waitlist

Represents subjects willing to consume future capacity if it becomes available.

Owns:

```text
WaitlistEntry
SlotOffer
```

Commands/queries:

```text
JoinWaitlist
LeaveWaitlist
CreateSlotOffer (normally event-driven/internal)
AcceptSlotOffer
DeclineSlotOffer
ExpireSlotOffer
GetWaitlistStatus
```

WaitlistEntry does not consume booking capacity by itself.

When a SlotOffer must reserve capacity exclusively during its response window, queue coordinates with booking to create a short CapacityHold. Otherwise `AcceptSlotOffer` simply revalidates capacity through booking.

Selection policy starts simple and deterministic; no optimization engine V1.

---

## 7. Communications

Owns transactional communication intent and communication-specific business policy, not external provider transport truth alone.

Owns:

```text
CommunicationTask
CommunicationDelivery
CommunicationTemplate or TemplateRef/version
CommunicationPreference
ContactEndpoint contract/reference
ReminderPlan
ReminderAcknowledgement when required
```

Initial purposes include:

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

Initial commands/queries:

```text
CreateCommunicationTask
RecordDeliveryAttempt
RecordDeliveryResult
RecordProviderDeliveryCallback
CreateReminderPlan
UpdateReminderPlan
CancelReminderPlan
AcknowledgeReminder
```

Communication provider I/O happens after originating business commit.

The module can define fallback-channel policy, but does not become a marketing journey/campaign platform.

Medication reminders execute an authorized plan; the module does not infer clinical dosage/treatment decisions.

---

## 8. Delivery — deferred

The V2 `delivery` module previously owned admission/queue, ServiceSession, Fulfillment and corrections.

V3 disposition:

- Queue/Waitlist move conceptually to `queue`.
- ServiceSession/Fulfillment/Correction are deferred until a concrete execution/outcome proof requires them.
- No baseline module may rely on these deferred concepts to complete appointment, queue, communication or generic Request verticals.

Do not delete useful V2 design history until the clean V3 baseline is complete; do not treat it as active architecture either.

---

## 9. Payments — deferred

V2 financial concepts remain useful future design material, but payments do not block the first baseline.

Re-entry requires concrete product semantics such as:

```text
pay/deposit before confirm
reserve now / pay before deadline
no payment prerequisite
```

When reactivated, financial truth remains separate from booking/fulfillment truth and provider observations remain distinct from business obligations.

---

## 10. Dispatch — deferred

Dispatch/field-service destination and feasibility planning are not baseline capabilities.

Do not preserve PlanningRevision, external feasibility or routing complexity merely to keep the V2 schema shape. Reactivate only for a real field-service vertical.

---

## 11. Platform

Platform is technical infrastructure, never a business catch-all.

### `platform/db`

- engine/session factories;
- transaction plumbing;
- PostgreSQL error translation;
- technical DB types.

### `platform/idempotency`

- idempotency acquisition/completion mechanics;
- request-hash/command result replay infrastructure.

Business meaning of a command remains in its module.

### `platform/outbox`

- outbox claim/delivery leases;
- fencing;
- bounded retry/dead-letter plumbing;
- generic publisher runtime.

Business event payload production remains with emitting modules.

### `platform/scheduling`

Owns generic durable scheduling mechanics:

```text
ScheduledAction persistence contract
clock abstraction
claim batching
lease/fencing
retry/dead-letter
manual replay plumbing
scheduling lag telemetry
```

It does not decide why an appointment reminder, SlotOffer expiry or medication reminder exists.

### `platform/audit` / `platform/events`

Cross-cutting append/serialization mechanics only; business event vocabulary belongs to emitting modules.

### `platform/observability`

Tracing/metrics/logging infrastructure. Audit is not telemetry.

### `platform/security`

Authentication/Principal plumbing and common technical enforcement. Representation/business authority remains tenancy/application policy.

---

## 12. Cross-module transaction/event examples

### BookAppointment

Owner: `booking`.

May read catalog/request context through contracts. Local capacity and Reservation changes commit atomically inside booking's authoritative transaction.

After commit, an outbox fact may cause `communications` to create confirmation/reminder tasks.

### RescheduleReservation

Owner: `booking`.

Replaces capacity atomically. After commit, communication policy may cancel obsolete scheduled reminders and create new ones.

### ConfirmAttendance

Owner: `booking` for authoritative attendance/reservation consequence. Communications/provider adapter may supply the inbound response through a booking contract.

### JoinQueue

Owner: `queue`.

Does not automatically create a Reservation unless a documented capability explicitly coordinates both.

### AcceptSlotOffer

Owner: `queue` for offer lifecycle, coordinating booking contract for capacity/Reservation creation. If capacity correctness requires one local transaction across both modules, keep it one PostgreSQL transaction rather than using asynchronous events for aesthetic separation.

### Create appointment reminder

Booking emits reservation fact after commit. Communications owns communication intent. `platform/scheduling` owns when/how the future action is safely claimed, not the business policy that requested it.

### Generic quote Request via n8n

Owner: `requests`.

```text
CreateRequest
→ commit/outbox
→ n8n integration
→ authenticated idempotent RecordRequestResult/CompleteRequest
```

---

## 13. Ownership change gate

Moving a concept between top-level modules or activating a deferred module requires updating:

- this map;
- affected module READMEs;
- architecture/import tests;
- DB/read/cmd ownership mapping;
- an ADR when material or hard to reverse.

Never infer automatically:

```text
table → domain entity → repository → endpoint
```

Some rows exist only as serialization identities, relational links, append facts or integrity mechanics.

The core V3 rule remains:

```text
one public operational API
        ≠
one universal bounded context
```
