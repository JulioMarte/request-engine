# Request Engine V3 — pre-SQL domain and transaction contract

> **Estado:** normativo pre-SQL para el baseline V3.
>
> Este documento define las entidades mínimas, cardinalidades, serialization roots, transaction protocols, lock ordering, invariant ownership y race matrix que el candidato PostgreSQL V3 debe implementar. Tiene precedencia sobre el V2 `02-pre-sql-domain-contract.md` para conceptos V3.
>
> SQL no debe inventar semántica ausente aquí. Si una tabla requiere una abstracción no justificada por este contrato, el default es no crearla.

---

# 1. Baseline scope

V3 baseline defiende sólo estas capacidades:

```text
Tenant/authority
Structured business/catalog information
Generic durable Requests
Appointment booking/local capacity
Attendance response
FIFO ServiceQueue
Waitlist + released-slot recovery
Transactional communications
Recurring ReminderPlan
Durable ScheduledAction
Idempotency / outbox / provider event / audit
```

No baseline promise para:

```text
OutcomeScope
universal Workflow
ServiceSession/Fulfillment accounting
advanced payments/reconciliation
CapacityPool
external capacity commitments
Dispatch/PlanningRevision
route/workforce optimization
```

---

# 2. Modeling principles

## 2.1 One API does not mean one aggregate

Public capability composition does not erase domain transaction boundaries.

## 2.2 Stable identity only where concurrency/history requires it

Do not create an entity merely because a noun appears in documentation.

## 2.3 JSONB is a boundary tool, not a replacement for relational domain truth

Allowed baseline uses include:

- versioned generic Request payload/schema;
- narrow versioned policy/config documents where relational decomposition adds no invariant;
- provider-safe raw payload hash/reference when required for audit/debugging.

Do not store booking capacity, tenant authority, queue state or lifecycle FKs as arbitrary JSON.

## 2.4 Facts vs current state

Current aggregate state may be updated under concurrency controls. Historical facts that must explain external events/deliveries/audit are append-oriented.

## 2.5 No fake distributed transactions

PostgreSQL atomicity ends at the DB boundary.

---

# 3. Identity and tenant model

Baseline entities are tenant-owned unless explicitly technical/global.

Every critical tenant-owned relationship must be DB-provable as same-Organization, normally through composite references or an equivalent relational mechanism.

## 3.1 Organization

Hard tenant root.

## 3.2 Principal

Authenticated actor identity:

```text
human
service account
agent runtime
integration
provider/webhook principal
worker identity when needed
```

## 3.3 Party

Minimal business identity:

```text
person
organization
```

A Party may have tenant-owned contact points required for operational communications.

## 3.4 Representation

Material authority to act on behalf of Party/subject scope.

Representation remains separate from:

```text
RequestParticipant role
conversation correlation
phone/email ownership
public aggregate id
```

---

# 4. Catalog model

## 4.1 Location

Operational location of a tenant. May expose public address/contact/hours metadata.

## 4.2 Offering

Stable commercial/service identity.

## 4.3 OfferingVersion

Immutable historical version once referenced by an authoritative transaction.

Appointment-relevant versioned configuration may include:

```text
duration
buffer semantics if used
bookable flag
location eligibility
resource requirements
booking/attendance policy reference + version
```

## 4.4 ResourceCapability

Tenant-scoped capability vocabulary such as:

```text
doctor.general_medicine
chair.dental
equipment.ultrasound
```

Do not build skill ontology inheritance in baseline.

## 4.5 Resource

Concrete locally controlled reservable capacity.

Baseline resource capacity fields/concepts:

```text
capacity_model = exclusive | units
capacity_units
active state
location eligibility
availability revision
```

A Resource itself is the baseline capacity serialization root. V3 does **not** require a separate `CapacityAuthority` row.

### Decision: no baseline CapacityAuthority table

Rationale:

- first capacity source is always a concrete Resource;
- Resource provides a stable typed FK and lock row;
- a separate authority row would be one-to-one indirection without a second baseline source type;
- future CapacityPool can introduce a generalized capacity-source abstraction through an explicit migration if needed.

## 4.6 Resource requirement

Baseline retains a deliberately small resource requirement model because real appointments may need more than one local resource atomically.

An OfferingVersion may have `0..N` mandatory resource requirements.

Each requirement means:

```text
one concrete Resource
with one required ResourceCapability
consuming quantity units
for the Reservation interval
```

No baseline:

```text
OR requirements
k-of-n
nested expressions
optional optimization groups
late binding pools
```

Multiple mandatory requirement rows are ANDed.

---

# 5. Request model

## 5.1 RequestDefinition

Stable tenant-scoped definition identity/key for extensible durable demand.

Examples:

```text
request_quote
request_callback
request_service
website_contact
```

## 5.2 RequestDefinitionVersion

Immutable version containing at minimum:

```text
input schema/version
optional result schema/version
public capability metadata
active/deprecated state semantics
```

Implementation may use JSON Schema in JSONB or an explicit schema reference. The database does not need to implement arbitrary JSON Schema validation; Python validates and persists the exact version used. SQL enforces that the referenced version belongs to the same tenant/definition.

## 5.3 Request

Durable new business demand.

Baseline lifecycle:

```text
open
completed
cancelled
failed
```

Terminal states do not reopen.

Baseline Request stores/references:

```text
organization
RequestDefinitionVersion
requester/recipient Parties where relevant
validated input payload
safe final result payload when applicable
revision
created/completed timestamps
```

## 5.4 RequestParticipant

Optional typed Party roles for a Request. Role does not grant authority.

## 5.5 ExternalCorrelation

N:M correlation to channels/threads/calls/forms. Not authority.

## 5.6 Decision: no baseline OutcomeScope

A demonstrated independent requested-outcome lifecycle does not exist in the six proof verticals.

## 5.7 Decision: no baseline universal Workflow

Request processing uses typed application handlers, outbox, ScheduledAction and extension callbacks.

---

# 6. Appointment/booking model

## 6.1 Reservation cardinality decision

Baseline:

```text
Reservation N ── 1 OfferingVersion
Reservation N ── 1 recipient/subject Party
Reservation N ── 0..1 Location
Reservation 1 ── 1..N active CapacityClaims when OfferingVersion has requirements
```

### Decision: no ReservationItem baseline

One Reservation represents one bookable OfferingVersion for one subject and interval.

If several services are sold as one appointment, model the commercial/service package as one OfferingVersion initially.

Reason:

- removes an aggregate level not required by initial use cases;
- eliminates commitment-requirement join graphs;
- makes booking atomicity and reschedule semantics explicit;
- future multi-offering transactions can add a compound booking capability when product evidence exists.

## 6.2 CapacityHold

Temporary local commitment.

States:

```text
active
consumed
released
expired
```

Fields/concepts:

```text
expires_at authoritative instant
revision
created_by / provenance
```

An active Hold has `1..N` active CapacityClaims satisfying the OfferingVersion's mandatory requirements selected for the proposed interval.

A Hold consumes capacity iff:

```text
hold.status = active
AND expires_at > authoritative DB wall clock
AND claim.status = active
```

Persisted `expired` is operational/history state; wall-clock expiry wins even before a cleanup worker updates the row.

## 6.3 CapacityClaim

Common local capacity-consumption truth for both Holds and Reservations.

Each claim references:

```text
organization
Resource
resource requirement identity when applicable
interval [start, end)
quantity
status = active | released | replaced
source Hold? for provenance/temporary ownership
Reservation? when confirmed
```

Ownership rule:

```text
hold_id present, reservation_id absent
    → temporary hold claim

reservation_id present
    → reservation claim
    → hold_id may remain as provenance if promoted from a hold
```

No separate `ResourceAllocation` baseline.

### Decision: merge ResourceAllocation truth into CapacityClaim

Rationale:

- V2 required deferred machinery to keep a 1:1 allocation/claim pair synchronized;
- initial product has no independent operational assignment lifecycle;
- one row can express resource, interval, quantity, requirement and reservation ownership;
- if future execution assignment differs from capacity consumption, introduce `ResourceAssignment` as a distinct proven concept.

## 6.4 Reservation

States:

```text
confirmed
cancelled
closed
```

`closed` means reservation lifecycle no longer consumes capacity. Queue completion/no-show/attendance are not encoded as Reservation status.

Fields/concepts:

```text
OfferingVersion
subject Party
Location?
start_at/end_at or authoritative interval
revision
booking policy/version snapshot/reference
origin Request? optional correlation only
```

## 6.5 AttendanceResponse

Distinct child state/fact of Reservation.

Baseline current values:

```text
pending
accepted
declined
```

The system should preserve who/when/source for material attendance responses, either append-oriented response rows with a current projection or equivalent history-preserving design.

### Decision: prefer append-oriented AttendanceResponse history

Rationale:

- inbound responses can arrive from WhatsApp, voice, staff and web;
- corrections/change of mind should remain auditable;
- one small append table avoids overloading Reservation lifecycle.

Reservation exposes derived current attendance response.

---

# 7. Availability and time semantics

## 7.1 Intervals

All authoritative capacity intervals use half-open semantics:

```text
[start, end)
```

`start < end` required.

Store authoritative instants as timezone-aware timestamps. IANA timezone is separately retained where local schedule interpretation/presentation requires it.

## 7.2 AvailabilitySchedule

Recurring resource availability expressed in local wall-clock semantics + IANA timezone.

Schedule mutation increments a Resource availability revision and serializes through the Resource lock.

## 7.3 ScheduleException

Date/range override/closure/additional availability for one Resource.

Mutation serializes through Resource.

## 7.4 Find-slots is advisory

Availability query may compute options without locks. `BookAppointment`/Hold acquisition must lock Resources and re-read/revalidate current schedule, exceptions, capacity and eligibility before writing claims.

## 7.5 DST

Ambiguous/nonexistent local times must be explicitly resolved or rejected during option generation. No implicit server-local timezone conversion.

---

# 8. ServiceQueue model

## 8.1 ServiceQueue

Stable serialization/config root.

May bind to:

```text
Location?
Offering/service family?
queue policy/version
```

Baseline policy is FIFO.

## 8.2 QueueEntry

States:

```text
waiting
called
serving
completed
cancelled
no_show
```

References:

```text
ServiceQueue
subject Party
Reservation? optional
Offering? optional
admitted_at
state timestamps
revision
```

At most one active entry per `(ServiceQueue, subject Party)` in baseline, where active means:

```text
waiting | called | serving
```

Queue position is derived, not stored authoritative counter state.

---

# 9. Waitlist model

## 9.1 WaitlistEntry

Represents future capacity interest; never capacity consumption.

Baseline fields/concepts:

```text
subject Party
Offering stable identity
Location? preference
provider/Resource? preference
acceptable earliest_start?
acceptable latest_start?
status = active | fulfilled | cancelled | expired
created_at
revision
```

No generic preference DSL.

## 9.2 SlotOpportunity

Coordination root created when a specific appointment opportunity should be offered to standby demand.

It may originate from:

```text
reservation cancellation
explicit released slot event
future supported opportunity source
```

Fields/concepts:

```text
OfferingVersion to be booked
Location
start/end
source event / source Reservation correlation
status = open | filled | closed | expired
revision
```

Important:

> SlotOpportunity is not capacity authority and does not prove the slot remains free.

Booking owns capacity truth.

### Decision: introduce SlotOpportunity

Without it, sequential SlotOffers lack a stable coordination/serialization identity and duplicate release events can create parallel candidate chains.

## 9.3 SlotOffer

One expiring offer to one WaitlistEntry.

States:

```text
offered
accepted
declined
expired
cancelled
```

References:

```text
SlotOpportunity
WaitlistEntry
CapacityHold
expires_at
revision
```

Baseline policy uses a short CapacityHold while an offer is active.

### Decision: baseline SlotOffer reserves capacity with a short Hold

Rationale:

- prevents notifying one candidate about an offer that ordinary booking can consume before acceptance;
- makes offer expiry semantics deterministic;
- reuses booking capacity correctness rather than inventing waitlist locks;
- business may later add non-exclusive/broadcast offer mode explicitly.

Only one active `offered` SlotOffer exists per SlotOpportunity in baseline.

Candidate selection among eligible WaitlistEntries is FIFO by `(created_at, id)`.

---

# 10. Communications model

## 10.1 PartyContactPoint

Minimal tenant-owned operational endpoint:

```text
Party
channel kind: phone | email | whatsapp or future typed key
normalized endpoint/value
verification state when known
active state
```

Sensitive contact data must follow application/security policy. This is not CRM profile management.

## 10.2 CommunicationTask

Durable business intent to communicate.

States:

```text
pending
delivering
completed
cancelled
failed
```

Fields/concepts:

```text
purpose
recipient Party/contact target
source module/type/public id or typed relational references where critical
channel policy
message/template key + version
safe rendering context or snapshot
dedupe key
not_before?
expires_at?
revision
```

A task may have many delivery attempts.

## 10.3 CommunicationDelivery

Append-oriented concrete attempt/fact.

Fields/concepts:

```text
CommunicationTask
channel/provider
attempt number
provider idempotency key
provider message/call id?
status
started_at/completed_at
normalized result/error class
```

Do not rewrite previous attempts as if they never happened.

Exactly-once provider delivery is not promised.

## 10.4 Template storage decision

No mandatory `CommunicationTemplate` table in baseline.

CommunicationTask persists a stable template/content key and version or content snapshot sufficient to explain what was intended. Template implementation may initially live in application/config/provider systems.

Introduce tenant-editable template entities only when product functionality requires them.

---

# 11. ReminderPlan model

## 11.1 ReminderPlan

Recurring business intent independent of Reservation.

States:

```text
active
cancelled
completed
```

Baseline schedule specification is a versioned typed document:

```text
type = daily_times
timezone = IANA zone
local_times = [HH:MM...]
start_date
end_date?
missed_execution_policy = skip | send_within_window
optional late window
```

No arbitrary executable cron payload.

Material changes increment plan revision/version. Completed delivery history remains immutable.

## 11.2 ReminderAcknowledgement

Optional append fact:

```text
ReminderPlan / occurrence identity
Party
acknowledged_at
source
reported value/key when purpose defines one
```

For medication reminders this records user report, not clinically verified adherence.

## 11.3 Materialization horizon

Application scheduler may materialize future ScheduledActions within a bounded horizon rather than infinite recurrence rows.

Generation is idempotent by:

```text
ReminderPlan + plan revision + occurrence instant + action type
```

---

# 12. ScheduledAction model

Technical durable future work.

States:

```text
pending
leased
completed
cancelled
dead
```

Required fields/concepts:

```text
organization where tenant-owned
owner module
action type/version
typed reference/payload
execute_at
next_attempt_at
lease_until?
claim_token/fencing token?
attempt_count
max_attempts
last_error_class?
dedupe key
completed_at?
```

## 12.1 Claim protocol

Claim transaction:

```text
SELECT due pending/reclaimable rows
FOR UPDATE SKIP LOCKED
→ assign fresh claim_token
→ set leased + lease_until
→ increment attempt_count
→ COMMIT
```

External/business execution occurs after claim transaction commits.

Completion/failure update requires the current claim_token. A stale worker cannot complete a row after another worker reclaimed it.

## 12.2 Retry

Failure classification decides:

```text
retryable → pending with next_attempt_at
non-retryable → dead
attempt_count >= max_attempts → dead
```

Manual replay creates a new leaseable attempt or explicitly resets according to an audited admin command; history remains observable.

---

# 13. Outbox and ProviderEvent

## 13.1 OutboxMessage

Durable after-commit integration/event delivery.

Outbox and ScheduledAction remain separate because:

```text
Outbox = publish a fact/consequence after commit
ScheduledAction = execute future work at/after an authoritative time
```

Outbox baseline must adopt the same production-grade properties missing from early V2:

```text
lease/fencing
attempt_count
max_attempts
next_attempt_at
dead-letter terminal state
manual replay
```

## 13.2 ProviderEvent

Dedupe/correlation boundary for inbound provider callbacks.

Uniqueness based on:

```text
organization/provider connection + provider event identity
```

When provider lacks a stable event id, use an explicit documented dedupe strategy/hash and accept its limitations.

Raw external payload may be retained/referenced according to security/privacy policy, but provider payload is never business authority by itself.

---

# 14. Idempotency

Every network-retryable mutation has an idempotency record keyed conceptually by:

```text
organization
Principal
capability/command
idempotency key
```

Record includes a canonical request fingerprint/hash.

Protocol:

```text
acquire idempotency identity
if completed with same fingerprint → replay safe result
if same key different fingerprint → reject
if in progress → serialize/wait or return explicit in-progress semantics
execute authoritative transaction
persist deterministic result identity/status atomically enough that retry cannot repeat business effect
```

Authorization is revalidated according to command semantics even when the key exists; do not let possession of an idempotency key bypass current tenant/Principal binding.

---

# 15. Audit

Audit is append-oriented and distinct from technical logs.

Material mutation record includes as applicable:

```text
organization
actor Principal
represented Party/scope + Representation version/reference
capability/command
aggregate/public identifiers
before/after semantic state or safe diff/reference
policy/version
idempotency identity
correlation ids
timestamp
reason/override when required
```

Database owner/superuser can still alter database history. Baseline audit is application/database-immutable under runtime roles, not a cryptographic WORM guarantee.

---

# 16. Runtime database isolation decision

V3 adopts PostgreSQL RLS as defense-in-depth for tenant-owned baseline tables.

## 16.1 Runtime roles

Conceptual roles:

```text
schema_owner       NOLOGIN / migration ownership
request_app        application runtime, no BYPASSRLS
request_worker     worker runtime, no blanket BYPASSRLS
request_admin      explicit privileged operational role, tightly controlled
```

Production runtime never connects as schema owner/superuser.

## 16.2 Tenant context

Each tenant-scoped authoritative transaction sets a transaction-local organization context after application authentication/authorization resolution.

RLS policy requires row `organization_id` equal current context.

RLS is defense-in-depth, not a substitute for application authority: a shared runtime role can technically set another tenant context if compromised application code is allowed to issue arbitrary SQL. Therefore SQL surfaces and application permissions remain narrow.

## 16.3 Cross-tenant worker claiming

Workers do not receive blanket tenant-table visibility merely to discover work.

Use narrow `SECURITY DEFINER` claim primitives (or equivalent controlled technical surfaces) to claim cross-tenant outbox/ScheduledAction rows. The primitive returns the organization identity required for subsequent tenant-scoped execution.

The worker-control connection has no direct privileges on authoritative tables.
After a narrow claim primitive returns the tenant identity, business processing
uses a separate `request_app` connection and a transaction-local tenant context.
This credential split prevents a compromised global worker connection from
turning an arbitrary tenant GUC into direct table authority.

Security-definer functions must pin `search_path` to trusted schemas with
`pg_temp` last, have a non-login owner and grant only minimal EXECUTE permission.

---

# 17. Serialization roots

Baseline authoritative serialization roots:

| Concern | Serialization root / lock |
|---|---|
| Request lifecycle | `Request` |
| Representation revocation/update | `Representation` |
| Resource capacity + availability mutation | `Resource` |
| Hold lifecycle | `CapacityHold` then affected Resources |
| Reservation mutation | `Reservation` then affected Resources |
| Attendance append/change consequence | `Reservation` |
| FIFO selection | `ServiceQueue` then selected QueueEntry |
| QueueEntry direct lifecycle | `ServiceQueue` then QueueEntry |
| Waitlist opportunity chain | `SlotOpportunity` then SlotOffer/WaitlistEntry, then Hold/Resources when needed |
| ReminderPlan mutation | `ReminderPlan` |
| CommunicationTask lifecycle | `CommunicationTask` |
| Scheduled work claim | `ScheduledAction` row via SKIP LOCKED/fence |
| Outbox claim | `OutboxMessage` row via SKIP LOCKED/fence |
| Idempotent mutation | idempotency record before domain mutation |

A stable lock row is a concurrency mechanism, not proof of a rich DDD aggregate.

---

# 18. Canonical lock ordering

When one command needs several roots, use:

```text
0. idempotency identity (when applicable)
1. primary existing business root
   Request | Reservation | ServiceQueue | SlotOpportunity | ReminderPlan | CommunicationTask
2. child/root-specific rows
   SlotOffer | WaitlistEntry | CapacityHold | QueueEntry
3. Resources, sorted by stable Resource id
4. append/write dependent rows
```

Special cases:

### Acquire Hold

Hold is new/uncontended; lock all planned Resources sorted before inserting claims.

### Confirm existing Hold

```text
CapacityHold
→ Resources sorted
→ create Reservation / promote claims
```

### Reschedule

```text
Reservation
→ union(old Resource ids, new Resource ids) sorted
→ replace claims
```

### Cancel Reservation

```text
Reservation
→ active claim Resources sorted
→ release claims
```

### Waitlist offer creation

```text
SlotOpportunity
→ selected WaitlistEntry
→ Resources sorted through booking Hold acquisition
→ create Hold claims + SlotOffer
```

### Accept SlotOffer

```text
SlotOpportunity
→ SlotOffer
→ CapacityHold
→ Resources sorted
→ confirm Reservation / mark offer + opportunity
```

No command may acquire Resource first and then later an existing Reservation/Hold/SlotOpportunity when another command can acquire them in the reverse order.

---

# 19. Authoritative command protocols

Every critical command follows:

```text
READ
PLAN
LOCK
VALIDATE
WRITE
EMIT
COMMIT
```

External I/O comes after commit.

## 19.1 CreateRequest

```text
validate RequestDefinitionVersion + payload
validate Principal/tenant/participants
acquire idempotency
insert Request(open)
append audit
append outbox request.created.v1 when integration policy requires
commit
```

## 19.2 RecordRequestResult / CompleteRequest

```text
acquire idempotency
lock Request
validate integration Principal/authority/current state/result schema
write result / terminal transition
append audit/outbox
commit
```

## 19.3 AcquireCapacityHold

```text
validate desired OfferingVersion/subject/location
plan concrete Resources satisfying mandatory requirements
sort Resource ids
lock Resources
re-read Resource availability revisions/schedules/exceptions
validate capacity excluding no claims
insert Hold(active) + complete claim set atomically
commit
```

Failure leaves no partial active Hold.

## 19.4 BookAppointment direct

```text
acquire idempotency
plan concrete Resources
lock Resources sorted
revalidate Offering/resource eligibility, schedule, exceptions, capacity
insert Reservation(confirmed)
insert complete active reservation claim set
append audit/outbox reservation.created.v1
commit
```

## 19.5 Confirm Hold

```text
acquire idempotency
lock Hold
reject if wall-clock expired/released/consumed
lock Hold Resources sorted
revalidate current Resource/schedule state where policy requires
create Reservation
promote existing claim rows to reservation ownership (or equivalent non-double-counting transformation)
mark Hold consumed
append audit/outbox
commit
```

Confirmation must not temporarily double-count Hold + Reservation consumption.

## 19.6 CancelReservation

```text
acquire idempotency
lock Reservation
validate cancellable policy/state
lock active claim Resources sorted
mark claims released
mark Reservation cancelled
append audit/outbox reservation.cancelled.v1
commit
```

Waitlist processing happens after commit.

## 19.7 RescheduleReservation

```text
acquire idempotency
read/plan new concrete Resource set
lock Reservation
read old active claims
lock union(old,new Resources) sorted
re-read current schedules/capacity
validate FINAL desired capacity state while excluding this Reservation's old claims that will be replaced
mark old claims replaced
insert new active claims
update Reservation interval/location/revision
append audit/outbox reservation.rescheduled.v1
commit
```

No replacement Hold is required for correctness.

On any error/rollback, old claims and old Reservation state remain active.

## 19.8 RecordAttendanceResponse

```text
acquire idempotency
lock Reservation
validate actor/authority/current Reservation/policy
append AttendanceResponse fact
if response consequences require cancellation:
    lock active Resources sorted
    release claims + cancel Reservation in same transaction
append audit/outbox attendance_changed (+ cancelled when applicable)
commit
```

## 19.9 JoinQueue

```text
acquire idempotency
lock ServiceQueue
validate subject eligibility/no active duplicate
insert QueueEntry(waiting)
append audit/outbox as configured
commit
```

## 19.10 CallNext

```text
acquire idempotency when network-retryable
lock ServiceQueue
select earliest eligible waiting QueueEntry by (admitted_at,id)
lock selected entry
transition to called
append audit/outbox queue.entry_called.v1
commit
```

## 19.11 CreateSlotOpportunity

Triggered after capacity-release event:

```text
dedupe source event
create/get SlotOpportunity for released reservation interval/scope
commit
```

Does not claim capacity.

## 19.12 OfferNextWaitlistCandidate

```text
lock SlotOpportunity(open)
verify no active offered SlotOffer
select earliest eligible active WaitlistEntry
plan booking Resources for opportunity
lock Resources sorted
revalidate availability/capacity
create short CapacityHold + complete claims
create SlotOffer(offered) referencing Hold
append outbox slot_offer.created.v1
commit
```

Communication happens later.

If candidate selection exists but capacity disappeared, close/reevaluate Opportunity according to policy; do not send false offer.

## 19.13 AcceptSlotOffer

```text
acquire idempotency
lock SlotOpportunity
lock SlotOffer
lock CapacityHold
validate offer offered/unexpired + Opportunity open + Hold active/unexpired
lock Hold Resources sorted
confirm Reservation using held claims
mark SlotOffer accepted
mark SlotOpportunity filled
mark WaitlistEntry fulfilled
append audit/outbox reservation.created + offer accepted
commit
```

All local state changes atomic.

## 19.14 Decline/Expire SlotOffer

```text
lock SlotOpportunity
lock SlotOffer
lock Hold
lock Hold Resources sorted
validate current state
release Hold claims + mark Hold released/expired
mark offer declined/expired
append event enabling next candidate
commit
```

## 19.15 Derive appointment communications

Outbox consumer processes reservation event idempotently:

```text
read event
load versioned communication policy
create deduped CommunicationTasks
create ScheduledActions at required times
commit
```

No booking locks required because this is consequence materialization, not capacity truth.

Reschedule/cancel consumers idempotently cancel obsolete pending actions/tasks and create replacements.

## 19.16 Deliver communication

```text
claim ScheduledAction in short claim transaction
commit

create/load provider delivery attempt identity
call provider outside authoritative transaction

record CommunicationDelivery result
complete/reschedule/dead ScheduledAction using current fencing token
commit
```

Provider ambiguity after timeout is recorded as ambiguous/retry-policy input, not silently treated as definitely unsent.

## 19.17 n8n Request callback

```text
authenticate integration Principal
bind tenant + correlation
acquire idempotency
lock Request
revalidate current state/definition result schema
record result/complete as semantic command
append audit/outbox
commit
```

---

# 20. V3 invariant matrix

Enforcement classes:

```text
DB      structural/transactional database backstop
APP     application/domain policy
BOTH    application semantics + DB backstop
EXT     external truth handled through provider facts/reconciliation
```

## Tenant/authority

| ID | Invariant | Owner |
|---|---|---|
| V3-I01 | Critical tenant-owned references never cross Organization | DB |
| V3-I02 | Correlation/public identifier/participant role never grants authority | APP |
| V3-I03 | Material commands revalidate current Principal/Representation/policy | APP |
| V3-I04 | Runtime app/worker roles do not use schema-owner/superuser authority | DB/ops |
| V3-I05 | Tenant-owned runtime reads/writes are protected by RLS defense-in-depth | DB |
| V3-I06 | Material audit records actor and authority/policy provenance | BOTH |

## Catalog/config

| ID | Invariant | Owner |
|---|---|---|
| V3-I07 | Referenced OfferingVersion semantics are not rewritten historically | BOTH |
| V3-I08 | Resource/Capability/Location configuration remains tenant-local | DB |
| V3-I09 | Schedule-changing mutations serialize through Resource and advance revision | BOTH |

## Requests

| ID | Invariant | Owner |
|---|---|---|
| V3-I10 | Request payload was validated against the exact referenced RequestDefinitionVersion | APP + DB reference |
| V3-I11 | Request terminal lifecycle is monotonic | BOTH |
| V3-I12 | Same idempotency key + different command fingerprint is rejected | BOTH |
| V3-I13 | n8n/provider callbacks are tenant-bound, authenticated and semantic | APP |
| V3-I14 | Cancelling Request does not implicitly cancel independent generated domain state | APP |

## Booking/capacity

| ID | Invariant | Owner |
|---|---|---|
| V3-I15 | Capacity interval is valid half-open `[start,end)` with start < end | DB |
| V3-I16 | CapacityClaim tenant, Resource, Hold/Reservation owners are relationally consistent | DB |
| V3-I17 | An active exclusive Resource never has overlapping live consumption > 1 | BOTH |
| V3-I18 | An active units Resource never has overlapping live quantity > capacity_units | BOTH |
| V3-I19 | Hold acquisition is all-or-none across mandatory resource requirements | transaction + BOTH |
| V3-I20 | Wall-clock expired Hold cannot confirm even if cleanup has not run | BOTH |
| V3-I21 | Successful Reservation has complete active claims for all mandatory requirements | BOTH |
| V3-I22 | Hold confirmation does not double-count promoted claims | BOTH |
| V3-I23 | CancelReservation releases all active Reservation claims atomically with cancellation | transaction + DB checks |
| V3-I24 | Reschedule validates final state excluding only claims replaced from same Reservation | BOTH |
| V3-I25 | Failed reschedule leaves original Reservation/claims unchanged | transaction |
| V3-I26 | Resource locks are acquired in canonical stable-id order | APP protocol |
| V3-I27 | Booking revalidates schedule/exception/capacity after acquiring Resource locks | APP |
| V3-I28 | Reservation terminal state never retains active capacity-consuming claims | BOTH |
| V3-I29 | Attendance response is independent from Reservation confirmed status | domain/DB model |
| V3-I30 | No-response/decline affects Reservation only through explicit versioned policy | APP |

## ServiceQueue

| ID | Invariant | Owner |
|---|---|---|
| V3-I31 | At most one active QueueEntry per `(ServiceQueue, subject)` in baseline | DB |
| V3-I32 | `CallNext` chooses earliest eligible waiting entry by deterministic FIFO | APP under queue lock |
| V3-I33 | Two concurrent `CallNext` commands cannot call the same entry | DB transaction/lock |
| V3-I34 | QueueEntry lifecycle follows allowed state transitions | BOTH |
| V3-I35 | Queue position is derived, never an authoritative mutable counter | architecture |

## Waitlist

| ID | Invariant | Owner |
|---|---|---|
| V3-I36 | WaitlistEntry alone never consumes capacity | model/DB |
| V3-I37 | SlotOpportunity never substitutes for booking capacity validation | APP |
| V3-I38 | At most one active offered SlotOffer per SlotOpportunity in baseline | DB |
| V3-I39 | Active SlotOffer references an active/unexpired short CapacityHold | BOTH |
| V3-I40 | AcceptSlotOffer atomically confirms Reservation and fills offer/opportunity | transaction + BOTH |
| V3-I41 | Decline/expiry releases the offer Hold before opportunity advances | transaction + BOTH |
| V3-I42 | One SlotOpportunity can be filled at most once | BOTH |
| V3-I43 | Candidate selection is deterministic FIFO among eligible active entries | APP under opportunity lock |

## Communications/reminders

| ID | Invariant | Owner |
|---|---|---|
| V3-I44 | Communication provider I/O never runs inside originating authoritative business transaction | architecture/APP |
| V3-I45 | Business-event-derived CommunicationTask creation is idempotent/deduped | BOTH |
| V3-I46 | CommunicationDelivery preserves attempt history; provider identifiers are correlated/deduped | BOTH/EXT |
| V3-I47 | Provider delivery status never directly mutates unrelated business aggregates | APP |
| V3-I48 | ReminderPlan timezone and schedule type are explicit/versioned | BOTH |
| V3-I49 | Reminder occurrence materialization is idempotent per plan revision + occurrence | BOTH |
| V3-I50 | Cancelling/updating ReminderPlan stops obsolete pending future actions without rewriting delivered history | BOTH |
| V3-I51 | Medication reminder execution never infers/changes clinical instruction | product boundary/APP |

## Scheduling/outbox/providers

| ID | Invariant | Owner |
|---|---|---|
| V3-I52 | A ScheduledAction/OutboxMessage lease has one current fencing token | DB |
| V3-I53 | Stale worker cannot complete/release work after lease was reclaimed | DB |
| V3-I54 | Retries are bounded; poison work reaches terminal dead state | BOTH |
| V3-I55 | Claim transaction ends before external I/O | architecture/APP |
| V3-I56 | Provider events are deduped before semantic processing | BOTH |
| V3-I57 | External exactly-once delivery is not assumed; ambiguous outcomes use provider idempotency/reconciliation policy | EXT/APP |
| V3-I58 | Outbox publication is consequence of committed local fact, never pre-commit network I/O | transaction/APP |

## Audit/idempotency

| ID | Invariant | Owner |
|---|---|---|
| V3-I59 | Material runtime audit is append-oriented under normal app roles | DB |
| V3-I60 | Idempotent retry cannot repeat an already committed business effect | BOTH |
| V3-I61 | Idempotency identity is bound to Organization + Principal + capability + fingerprint | BOTH |

---

# 21. Required concurrency/race matrix

A schema is not ready for `0001_initial` until critical races below are executable against real PostgreSQL.

## Booking

1. two direct bookings, same exclusive Resource/interval → exactly one succeeds;
2. concurrent unit claims whose sum exceeds capacity → oversell impossible;
3. multi-resource Hold where one Resource conflicts → zero active partial Hold claims;
4. Hold expires while confirmation races → no confirmation after authoritative expiry;
5. cancel vs reschedule same Reservation → one serial outcome; no leaked claims;
6. duplicate book same idempotency key → one Reservation/result;
7. same-resource overlapping self-reschedule → succeeds when final state is otherwise valid;
8. self-reschedule vs third-party booking into new interval → no oversell; loser gets conflict;
9. units self-reschedule → old claim excluded, not temporarily double-counted;
10. schedule exception/update vs book → one serialization order; booking revalidates after lock;
11. resource deactivation vs booking → no commitment against invalid resource after serialized mutation;
12. confirm Hold vs release Hold → one valid terminal outcome.

## ServiceQueue

13. two `CallNext` workers same queue → distinct/one next result, never same entry;
14. duplicate JoinQueue same subject → one active entry;
15. leave/cancel vs CallNext → deterministic serialized state;
16. mark no-show vs start service → one allowed transition wins;
17. same timestamps → stable id tie-breaker keeps deterministic FIFO.

## Waitlist

18. duplicate reservation-cancelled event → one SlotOpportunity;
19. two offer workers same Opportunity → max one active SlotOffer;
20. SlotOffer accept exactly as ScheduledAction expires it → one terminal outcome;
21. two duplicate accepts → one Reservation via idempotency;
22. ordinary booking competes before short Hold acquisition → either Hold or ordinary booking wins, no false active offer;
23. candidate becomes inactive/cancelled while offer worker selects → revalidation prevents invalid offer;
24. decline/expiry vs accept → one serialized result, no orphan Hold;
25. accepted offer transaction failure → offer/Hold/opportunity remain in pre-accept state via rollback.

## Requests/n8n

26. duplicate `requests.submit` → one Request;
27. duplicate n8n result callback → one result transition;
28. n8n callback after Request cancelled/completed → explicit stale/terminal response, no rewrite;
29. callback wrong tenant/correlation → rejected;
30. integration Representation revoked before callback → rejected according to current authority policy.

## Scheduling/outbox

31. two workers claim same ScheduledAction → one current claim token;
32. worker dies after claim → action reclaimable after lease;
33. stale worker completes after reclaim → fencing rejects stale completion;
34. retry reaches max → dead, no infinite loop;
35. cancel pending action vs claim → one serialized outcome;
36. cancel leased action vs worker completion → explicit race semantics; no silent resurrection;
37. two outbox workers same message → one current claim token;
38. poison outbox message → dead-letter after bounded attempts.

## Communications/providers

39. duplicate reservation event → one deduped reminder/confirmation task set;
40. provider timeout after it may have accepted send → retry follows provider-idempotency/ambiguity policy, not blind duplicate assumption;
41. duplicate provider delivery callback → one normalized effect;
42. late success arrives after fallback scheduled → policy prevents unintended duplicate fallback when detectable;
43. reschedule event vs due old reminder → old reminder revalidates source revision/policy or is cancelled so stale appointment time is not intentionally sent;
44. cancel Reservation vs due reminder → cancellation policy prevents future stale reminder delivery when action has not irreversibly reached provider.

## Tenant/security

45. tenant A public id used under tenant B context → no row access/mutation;
46. worker global claim returns tenant-scoped work but subsequent business query without/set wrong tenant context cannot read target rows;
47. app runtime role cannot bypass RLS or execute admin-only SQL surfaces;
48. SECURITY DEFINER claim primitive cannot be hijacked through search_path/object shadowing.

---

# 22. Failure and recovery matrix

| Failure | Required behavior |
|---|---|
| capacity conflict | no partial commitment; return typed conflict + suggest find_slots |
| Hold expiry | fail confirmation; reacquire capacity; never resurrect expired Hold |
| reschedule conflict | original Reservation remains committed |
| DB deadlock/serialization failure | safe command-level retry only when idempotency/policy allows |
| worker crash before external I/O | lease expires/reclaim |
| provider timeout/unknown result | record ambiguity; use provider idempotency/query/reconciliation strategy |
| provider hard reject | delivery attempt fails; retry/fallback only by policy |
| repeated poison work | dead-letter after bounded attempts |
| duplicate provider callback | dedupe and replay-safe response |
| stale reminder after reschedule/cancel | source state/revision policy prevents intentional stale send before provider handoff |
| n8n unavailable | Request remains open; outbox retry/dead-letter surfaces operational backlog |
| n8n callback after terminal Request | reject/no historical rewrite |
| SlotOffer expires | release Hold; opportunity may advance |
| accept after expiry | reject; candidate may rejoin/receive future offer |
| communication provider outage | booking/request transaction remains successful; communication backlog observable |

---

# 23. Read model guidance

SQL schema should support capability-oriented reads, not table mirroring.

Candidate stable read contracts:

```text
request_read.business_info_v1
request_read.offering_summary_v1
request_read.reservation_status_v1
request_read.service_queue_status_v1
request_read.waitlist_status_v1
request_read.communication_status_v1        # operational/admin
request_admin.scheduled_action_health_v1
request_admin.outbox_health_v1
```

`find_slots` is a Query Service and may require richer SQL/application computation rather than one static view.

---

# 24. Narrow PostgreSQL command primitives

Potential `request_cmd.*` primitives remain data-centric:

```text
acquire_idempotency
complete_idempotency
claim_outbox_batch
complete/retry/dead_outbox_message
claim_scheduled_action_batch
complete/retry/dead_scheduled_action
```

Capacity/queue business workflows stay in Python-owned commands. SQL functions may provide narrow lock/check primitives if tests prove they reduce risk, but no `book_appointment_workflow()` stored procedure that absorbs application policy.

---

# 25. Decisions closed by this contract

The previous `RE_EVALUATE` items are resolved as follows:

| Question | V3 baseline decision |
|---|---|
| ReservationItem needed? | **No** — one Reservation = one OfferingVersion |
| ResourceRequirementTemplate needed? | **Keep simplified** as immutable OfferingVersion mandatory resource requirements |
| Separate CapacityAuthority row? | **No** — concrete Resource is serialization root |
| CapacityClaim for hold + reservation? | **Yes** — common claim truth; no ResourceAllocation baseline |
| AttendanceResponse own history? | **Yes** — append-oriented response history/current projection |
| Generic IntakeDefinition separate from RequestDefinition? | **No baseline separate concept** — RequestDefinitionVersion supplies validated generic input contract |
| SlotOffer reserve capacity? | **Yes** — short CapacityHold baseline |
| Need stable opportunity root? | **Yes** — SlotOpportunity coordinates sequential offers and event dedupe |
| Universal Workflow? | **No** |
| OutcomeScope/Fulfillment baseline? | **No** |
| RLS? | **Yes**, defense-in-depth with narrow cross-tenant worker claim primitives |
| Outbox infinite retry? | **No** — bounded + dead-letter |

---

# 26. Schema construction gate

A clean V3 SQL candidate may now be designed because baseline semantic questions are sufficiently closed.

However `0001_initial` remains blocked until:

1. candidate schema maps every concept here without reintroducing deferred V2 nouns;
2. DB enforcement assignment for V3-I01..I61 is documented beside implementation/tests;
3. booking, queue, waitlist, scheduling and idempotency critical races run against PostgreSQL 18;
4. RLS/runtime-role privilege tests pass;
5. at least these proof flows execute end to end at application/DB level:
   - business information query;
   - direct appointment booking/cancel/reschedule;
   - appointment reminder/attendance response;
   - FIFO queue;
   - cancellation → SlotOpportunity → SlotOffer → rebooking;
   - generic Request → outbox → semantic integration callback;
6. only then squash the approved schema into Alembic `0001_initial`.

The schema should be materially smaller than V2.10. That is an architectural objective, not a regression.

---

# 27. Gated V3 extension contract — cross-tenant shared capacity

This section is normative for any V3 candidate that includes the cross-tenant shared-capacity migrations and runtime integration. It extends the baseline without replacing tenant ownership or introducing a generalized CapacityPool.

Statements above that describe `Resource` as the baseline capacity root remain true for every unbound Resource. For an explicitly authorized binding, the local Resource remains the first tenant-local lock root and an opaque `SharedCapacityIdentity` becomes an additional hidden serialization root.

## 27.1 Identity, authority and consumption truth

The extension adds these internal concepts:

```text
GlobalIdentity
    opaque control-plane identity for the real-world person/organization

SharedCapacityIdentity
    opaque serialization identity for one indivisible physical/logical capacity

SharedCapacityBinding
    explicit trusted authorization from one tenant-local Resource to one shared root

SharedCapacityClaimLink
    private claim-to-root serialization provenance
```

`Party` and `Resource` remain tenant-local. No global people directory or global Resource is created. Correlation by email, phone, government identifier, provider identifier or UUID knowledge never grants binding or read authority.

Only the trusted administrative/control-plane authority may create global identities, shared roots or activate/revoke bindings. Ordinary app and worker roles may neither enumerate nor mutate that global state.

`CapacityClaim` remains the **sole authoritative capacity-consumption ledger**. `SharedCapacityClaimLink` stores only private serialization provenance; it does not duplicate interval, quantity, Reservation, Party or Offering truth.

The initial shared-capacity model is restricted to `exclusive` Resources. Generalized unit sharing, CapacityPool semantics or external commitments require a separate contract.

## 27.2 Canonical lock and transaction protocol

For an operation that may consume or release capacity on bound Resources, the baseline lock protocol is extended as follows:

```text
0. idempotency identity when applicable
1. existing business root/child rows required by the baseline command
2. collect the complete set of affected tenant-local Resources
3. deduplicate and lock all local Resources in stable UUID order
4. resolve active shared bindings only through the protected runtime surface
5. deduplicate and lock all corresponding SharedCapacityIdentity rows in stable UUID order
6. revalidate authoritative final capacity state
7. mutate CapacityClaim and dependent state
8. emit audit/outbox consequences
```

No shared root may be locked before an affected local Resource on a booking path. A command with no active binding has an empty shared-root step and therefore retains baseline behavior.

Reschedule collects `union(old Resource ids, new Resource ids)` before either releasing old claims or creating replacements, locks that whole local set, then locks the union of shared roots. This preserves self-overlap correctness and removes inverse old/new-root acquisition.

Control-plane binding activation/revocation follows `Resource → SharedCapacityIdentity`. Activation under those locks backfills private links for already-live local claims. Revocation does not delete claim links for already-committed live consumption.

The database capacity guard is the final cross-tenant backstop. Shared overlap fails with generic capacity-unavailable semantics and must not include the foreign Organization, Resource, Party, Reservation, Offering, root or claim identifier.

When Queue owns an outer SlotOffer issuance transaction and expected capacity loss must be converted into “close/advance opportunity”, speculative Hold/Claim acquisition executes in a nested transaction/savepoint. A shared-capacity conflict rolls back only those speculative writes before Queue continues its outer transaction. Catching `23P01` without restoring transaction usability is not a valid implementation.

## 27.3 Extension invariants

These invariants augment V3-I01..V3-I61 whenever this extension is present:

| ID | Invariant | Owner |
|---|---|---|
| V3-I62 | Global/shared identity and binding authority is explicit trusted control-plane authority; correlation or UUID knowledge grants no tenant binding/read authority | BOTH/ops |
| V3-I63 | Every live commitment created through an actively bound exclusive Resource serializes through its SharedCapacityIdentity while CapacityClaim remains the sole consumption truth | BOTH |
| V3-I64 | Tenant runtime cannot enumerate private global/shared state, and local versus foreign shared-capacity contention is externally indistinguishable except for generic availability/unavailability | DB+APP |
| V3-I65 | Binding activation/revocation/rebinding preserves live serialization provenance: activation backfills under locks, revocation preserves live links, and different-root rebinding is rejected while live provenance exists | BOTH |
| V3-I66 | Shared-capacity lock topology is deterministic: all affected local Resources stable-id ordered before all shared roots stable-id ordered; control-plane binding mutation uses Resource then shared root | APP protocol + DB primitive |

## 27.4 Extension race requirements

The canonical race inventory is extended by:

49. simultaneous overlapping commitments from two Organizations bound to one shared root → exactly one incompatible commitment commits;
50. direct Booking versus CapacityHold/SlotOffer across Organizations in both winner orders → one valid capacity owner and no false active offer/orphan Hold/Claim;
51. reschedule versus foreign shared commitment → conflicting reschedule rolls back completely and preserves the original Reservation/claim state;
52. binding activation/revocation versus live claim creation → one serial outcome with correct backfill/preserved provenance and no serialization gap;
53. inverse multi-Resource/multi-root acquisition, including simultaneous real reschedules touching old/new roots → deterministic local-Resource-then-shared-root order, no deadlock, and final claim cardinality/state is valid.

The release-level aliases for these races are `R25..R29` in `docs/release/v3-race-matrix.md`.

## 27.5 Extension construction gate

For a candidate that includes this extension, schema-construction gate item 2 expands from `V3-I01..V3-I61` to `V3-I01..V3-I66`, and the PostgreSQL concurrency gate includes races 49..53 / `R25..R29`.

The capability is not considered accepted merely because migrations apply. It must pass least-privilege privacy tests, cross-tenant booking/Hold/SlotOffer/reschedule evidence, binding-authority races, deterministic multi-root deadlock proof, repeated concurrency proof, test-order independence, mutation probes, bootstrap/equivalence checks and the executable evidence manifest on the final branch head.
