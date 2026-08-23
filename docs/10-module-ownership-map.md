# Request Engine — module ownership map

> **Estado:** normativo para ownership del backend capability-first V3 y extensiones post-V3 aceptadas/activas.
>
> `docs/v3/02-pre-sql-contract.md` define las cardinalidades, serialization roots, transacciones e invariantes del baseline; los contratos post-V3 documentan extensiones explícitas.

## 1. Summary

| Module | Status | Primary ownership |
|---|---|---|
| `tenancy` | baseline | Organization, Principal, Party, PartyContactPoint identity, Representation, tenant authority |
| `catalog` | baseline | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement, structured business info |
| `requests` | baseline | RequestDefinition/Version, durable Request, participants/correlation, generic extension payload/result boundary |
| `booking` | baseline + F1 | Resource, Resource-at-Location contextual supply, availability, CapacityHold/Claim, Reservation, AttendanceResponse, booking commitment/revalidation |
| `queue` | baseline | ServiceQueue/QueueEntry, WaitlistEntry, SlotOpportunity, SlotOffer |
| `communications` | baseline | CommunicationTask/Delivery, communication policy refs, ReminderPlan/Acknowledgement |
| `discovery` | active post-V3 F2 | canonical service classification mapping, tenant discovery publication, cross-tenant published-supply projection, opaque discovery handoff |
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
BookingContextTerms + commercial commitment provenance (F1)
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

F2 may pass an opaque discovery handoff into Booking, but Booking remains the authoritative revalidation and commitment boundary. The handoff can constrain/revalidate publication provenance; it cannot create a second capacity ledger.

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

Commands/Queries include:

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
OfferReleasedSlot
AcceptSlotOffer
DeclineSlotOffer
ExpireSlotOffer
```

---

## 7. Communications

Owns durable communication intent and delivery/reconciliation state. External providers remain adapters; communications do not own Booking or Queue truth.

---

## 8. Discovery — post-V3 F2

Owns only the platform-discovery semantics added by F2:

```text
ServiceClassification vocabulary / mapping semantics
OfferingServiceClassification provenance
DiscoveryPublication lifecycle
published cross-tenant candidate projection
objective geospatial filtering/order inputs
opaque discoopt_v1 handoff issuance state
```

Does **not** own:

```text
Organization / Representation authority       -> tenancy
Location / Offering / OfferingVersion truth   -> catalog
Resource / schedule / terms / capacity        -> booking
Reservation / CapacityClaim                   -> booking
GlobalIdentity / SharedCapacityIdentity       -> private platform/shared-capacity machinery
provider public profile                       -> requires an explicit future owner/contract
```

Important boundaries:

- existence does not imply publication;
- discovery runtime receives only narrow protected read/handoff functions, never generic tenant-table authority;
- Discovery imports Booking only through supported contracts;
- Booking does not import Discovery internals;
- `discoopt_v1` is opaque server-side handoff state, not a public serialization of Resource/private identifiers;
- normal tenant Booking authority is still required after a user selects a discovery option;
- publication/mapping are revalidated at the Booking transaction boundary before commitment.

---

## 9. Deferred modules

`delivery`, `payments`, and `dispatch` remain deferred until a concrete accepted feature activates them. Their existence in the tree does not grant current authority or imply a universal workflow architecture.

---

## 10. Platform

`platform` owns technical plumbing, not business truth:

```text
DB/session mechanics
idempotency
outbox/scheduled work
security execution context
audit/events
observability
narrow privileged SQL mechanics
```

A technical privileged function may enforce a cross-module invariant, but ownership of the business fact remains with the module named above.
