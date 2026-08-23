# Request Engine — module ownership map

> **Estado:** normativo para ownership del backend capability-first V3 y extensiones post-V3 aceptadas/activas.
>
> `docs/v3/02-pre-sql-contract.md` define las cardinalidades, serialization roots, transacciones e invariantes del baseline; los contratos post-V3 documentan extensiones explícitas sin borrar la provenance anterior.

## 1. Summary

| Module | Status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, PartyContactPoint identity, Representation, tenant authority |
| `catalog` | baseline | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement, structured business info |
| `requests` | baseline | RequestDefinition/Version, durable Request, participants/correlation, generic extension payload/result boundary |
| `booking` | baseline + F1 | Resource, contextual Resource-at-Location supply, availability, CapacityHold/Claim, Reservation, AttendanceResponse, booking commitment/revalidation |
| `queue` | baseline | ServiceQueue/QueueEntry, WaitlistEntry, SlotOpportunity, SlotOffer |
| `communications` | baseline | CommunicationTask/Delivery, communication policy refs, ReminderPlan/Acknowledgement |
| `discovery` | active post-V3 F2 | canonical service mapping, tenant discovery publication, cross-tenant published-supply projection, opaque discovery handoff |
| `delivery` | deferred | future ServiceSession/Fulfillment/outcome execution domain |
| `payments` | deferred | future pricing/payment/reconciliation domain |
| `dispatch` | deferred | future field-service dispatch/feasibility domain |
| `platform` | technical | DB, idempotency, outbox, scheduling mechanics, audit/events, observability, security plumbing |

Baseline modules must not depend on deferred modules without a concrete product use case and accepted architecture change. Active post-V3 modules obey the same contracts-only dependency rule.

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

Multiple rows are ANDed.

There is no baseline reusable `ResourceRequirementTemplate`, OR/k-of-n expression graph, CapacityPool or late-binding optimizer.

Expected Queries:

```text
GetBusinessInfo
SearchOfferings
GetOfferingDetails
GetLocations
```

Booking consumes catalog requirement/version contracts and resolves them to concrete Resources. Runtime claims never mutate catalog history.

---

## 4. Requests

Owns durable **new business demand requiring later processing**.

Owns:

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

### Explicit non-ownership

No baseline:

```text
RequestType as mutation-command taxonomy
IntakeDefinition / IntakeSubmission parallel lifecycle
OfferingSelection / RequestItem generic graph
OutcomeScope
universal Workflow
```

A form representing new demand submits a Request directly against a RequestDefinitionVersion. Draft/partial-form lifecycle can become a separate capability later if proven.

Cancel/reschedule/attendance/queue mutations belong to their native domains by default, regardless of whether an LLM/chat initiated them.

Commands/Queries:

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

Owns local reservation/capacity truth:

```text
Resource
Resource ↔ ResourceCapability assignment
ResourceLocationAssignment + contextual availability (F1)
BookingContextTerms + immutable commercial commitment provenance (F1)
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse history/current projection
```

Initial capacity models:

```text
exclusive
units
```

### Closed baseline/current decisions

```text
1 Reservation = 1 OfferingVersion + 1 subject Party + 1 interval
Resource = capacity serialization/lock root
CapacityClaim = common Hold/Reservation consumption truth
Discovery never becomes capacity authority
```

F2 may pass an opaque discovery handoff into Booking, but Booking remains the authoritative revalidation and commitment boundary. The handoff constrains/revalidates publication provenance; it does not create another capacity or pricing ledger.

No baseline/current:

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

Commands/Queries:

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

Booking owns self-overlap-safe reschedule according to `docs/v3/02-pre-sql-contract.md`.

Attendance confirmation is distinct from Reservation confirmation. No-response/decline capacity consequences require explicit versioned booking policy.

---

## 6. Queue

Owns two distinct capabilities.

### 6.1 ServiceQueue

```text
ServiceQueue
QueueEntry
```

Represents subjects waiting to be served now. Baseline `CallNext` is FIFO by `(admitted_at, id)` under ServiceQueue serialization.

Commands/Queries:

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

### 6.2 Waitlist/released-slot recovery

Owns:

```text
WaitlistEntry
SlotOpportunity
SlotOffer
```

`WaitlistEntry` represents future interest and never consumes capacity.

`SlotOpportunity` is the stable coordination root for one released appointment opportunity and sequential candidate chain. It does not prove availability.

Baseline `SlotOffer` is backed by a short booking CapacityHold before notification. Only one active offered SlotOffer exists per Opportunity.

Candidate selection is FIFO among candidates eligible for the concrete Opportunity.

Commands/Queries:

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

`AcceptSlotOffer` is queue-owned orchestration with booking through supported contracts and one local transaction where atomicity requires it.

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

Provider I/O happens after the originating business transaction commits.

Provider delivery state cannot directly mutate booking/queue/request truth. An inbound response that means “confirm attendance” invokes booking's supported semantic Command.

Medication reminders execute an authorized plan; communications does not infer dosage/treatment decisions.

---

## 8. Delivery — deferred

The former V2 admission/queue ownership is removed from `delivery`.

Future `ServiceSession`, Fulfillment/outcome evidence and corrections remain deferred until a real execution vertical needs independent policy/lifecycle.

No baseline module may depend on delivery to complete V3 proof flows.

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

Narrow privileged SQL may enforce F1/F2 cross-boundary invariants, but possession of the technical function does not transfer ownership of the underlying business fact to `platform`.

---

## 12. Cross-module transaction/event examples

### BookAppointment

Owner: `booking`.

Consumes immutable catalog contracts; Resource/Reservation/claims commit atomically. Confirmation/reminder consequences are emitted after commit.

For a selected F2 `discoopt_v1`, Booking additionally fences the exact DiscoveryPublication/OfferingServiceClassification observation inside the same Reservation transaction before commitment. This is a prerequisite check, not Discovery ownership of Reservation or CapacityClaim.

### RescheduleReservation

Owner: `booking`.

Old/new Resource claims replace atomically. After commit communications cancels/regenerates obsolete reminder tasks/actions idempotently.

### ConfirmAttendance

Owner: `booking`.

Communications/provider adapters may route an inbound response into this command, but do not mutate Reservation state themselves.

### JoinQueue / CallNext

Owner: `queue`.

Queue completion does not imply universal Fulfillment or Request completion.

### Reservation cancellation → standby recovery

```text
booking cancel commit
→ outbox reservation.cancelled
→ queue create/get SlotOpportunity
→ queue selects WaitlistEntry
→ booking CapacityHold
→ SlotOffer
→ communications notification
```

Only booking claims capacity.

### AcceptSlotOffer

Owner: `queue` for offer/opportunity lifecycle, coordinating booking to confirm the Hold into a Reservation in the same local transaction required by V3-I40.

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

## 13. Ownership change gate

Moving a concept between top-level modules or activating a deferred module requires updating:

- `docs/v3/01-capability-contracts.md` when external semantics change;
- `docs/v3/02-pre-sql-contract.md` when cardinality/transaction/invariants change;
- this map;
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

---

## 14. Discovery — active post-V3 F2

Discovery owns the minimum semantics required to expose tenant-authorized supply across Organizations:

```text
ServiceClassification mapping semantics
OfferingServiceClassification provenance
DiscoveryPublication lifecycle
published cross-tenant candidate projection
objective geospatial filter/order contract
opaque discoopt_v1 handoff issuance state
```

It does **not** own:

```text
Organization / Representation authority       -> tenancy
Location / Offering / OfferingVersion truth   -> catalog
Resource / schedule / contextual terms        -> booking
Reservation / CapacityClaim                   -> booking
GlobalIdentity / SharedCapacityIdentity       -> private shared-capacity machinery
public provider profile                       -> future explicit contract
```

Runtime topology is intentionally split:

```text
Public Discovery process
  request_engine_discovery only
  candidate projection + handoff issuance
  remote availability client
        |
        v
Internal Discovery Availability Gateway
  request_engine_app tenant-domain credential
  exact Publication/Mapping fence
  Booking PublishedSlotReader
```

The public Discovery process must not contain `request_engine_app` credentials or the normal Booking appointment-option signing key. The internal availability gateway is not a generic tenant reader: every call must carry and revalidate exact Publication/Mapping observations before Booking availability is evaluated.

Discovery may import Booking only through supported `contracts`. Booking must not import Discovery adapters/application/domain internals. The discovery-to-booking commitment fence is carried through narrow execution context/PostgreSQL functions so the authoritative Booking transaction can reject revoked/remapped/stale handoffs without reversing module ownership.
