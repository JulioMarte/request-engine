# Request Engine V2.6 — arquitectura de referencia

> **Estado:** arquitectura objetivo. Schema freeze bloqueado hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> Documento padre: `docs/00-product-definition.md`.

---

## 1. Objetivo técnico

```text
Channels / Humans / Agents / Integrations
                   ↓
             Application layer
                   ↓
        deterministic domain rules
                   ↓
              PostgreSQL
                   ↓
       outbox / async integrations
```

El sistema mantiene autoridad bajo retries, duplicate/out-of-order callbacks, races de capacity, concurrent outcome writes, schedule/planning changes, authority revocation, late payments, financial corrections, multichannel handoffs y partial recovery.

---

## 2. Stack

- PostgreSQL: source of truth para tenant isolation, referential integrity, serialization authorities, capacity conflict protection, financial/outcome invariants, idempotency, audit y outbox.
- Python + FastAPI: domain/application/workers/integrations.
- SQLAlchemy + Alembic: persistence mapping y migrations.
- Pydantic → FastAPI → OpenAPI → generated SDKs.

No network calls dentro de authoritative DB transactions.

---

## 3. Modular monolith

```text
request-engine/
├── api/
├── domain/
│   ├── organizations/
│   ├── identity/
│   ├── offerings/
│   ├── requests/
│   ├── pricing/
│   ├── workflows/
│   ├── capacity/
│   ├── reservations/
│   ├── admission/
│   ├── schedules/
│   ├── locations/
│   ├── dispatch/
│   ├── payments/
│   └── fulfillment/
├── application/
├── infrastructure/
└── workers/
```

No microservices por módulo sin necesidad medida.

---

## 4. Dependency rule

```text
API / Worker / Integration / Agent adapter
                    ↓
             Application layer
                    ↓
                Domain rules
                    ↓
          Repository/interfaces
                    ↓
            PostgreSQL/adapters
```

External data necesaria para una transaction se obtiene antes y se representa mediante snapshot/reference/revision verificable, o se procesa después por compensation/outbox.

---

## 5. Aggregate/authority philosophy

Probable business roots:

```text
Organization
Party
Request
Offering
Resource
CapacityPool
CapacityHold
Reservation
PaymentRequirement
PaymentTransaction
Refund
PaymentDispute
ReconciliationCase
ServiceSession
Dispatch if lifecycle justifies it
```

Internal serialization identities/concepts:

```text
OutcomeScope
AdmissionScope mapping
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision
PlanningRevision
```

`FinancialObservation` y `ObservationCorrection` son append-oriented facts ligados a PaymentTransaction; no se diseñan como universal ledger.

No noun-to-table mapping automático.

---

## 6. Tenancy and typed references

Toda authoritative tenant-owned relation demuestra:

```text
child.organization_id == parent.organization_id
```

Prefer tenant-aware composite FKs where practical.

Forbidden para critical relationships:

```text
entity_type
entity_id
```

sin FK real.

Usar explicit typed links, real relational supertype o XOR-constrained typed FKs.

---

## 7. Identity and authority transaction semantics

Mutation authorization depende de:

```text
Principal
Organization
capability/scope
Party/subject correlation when relevant
current local Representation
entity state
policy/version
idempotency
```

Local Representation revocation y dependent mutation comparten lock/version authority.

External authority se materializa como verified snapshot/reference con source, verified_at, version/hash/reference, optional validity y locally-known revocation state.

Audit guarda exact Representation/policy snapshot usada.

---

## 8. Request serialization and completion validity

`Request` es serialization root para cambios que alteran required outcome obligations o lifecycle terminality.

`CompleteRequest`:

```text
LOCK Request
LOCK/read relevant OutcomeScopes in canonical order when completion depends on mutable outcome budgets
VALIDATE current Request revision + outcome criteria + current net valid Fulfillment contributions
WRITE Request.completed + completion decision provenance
EMIT audit/event/outbox
```

Una correction posterior no reabre Request. Re-evalúa `completion_validity` projection/materialized status y, si queda invalidated, emite recovery/review work.

Forbidden:

```text
completed Request silently continues to claim valid outcome after authoritative correction invalidates required fulfillment
```

---

## 9. OutcomeScope architecture — V2.6

`OutcomeScope` es stable serialization identity para una requested outcome obligation.

Debe identificar tipadamente suficiente scope para relacionar:

```text
Request
OfferingSelection
recipient/subject when applicable
FulfillmentModel/version
requested quantity/components
```

Puede implementarse como explicit relational entity o equivalente stable typed row; no se expone necesariamente como public API noun.

### RecordFulfillment protocol

```text
READ:
  Request/Selection/FulfillmentModel
  evidence/source

PLAN:
  affected OutcomeScope(s)

LOCK:
  OutcomeScope(s) canonical order
  Request when completion decision can race

VALIDATE:
  scope ownership/tenant
  model semantics
  current net valid contributions
  excess_policy for quantity
  evidence/source authority

WRITE:
  append Fulfillment

EMIT:
  audit/event/outbox
```

For `reject_excess`:

```text
net valid additive fulfillment <= requested quantity
```

For `allow_excess`, excess is recorded but remaining requested scope floors at zero; no negative “remaining” truth.

### CorrectFulfillment protocol

```text
LOCK affected OutcomeScope(s)
LOCK Request if completion validity may change
VALIDATE correction authority/reason/source
WRITE append correction/supersession lineage
RECOMPUTE current net outcome contribution
RE-EVALUATE completion_validity when Request already completed
EMIT recovery/review if invalidated
```

No destructive overwrite of historical outcome facts.

---

## 10. OfferingSelection / ReservationItem physical rule

`ReservationItem` references exactly one OfferingSelection.

A Selection may have many ReservationItems and span many Reservations through those items.

Do not allow an item to act as an untyped mini-package aggregating several selections.

---

## 11. Pricing and obligation derivation

`PriceDetermination` preserves typed scope, source/policy/version, Money, quantity semantics, adjustments, provenance y overrides.

`PaymentRequirement` preserves commercial basis + PaymentPolicy/version + calculation inputs + required Money.

No FX implicit.

Once a Requirement has financial use, required Money is not destructively changed by repricing.

### RepriceAfterCommitment

Preferred V1 semantics:

```text
LOCK affected commercial/Request scope
LOCK old PaymentRequirement(s) when financial consequences exist
VALIDATE policy + existing allocations
WRITE new PriceDetermination
WRITE replacement/new PaymentRequirement(s)
mark old business disposition/supersession as policy dictates
preserve allocation treatment/reconciliation lineage
EMIT amendment/audit/outbox
```

Do not rewrite old $100 requirement into $80 after $50 has already been allocated.

---

## 12. Capacity architecture

Domain:

```text
Resource
CapacityPool
CapacityHold
ResourceAllocation
ExternalCommitmentReference
```

Internal:

```text
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision
PlanningRevision
```

### CapacityAuthority

Stable row/identity que todas las operations que consumen/cambian misma capacity pueden identificar y lockear.

### CapacityClaim

Common conflict-space para Hold claims y active Allocation claims.

---

## 13. Local compound CapacityHold protocol

`CapacityHold` sólo promete atomicidad dentro de locally authoritative PostgreSQL capacity.

### CreateCapacityHold

```text
READ:
  Request/Selection snapshot
  requirement templates
  interval/location context

PLAN:
  complete local claim intents
  candidate authorities
  complete deterministic lock set

LOCK:
  CapacityAuthorities canonical order

VALIDATE:
  Request version/scope
  authority/config revisions
  schedule/location eligibility
  pool fungibility
  capability
  PlanningRevision/external feasibility when required
  live claims
  hold expiry policy

WRITE atomically:
  CapacityHold
  all mandatory local CapacityClaims
  requirement-intent lineage

EMIT audit/event/outbox
```

Failure of any mandatory local claim rolls back entire transaction.

---

## 14. External commitment protocol — no fake distributed atomicity

`ExternalCommitmentReference` represents inventory/partner/capacity commitment owned outside PostgreSQL.

Typical flow:

```text
1. request external lease/commitment idempotently
2. persist/obtain typed reference + valid_until/status/provenance
3. BEGIN local confirmation transaction
4. lock local roots/authorities
5. validate external reference snapshot still usable under policy
6. acquire/transform local commitments
7. create Reservation + external dependency links
8. COMMIT
9. if local commit fails after external lease: enqueue idempotent release/compensation
```

Request Engine promises local atomicity + explicit external dependency + compensation semantics, not distributed all-or-none.

External lease expiry racing local confirmation must be checked against authoritative local wall clock and available provider validity semantics immediately before local commit decision.

---

## 15. ConfirmReservation protocol

```text
LOCK:
  CapacityHold
  Request as required
  involved CapacityAuthorities canonical order

VALIDATE:
  Hold active/logically live
  Request/Selection still current
  complete mandatory local claim set
  authority revisions compatible
  required ExternalCommitmentReferences valid under policy
  every mandatory CommitmentRequirement will be covered

WRITE atomically:
  Reservation
  ReservationItems
  CommitmentRequirements
  ResourceAllocations
  transform/repoint local CapacityClaims
  link external commitments
  Hold → confirmed

EMIT audit/event/outbox
```

Forbidden:

```text
Reservation confirmed with missing mandatory local coverage
Reservation confirmed while required external commitment is known invalid/expired
```

---

## 16. Exclusive and unit capacity enforcement

### Interval semantics

Canonical capacity interval:

```text
[start_at, end_at)
start_at < end_at
```

No infinite/open-ended commitments V1.

Conflict interval includes setup/transition/cleanup buffers that actually block capacity; planned service interval remains separate.

### Exclusive

Preferred:

```text
common CapacityClaim relation
+ PostgreSQL range
+ exclusion constraint for logically-live incompatible claims
```

### Units

```text
LOCK CapacityAuthority
revalidate revisions
split/evaluate relevant schedule capacity change points
for every subinterval:
  sum logically-live overlapping claims + requested <= effective capacity
insert/transform claims
```

Checking capacity only at claim start is forbidden.

---

## 17. Hold expiry and wall clock

A Hold is logically live only when:

```text
state = active
AND expires_at > authoritative current time
```

Cleanup worker no define truth.

Expiry-sensitive checks occur immediately before authoritative transition and do not rely blindly on transaction-start `now()`.

Late payment never reactivates expired Hold.

---

## 18. Schedule/location/planning authority

Schedule/config mutations affecting reservability lock/increment same stable authority revision consumed by holds.

Includes:

```text
schedule edit
ScheduleException
capacity override
Resource unavailable
Resource operating-location eligibility
CapacityPool membership/fungibility
```

### PlanningRevision

For field-service feasibility, claims/allocations that can change adjacency/transition feasibility increment a monotonic PlanningRevision for the relevant planning authority/context.

External feasibility flow:

```text
read PlanningRevision = R
call external feasibility provider outside DB transaction
receive snapshot bound to R + exact inputs
BEGIN
lock CapacityAuthority/planning root
if current PlanningRevision != R:
    reject snapshot as stale / recompute
validate snapshot/policy
commit claim
increment PlanningRevision if resulting commitment changes planning state
COMMIT
```

This closes TOCTOU without network calls inside transaction.

If a deployment cannot define a bounded planning revision domain, it must use conservative local buffers instead of claiming authoritative external feasibility.

---

## 19. Canonical lock ordering

All multi-row authority operations use one deterministic total order.

Initial lock classes:

```text
REPRESENTATION
REQUEST
OUTCOME_SCOPE
RESERVATION
ADMISSION_SCOPE_ROOT
CAPACITY_HOLD
CAPACITY_AUTHORITY
SERVICE_SESSION
PAYMENT_TRANSACTION
PAYMENT_REQUIREMENT
FINANCIAL_REVERSAL_OR_CORRECTION
RECONCILIATION_CASE
```

Within class: ascending internal key or one documented total order.

PLAN complete lock set before acquisition when possible. PostgreSQL deadlock detection/retry is fallback.

---

## 20. CapacityPool binding

V1 only member-derived fungible pools.

Direct Resource claim and relevant Pool claim serialize together.

Pool realization uses non-consuming binding reference or atomic claim replacement preserving lineage.

Must prove:

```text
pool unit not double-counted
member not double-booked
claim lineage preserved
```

---

## 21. Shared requirements and partial cancellation

Reservation is structural serialization root.

```text
LOCK Reservation
PLAN surviving item/requirement scope
LOCK affected CapacityAuthorities canonical order
VALIDATE policy/session/admission + surviving coverage
WRITE releases/replacements atomically
terminal Reservation only after zero surviving commitment
EMIT amendment + financial consequences/outbox
```

Concurrent partial cancellations cannot release capacity still needed or leave orphan claims.

---

## 22. Atomic reschedule replacement

`RescheduleReservation` never releases old capacity before replacement is secured.

```text
PREPARE:
  create replacement CapacityHold for new local scope
  obtain required external commitments if any

BEGIN
  LOCK Reservation
  LOCK replacement CapacityHold
  LOCK old/new CapacityAuthorities canonical order
  VALIDATE current Reservation, policy, session/admission constraints
  VALIDATE replacement Hold/external dependencies
  WRITE replacement CommitmentRequirements/Allocations
  RELEASE/REPLACE old claims
  preserve old→new lineage and Amendment Contract
COMMIT
```

If replacement validation fails, original Reservation remains committed unless policy explicitly performs cancellation as a separate semantic decision.

---

## 23. Admission and queue concurrency

AdmissionScope does not require a universal aggregate, but every scope maps deterministically to a lock target:

```text
reservation-backed → ReservationItem
walk-in             → OfferingSelection/Request scope root
```

### JoinQueue

```text
LOCK AdmissionScope root
VALIDATE eligibility/current queue state
WRITE QueueEntry + ordering inputs
```

Default invariant:

```text
<= 1 active QueueEntry per AdmissionScope + admission context
```

unless versioned policy explicitly allows requeue/multi-queue semantics.

Persist ordering inputs, not absolute position. Position/ETA are projections.

Cancellation/check-in/start-session races lock the same admission root plus Reservation/ServiceSession where necessary.

---

## 24. ServiceSession and fulfillment coordination

Reservation ↔ ServiceSession is N:M.

Cancellation/reschedule conflicting with execution locks relevant Reservation + ServiceSession linkage/current state.

`CompleteServiceSession` does not automatically `CompleteRequest`.

A ServiceSession satisfying two Requests writes separate Fulfillment records to the respective OutcomeScopes.

---

## 25. Field-service destination mutation

`ChangeDispatchDestination`:

```text
LOCK Dispatch + relevant Reservation(s)
VALIDATE authority/policy/current dispatch state
WRITE before/after destination lineage
INVALIDATE prior external feasibility snapshot
if local conservative feasibility: re-evaluate synchronously
else mark blocked/pending external recheck
EMIT outbox/recovery
```

No route graph in core.

---

## 26. Amendment Contract implementation

No GenericAmendment aggregate.

Every material post-commitment command preserves:

```text
operation identity
initiator/represented Party
reason
policy/version
before refs/revisions
after refs/revisions
created/released/replaced links
evaluated inputs
override provenance
occurred_at
```

Typed command records + AuditRecord/DomainEvent are sufficient when material FKs remain in owning modules.

---

## 27. Financial architecture V2.6

### PaymentTransaction

Stable financial operation/value authority used to coordinate allocation/refund semantics.

It is distinct from the sequence of observations about that operation.

### FinancialObservation

Append-oriented knowledge fact.

```text
transaction
source/event identity
source-specific status
normalized finality
amount/value interpretation
occurred/effective_at
observed_at
source policy/version
provenance
```

### ObservationCorrection

Append-oriented correction of prior knowledge; does not claim a new movement of money.

### FinancialReversal

Separate financial fact for a later real return/reversal/invalidating financial event.

Current finality/eligible value are derived/materialized under versioned source policy from observations, corrections and reversals.

---

## 28. RecordFinancialObservation protocol

```text
AUTHENTICATE source/principal
DEDUPE provider event/observation identity where available
NORMALIZE under source policy/version

BEGIN
  LOCK PaymentTransaction value authority
  validate tenant/provider/account context
  append FinancialObservation
  derive new current financial interpretation/eligible value
  if eligible value drops below net allocations:
      deterministically create/require adjustment attribution when known
      otherwise open ReconciliationCase and mark financial condition inconsistent/under_review
  write audit/event/outbox
COMMIT
```

External facts are not rejected to preserve local allocation illusion.

Out-of-order observations append knowledge and are interpreted semantically, not by blind status overwrite.

---

## 29. ObservationCorrection protocol

```text
LOCK PaymentTransaction
LOCK affected observation/correction lineage as needed
LOCK affected PaymentAllocations when attribution known
VALIDATE correction authority/source/reason
WRITE ObservationCorrection
RECOMPUTE current eligible value
WRITE PaymentAllocationAdjustment(s) when deterministic
OR Open ReconciliationCase when ambiguous
EMIT audit/event/outbox
```

This is distinct from `RecordFinancialReversal`.

---

## 30. Manual financial verification

Manual verification is privileged semantic command.

Checks:

```text
Principal capability
Organization scope
source/account/cash context
amount/currency
evidence/reference
occurred_at/observed_at
policy/version
reason
idempotency
optional dual control
```

When four-eyes is required, first action creates pending review/evidence/observation candidate; distinct Principal approval is required before eligible authoritative value exists.

AI screenshot interpretation never calls the privileged verification command solely from visual inference.

---

## 31. Payment allocation and adjustments

### AllocatePayment

```text
LOCK PaymentTransaction
LOCK PaymentRequirements canonical order
VALIDATE current eligible value, currency, net allocations, requirement disposition
WRITE PaymentAllocation
```

```text
sum(net allocations) <= current eligible transaction value
```

### ApplyAllocationAdjustment

Source may be typed FinancialReversal or ObservationCorrection.

```text
LOCK source fact
LOCK affected PaymentAllocation(s)
VALIDATE source budget where monetary + allocation contribution budget
WRITE adjustment OR ReconciliationCase
```

Ambiguous attribution is never guessed.

---

## 32. Refund/reversal/dispute concurrency

Refund creation locks PaymentTransaction and validates:

```text
pending + succeeded refundable claims
<= currently refundable amount under policy/facts
```

External reversal/dispute/correction is always recorded even when it creates local deficit/inconsistency; recovery/reconciliation follows.

Original transaction, observations and Fulfillment remain historical.

---

## 33. Provider event ingestion

Preferred dedupe where provider guarantees event IDs:

```text
PaymentProviderConnection + provider_event_id
```

Flow:

```text
receive
→ authenticate/signature
→ dedupe envelope
→ persist safe raw/minimal reference
→ normalize to FinancialObservation / Refund / Dispute / Reversal semantics
→ execute internal command
→ record outcome
```

Same event identity + materially different payload = integrity/security conflict.

---

## 34. Idempotency

Persist conceptually:

```text
organization
operation
caller/context
idempotency key
canonical request hash
logical result reference
status
timestamps
```

Same key+same hash replays logical outcome. Same key+different hash conflicts. Current read authorization is always re-evaluated.

---

## 35. Transactional outbox

Business mutation + outbox append = same DB transaction.

Workers use row-claim protocol such as `FOR UPDATE SKIP LOCKED` where appropriate.

Delivery remains at-least-once; consumers are idempotent.

---

## 36. Projections

Derived/rebuildable unless future module proves otherwise:

```text
Availability
materialized slots
Queue position / ETA
Operational health
completion_validity
PaymentRequirement open/partial/satisfied/overdue
current PaymentTransaction finality/eligible value projection
remaining fulfillment scope
Resource utilization
```

No projection independently authorizes authoritative mutation without locked/versioned revalidation.

---

## 37. Required command proof catalogue

Before schema freeze document `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` for at least:

```text
CreateRequest
AddRequestParticipant
SelectOffering
UpdateOfferingSelectionBeforeCommitment
CompleteRequest
CreateCapacityHold
ReleaseCapacityHold
ConfirmReservation
CancelReservationScope
RescheduleReservation
ReplaceResourceAllocation
ChangeResourceAvailability
ChangeScheduleException
ChangeCapacityPoolMembership
CheckIn
JoinQueue
PromoteWaitlistEntry
StartServiceSession
CompleteServiceSession
RecordFulfillment
CorrectFulfillment
ChangeDispatchDestination
CreatePaymentRequirement
RepriceCommittedScope
RecordFinancialObservation
CorrectFinancialObservation
VerifyManualPayment
ApproveManualPaymentVerification
AllocatePayment
ApplyAllocationAdjustment
RequestRefund
RecordFinancialReversal
Open/ResolvePaymentDispute
Open/ResolveReconciliationCase
```

---

## 38. Required race/integration matrix

```text
cross-tenant FK rejection
hallucinated public ID tenant escape
Request completion vs outcome amendment
concurrent 6/10 + 6/10 Fulfillment reject_excess
allow_excess quantity semantics
Fulfillment correction after Request completion invalidates completion_validity
Fulfillment correction vs concurrent CompleteRequest
compound local Hold all-or-none across 3+ authorities
compound Hold final-claim rollback
concurrent compound Holds opposite input ordering
external lease succeeds + local Hold/confirmation fails → compensation
external commitment expiry vs confirmation
exclusive Hold-vs-Allocation overlap
unit capacity oversell
variable capacity change point crossing
adjacent [start,end) bookings do not overlap
schedule/location mutation vs Hold
pool membership vs Hold
pool vs direct member booking
Hold confirm vs expiry
Reservation confirm missing mandatory coverage rejection
shared requirement concurrent partial cancellation
atomic reschedule success
atomic reschedule replacement failure preserves original
Reservation close with active claims rejection
resource unavailable vs confirmation
check-in vs cancellation
start-session vs cancellation
concurrent Queue joins same AdmissionScope
Destination change invalidates feasibility
external feasibility PlanningRevision stale after intervening booking
one ServiceSession → multiple Requests/Fulfillments
repricing after partial allocation preserves old requirement history
PaymentEvidence cannot satisfy Requirement
PaymentAttempt success cannot satisfy Requirement
out-of-order FinancialObservations
ObservationCorrection reducing eligible value vs AllocatePayment
FinancialReversal vs ObservationCorrection distinction
manual verification unauthorized rejection
dual-control same-Principal rejection
PaymentAllocation overspend
partial reversal/correction adjustment budget race
refund-vs-refund
refund-vs-external reversal
provider duplicate event
same event id conflicting payload
late bank transfer after Hold expiry
concurrent reconciliation
idempotency same key/different payload
idempotent replay after authorization revocation
outbox duplicate delivery
DST ambiguous/nonexistent local time
```

---

## 39. Schema design gate

Antes de final SQL, `docs/02-pre-sql-domain-contract.md` debe mapear cada critical invariant a:

```text
FK/unique/check/exclusion constraint
stable lock authority + transaction protocol
optimistic revision protocol
bounded application policy where DB enforcement is impossible/incorrect
```

Una critical invariant defendida sólo por “the service checks first” bloquea schema freeze.
