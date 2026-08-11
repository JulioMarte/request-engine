# Request Engine V2.5 — contrato de dominio pre-SQL

> **Estado:** normativo. Schema freeze bloqueado hasta satisfacer este contrato.
>
> Este documento no diseña tablas finales. Define cardinalidades, semantic states, serialization roots, proof obligations e invariantes que el futuro PostgreSQL schema y transaction protocols deberán demostrar.

---

## 1. Readiness

V2.5 cierra semánticamente los blockers detectados en la revisión adversarial:

1. compound multi-resource commitment atomicity;
2. exact Fulfillment semantics;
3. financial observation/finality/eligible-value semantics;
4. post-commitment Amendment Contract;
5. Resource multi-location reservability;
6. admission/queue scope semantics;
7. field-service feasibility invalidation;
8. privileged manual financial verification.

Schema exploration is allowed. Schema freeze is not allowed until every proof below has a concrete enforcement strategy.

---

## 2. Normative cardinalities

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                    via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
External interaction identity N ── M Request

Request N ── M Reservation              via OfferingSelection/ReservationItem lineage
OfferingSelection N ── M Reservation    via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CapacityHold 1 ── 1..N mandatory/optional claim intents or physical CapacityClaims
CommitmentRequirement 1 ── 1..N ResourceAllocation

Reservation N ── M ServiceSession
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

`Reservation ↔ Participant` does not require an independent global relationship if requested/admission scope is unambiguous through typed links.

Physical persistence may introduce internal supertypes/claim rows without changing these semantic cardinalities.

---

## 3. Typed-reference contract

Critical authoritative relationships require enforceable referential integrity.

Forbidden:

```text
entity_type TEXT
entity_id BIGINT/TEXT
```

when DB cannot prove existence and tenant equality.

Applies especially to:

```text
RequestTarget
PriceDetermination scope
capacity authority target
Hold/requirement coverage
Fulfillment requested scope
financial provenance/source links
```

Allowed:

```text
explicit typed link table
real relational supertype
XOR-constrained typed foreign keys
```

Audit-only references may be looser only when they never establish business authority.

---

## 4. Tenant contract

For every critical tenant-owned relationship:

```text
child.organization_id == parent.organization_id
```

Must be DB-enforceable where authoritative.

Public IDs, external IDs, conversation IDs and idempotency tokens never grant authority.

Public lookups resolve tenant + identifier together.

---

## 5. Request lifecycle contract

States:

```text
active
waiting
completed
cancelled
failed_terminal
```

Terminal states are monotonic.

`CompleteRequest` and every command changing required outcome obligations serialize through the same Request root/version.

Forbidden race:

```text
T1 CompleteRequest sees requirements satisfied
T2 adds required outcome component
both commit
```

Expected: one wins; loser reloads and re-evaluates.

Opaque workflow JSON cannot be sole completion authority.

---

## 6. Party, Principal and Representation contract

Forbidden assumptions:

```text
Principal == Party
RequestParticipant role == authority
ExternalCorrelation == authority
external revocation is instantly serializable locally
```

Mutation depending on authority requires:

```text
authenticated/verified Principal
Organization match
capability/scope
Party/subject correlation when relevant
current locally materialized Representation
entity authorization
current entity state
policy/version
idempotency
```

Local Representation revocation and dependent mutation must share lock/version authority.

Audit preserves exact Representation/policy snapshot used.

---

## 7. Cross-channel contract

ExternalCorrelation is N:M and never grants authorization.

Forbidden uniqueness assumption:

```text
(org, channel, external_id) → exactly one Request
```

Durable operation identity may survive controlled Website → WhatsApp → Voice → Human handoff without becoming Party identity or bearer authority.

---

## 8. OfferingSelection and requested-scope contract

Each Selection preserves reconstructible:

```text
Offering/version
quantity
unit semantics
configuration
recipient scope
historical snapshot
```

Quantity without unit semantics is invalid.

Changes to requested scope after outcome obligations exist serialize through Request and preserve Amendment Contract provenance.

---

## 9. Fulfillment contract — normative definition

`ServiceSession` = execution.

`Fulfillment` = append-oriented application of outcome evidence to a requested scope belonging to exactly one Request.

Every Fulfillment must prove:

```text
Request exists in same tenant
requested scope belongs to Request
OfferingSelection link valid when present
recipient/subject scope valid when present
FulfillmentModel/version valid for scope
quantity/components/result valid for model
ServiceSession/external evidence source valid when present
provenance preserved
```

A single ServiceSession satisfying Requests A and B creates distinct Fulfillments F_A and F_B.

Correction never destructive-updates historical evidence as if prior outcome never existed; it preserves correction/supersession lineage.

Refund/reversal/dispute never deletes Fulfillment.

---

## 10. CommitmentRequirement contract

Offering configuration uses `ResourceRequirementTemplate`.

Reservation commitment uses materialized `CommitmentRequirement`.

Required traceability:

```text
Reservation
→ ReservationItem
↔ CommitmentRequirement
→ ResourceAllocation
→ capacity authority
```

Shared requirements consume capacity once.

Every mandatory ReservationItem requirement must remain sufficiently covered while Reservation is operationally valid.

---

## 11. CapacityAuthority contract

Every reservable Resource or CapacityPool requires one stable lockable capacity identity or equivalent proven mechanism.

Must include/associate:

```text
Organization
capacity model
current revision
current schedule/location/availability revision
active/config state
```

Every transaction capable of changing or consuming the same capacity must be able to identify and lock the same authority.

---

## 12. Common CapacityClaim contract

Holds and confirmed Allocations compete in one logical conflict space.

Preferred physical concept:

```text
organization
capacity_authority
origin kind/reference
interval
quantity
claim state
expires_at when hold-backed
```

Separate Hold and Allocation tables with independent conflict checks do not prove cross-type conflict safety unless an equivalent shared serialization mechanism is demonstrated.

---

## 13. Compound CapacityHold contract

`CapacityHold` is a commitment set.

A Hold may span multiple CapacityAuthorities and multiple future CommitmentRequirements.

### Atomicity invariant

For one mandatory commitment group:

```text
all mandatory claims are created
OR
zero mandatory claims are created
```

There is no externally visible active partial Hold caused by contention, validation failure or storage failure.

Partial commitment is legal only when workflow/policy explicitly partitions independent commitment groups before acquisition.

### CreateCapacityHold proof

Final design must show:

```text
READ complete intended scope
PLAN complete claim/lock set
LOCK all involved CapacityAuthorities in canonical order
VALIDATE all authorities/schedules/location/capability/fungibility/live claims
WRITE Hold + all mandatory claims in one transaction
```

No authority may be acquired by network call inside this transaction.

---

## 14. Exclusive capacity proof

Invariant:

> No incompatible logically-live exclusive claims overlap on the same CapacityAuthority.

Preferred proof:

```text
PostgreSQL range + exclusion constraint on common CapacityClaim relation
```

If another strategy is used, it must prove Hold-vs-Hold, Hold-vs-Allocation and Allocation-vs-Allocation overlap safety.

---

## 15. Unit capacity proof

Invariant:

```text
sum(overlapping logically-live hold claims + active allocation claims)
<= effective capacity
```

V1 protocol:

```text
LOCK CapacityAuthority
revalidate schedule/location/config revision
calculate overlapping logically-live claims
validate requested quantity
insert/transform claim
COMMIT
```

No check-then-insert outside authority lock.

---

## 16. Hold lifecycle and expiry

States:

```text
active
confirmed
released
expired
```

Allowed:

```text
active → confirmed
active → released
active → expired
```

No terminal → active.

Logical liveness:

```text
state = active
AND expires_at > authoritative wall-clock time
```

Cleanup worker does not define expiry truth.

Confirmation checks wall-clock liveness immediately before transition under relevant locks.

Late payment never reactivates expired Hold.

---

## 17. Hold confirmation / Reservation completeness contract

`ConfirmReservation` must atomically prove:

```text
Hold still active and logically live
required Request/Selection scope still valid
complete mandatory Hold claim set exists
all relevant authority revisions still compatible
all mandatory CommitmentRequirements will be fully covered
```

Then atomically create/confirm:

```text
Reservation
ReservationItems
CommitmentRequirements
ResourceAllocations
claim transformation/repointing
Hold → confirmed
```

Forbidden committed state:

```text
Reservation.status = confirmed
AND any mandatory CommitmentRequirement lacks sufficient active coverage
```

---

## 18. Schedule/location phantom-race contract

ScheduleException rows alone are not stable lock targets.

Any mutation affecting reservability must lock/increment the same stable authority revision consumed by Hold creation:

```text
AvailabilitySchedule edit
ScheduleException insert/update
capacity override
Resource unavailable
Resource operating-location eligibility
CapacityPool membership/eligibility
fungibility config
```

Expected serialization:

```text
claim wins → config change sees existing commitment and emits recovery
config wins → later claim sees revision and fails/recomputes
```

A Resource operating at multiple Locations remains one Resource; availability is contextual by Resource + location/service context + interval.

---

## 19. Canonical lock-order contract

Any transaction locking multiple authority rows uses one deterministic global order.

Initial lock classes:

```text
REPRESENTATION
REQUEST
RESERVATION
CAPACITY_HOLD
CAPACITY_AUTHORITY
SERVICE_SESSION
PAYMENT_TRANSACTION
PAYMENT_REQUIREMENT
FINANCIAL_REVERSAL
RECONCILIATION_CASE
```

Within class: ascending internal key or another single documented total order.

Commands must PLAN complete lock set before acquiring locks when possible.

Deadlock detection/retry is fallback, not primary design.

---

## 20. CapacityPool contract

V1 pools are member-derived and late-bind only fungible contributors.

Contributor capacity cannot feed overlapping reservable pools whose claims can conflict concurrently unless future design introduces a stronger shared authority protocol.

Direct Resource claim and relevant Pool claim must serialize together.

Pool claim + concrete realization is one consumption.

Non-fungible candidate sets bind concrete Resource during Hold/confirmation.

---

## 21. Reservation lifecycle contract

States:

```text
confirmed
cancelled
closed
```

Forbidden global states:

```text
completed
no_show
checked_in
waiting
in_service
en_route
```

Terminal invariant:

```text
Reservation.status IN {cancelled, closed}
→ zero active capacity-consuming claims/allocations
```

No generic status setter.

---

## 22. Partial cancellation/shared requirement contract

Reservation is serialization root for structural commitment amendment.

Concurrent cancellation of shared-item scope must not:

```text
release capacity still required by survivor
leave orphan active claim after all scope is cancelled
produce terminal Reservation with active claim
```

Protocol must lock Reservation, compute surviving scope, lock affected CapacityAuthorities in canonical order, atomically replace/release coverage and preserve Amendment Contract provenance.

---

## 23. AdmissionScope / CheckIn / Queue contract

AdmissionScope must identify the concrete recipient/item/Reservation or walk-in Request scope affected by CheckIn, QueueEntry and no-show.

`QueueEntry.position` must not be treated as durable unquestioned truth.

Persist ordering inputs/facts and derive current position/ETA.

Concurrent joins, priority changes and manual overrides must use deterministic ordering policy and preserve policy/override provenance.

Cancellation vs CheckIn and cancellation vs StartServiceSession must serialize safely against relevant Reservation/AdmissionScope/ServiceSession state.

---

## 24. ServiceSession contract

Reservation ↔ ServiceSession is N:M.

Cancellation/reschedule conflicting with execution must observe serialization-safe session linkage/current state.

Forbidden:

```text
Session starts work
concurrent cancellation commits as though execution never started
```

Policy decides reject, stop/partial, reschedule remainder or manual override after serialization.

Planned timestamps are distinct from actual timestamps.

---

## 25. Field-service feasibility contract

Request Engine V1 does not own route optimization.

Feasibility comes from:

```text
fixed/conservative transition rule
OR
external feasibility snapshot
```

External snapshot must preserve relevant inputs/provenance.

Material change to:

```text
Destination
planned interval
assigned Resource/vehicle
relevant schedule
```

invalidates prior feasibility authority.

Destination change after Dispatch planning preserves before/after lineage and cannot silently overwrite historical destination.

---

## 26. Amendment Contract

No `GenericAmendment` aggregate is required.

Every material post-commitment semantic command preserves:

```text
operation identity
initiator Principal / represented Party
reason
policy/version
before authoritative refs/revisions
after authoritative refs/revisions
created/released/replaced lineage
evaluated inputs
override provenance when applicable
occurred_at
```

Applies to at least:

```text
reschedule
partial cancellation
resource replacement
destination change
repricing
material payer/recipient correction
recovery after capacity loss
```

History is never rewritten to pretend prior committed state never existed.

---

## 27. PaymentRequirement contract

Business disposition:

```text
active
waived
cancelled
```

Derived/materialized labels:

```text
open
partial
satisfied
overdue
```

No manual `paid=true`.

Satisfaction is derived from net eligible allocations, not PaymentAttempt, PaymentEvidence or provider UI labels.

Refund does not automatically cancel Requirement; reversal may make active Requirement outstanding again.

---

## 28. PaymentTransaction observation/finality contract

Every authoritative PaymentTransaction must preserve enough semantics to answer:

```text
what direction of value?
what Money?
what source/provider/account?
what external transaction identity if available?
when did it occur/effect?
when was it observed?
what counterparty is known?
what financial state/finality is known?
what value is currently eligible for local allocation?
what source policy/version produced that interpretation?
what correction/reversal lineage applies?
```

Source-specific statuses are never assumed equivalent across rails.

Conceptual local financial knowledge must distinguish at least:

```text
observed_pending
observed_available
observed_final
```

Invalidation/reversal is represented by separate financial fact/history, not destructive rewrite.

`eligible value` is policy-derived from current authoritative financial facts/finality.

---

## 29. PaymentAttempt and PaymentEvidence contract

`PaymentAttempt.success` contributes zero allocatable value by itself.

`PaymentEvidence` contributes zero allocatable value by itself.

AI interpretation of screenshot/document can only create evidence or review work.

Only authoritative financial observation under configured source policy can create eligible value.

---

## 30. Payment allocation contract

PaymentTransaction N:M PaymentRequirement via PaymentAllocation.

Allocation requires:

```text
same Organization
currency match unless explicit future FX model
Requirement not incompatible by disposition/policy
transaction has sufficient current eligible value
```

Invariant:

```text
sum(current net eligible allocations from transaction)
<= current eligible transaction value
```

Allocation command locks PaymentTransaction/value authority and Requirements in canonical order where required.

---

## 31. Financial eligibility reduction race

If new financial observation/reversal reduces eligible value while another transaction allocates it, both operations must serialize against the same PaymentTransaction/value authority or equivalent lock set.

Forbidden:

```text
allocation reads eligible=100
reversal reduces eligible to 0
allocation still commits 100 without reconciliation/adjustment semantics
```

Final design must define whether reduction directly invalidates existing contribution through typed adjustment/reconciliation flow or first creates an over-allocated financial condition requiring deterministic recovery.

External financial facts are never rejected merely to preserve a local invariant illusion.

---

## 32. PaymentAllocationAdjustment contract

Two budgets:

### Reversal/source budget

```text
sum(adjustments attributed to FinancialReversal R)
<= R.amount
```

### Allocation contribution budget

```text
sum(invalidating adjustments against Allocation A)
<= A.eligible historical contribution
```

Creation locks source financial fact and affected allocations in canonical order.

Ambiguous attribution creates ReconciliationCase.

---

## 33. Refund contract

Lifecycle:

```text
requested
processing
succeeded
failed
cancelled
```

Refund creation serializes against original PaymentTransaction/value authority and enforces:

```text
pending + succeeded refundable claims
<= refundable amount permitted by current facts/policy
```

Void of uncaptured authorization is not Refund.

Concurrent external reversal must still be recorded; resulting deficit becomes reconciliation rather than discarded reality.

---

## 34. Manual financial verification contract

`manual_bank_verification` and `cash_verification` are privileged semantic operations.

They require:

```text
verifier Principal
explicit capability/scope
Organization/source/account/cash context
amount/currency
observed evidence/reference
occurred_at and observed_at
reason
policy/version
idempotency
```

If tenant policy requires dual control:

```text
verifier Principal A ≠ approving Principal B
```

No eligible authoritative financial value exists until required approval completes.

Agent runtime cannot self-elevate through tool choice or screenshot interpretation.

---

## 35. Provider callback contract

When provider guarantees event IDs, preferred uniqueness:

```text
(provider_connection, provider_event_id)
```

Same ID + same canonical payload → replay.

Same ID + materially different payload → integrity/security conflict.

Out-of-order events may append financial knowledge but never blindly regress state.

Webhook envelope authentication and domain authorization are distinct concerns.

---

## 36. Reconciliation contract

ReconciliationCase is required when matching, attribution, finality or treatment is uncertain.

Concurrent resolution uses row lock/version.

Two resolutions cannot consume or attribute the same financial value incompatibly.

No guess-based automatic match merely because amount/time look similar.

---

## 37. Idempotency contract

For scope S, key K, canonical hash H:

```text
unseen → execute and persist H/logical result
same H → replay logical result
other H → conflict
```

Replay rechecks current read authorization.

Transport idempotency and durable cross-channel operation identity are distinct.

Keys/tokens are not bearer authorization.

---

## 38. Outbox contract

Domain mutation + outbox append = same DB transaction.

Worker claim prevents concurrent processing of same row; delivery remains at-least-once.

Consumers must be idempotent.

No external side effect is assumed exactly-once.

---

## 39. Projection contract

The following are projections/derived state unless a future module proves otherwise:

```text
Availability
materialized slots
current Queue position
Queue ETA
Operational health
PaymentRequirement open/partial/satisfied/overdue
remaining fulfillment scope
Resource utilization
```

If materialized they are rebuildable and cannot independently authorize mutations without revalidation.

---

## 40. Required command proofs

Before schema freeze each critical command needs `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` documentation.

Required minimum:

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
RecordPaymentTransaction
VerifyManualPayment
ApproveManualPaymentVerification if policy requires
AllocatePayment
ApplyAllocationAdjustment
RequestRefund
RecordFinancialReversal
Open/ResolvePaymentDispute
Open/ResolveReconciliationCase
```

---

## 41. Invariant-to-enforcement matrix required before SQL freeze

The final schema design document must assign every invariant below to a concrete enforcement mechanism.

### Tenant / authority

```text
I01 no cross-tenant authoritative reference
I02 public/external IDs never grant authority
I03 participant role never grants authority
I04 local Representation revocation races serialize
I05 audit preserves exact authority/policy version
```

### Request / scope / outcome

```text
I06 terminal Request is monotonic
I07 completion serializes with required-outcome mutation
I08 RequestTarget type is valid for RequestType
I09 RequestTarget and generated lineage remain distinct
I10 Selection quantity has explicit unit semantics
I11 Fulfillment references exactly one valid Request scope
I12 Fulfillment correction preserves history
I13 remaining additive fulfillment scope cannot become negative without explicit correction semantics
```

### Capacity

```text
I14 every consuming commitment has authoritative claim lineage
I15 incompatible exclusive live claims never overlap
I16 unit claims never exceed effective capacity
I17 compound mandatory Hold is all-or-none
I18 expired/released Hold cannot confirm
I19 Hold and Allocation claims share conflict space
I20 Reservation confirmation cannot leave mandatory requirements under-covered
I21 shared requirement consumes capacity once
I22 partial cancellation cannot release surviving shared capacity
I23 pool claim + realization never double-consume
I24 direct Resource and Pool claim serialize
I25 non-fungible pools cannot remain unresolved late-bound
I26 schedule/location/membership change serializes with commitment
I27 terminal Reservation has zero active consuming claims
I28 all multi-authority lock sets use canonical total ordering
```

### Admission / execution / field service

```text
I29 no-show applies to explicit AdmissionScope
I30 Queue absolute position is not authoritative persisted truth
I31 planned and actual timestamps remain distinct
I32 cancellation conflicting with active execution serializes
I33 Destination material change preserves before/after lineage
I34 material field changes invalidate stale feasibility authority
```

### Amendments

```text
I35 every material post-commitment change preserves Amendment Contract provenance
I36 old committed facts are not destructively rewritten to simulate nonexistence
```

### Payments

```text
I37 PaymentEvidence creates zero eligible financial value
I38 PaymentAttempt success creates zero eligible financial value by itself
I39 PaymentTransaction identity/source/finality/provenance is reconstructible
I40 only policy-eligible transaction value satisfies Requirements
I41 net allocations cannot exceed eligible transaction value
I42 currency mismatch cannot allocate without explicit FX model
I43 adjustment cannot exceed allocation historical contribution
I44 reversal-sourced adjustments cannot exceed reversal amount
I45 original financial facts survive refund/reversal/dispute
I46 Refund and Requirement disposition are independent
I47 ambiguous financial treatment creates reconciliation
I48 manual financial verification requires privileged authority/provenance
I49 dual-control policy cannot be satisfied by same Principal
I50 financial eligibility reduction and concurrent allocation serialize/reconcile deterministically
```

### Callbacks / agents / platform

```text
I51 provider events dedupe within provider connection/account semantics
I52 same event ID with conflicting payload is integrity conflict
I53 idempotency same key+same hash replays logical result
I54 idempotency same key+different hash conflicts
I55 replay does not bypass current read authorization
I56 agent interpretation never grants authority
I57 hallucinated IDs cannot escape tenant boundary
I58 stale availability never authorizes commitment
I59 screenshot evidence cannot become settlement through AI inference
I60 business mutation + outbox append commit atomically
I61 external delivery is treated as at-least-once
```

---

## 42. Required race/integration tests

At minimum:

```text
cross-tenant typed FK rejection
hallucinated public ID tenant attack
compound hold all-or-none across 3+ authorities
compound hold final-claim failure rollback
concurrent compound holds opposite input ordering
exclusive Hold-vs-Allocation overlap
unit capacity oversell
schedule exception vs Hold
Resource location change vs Hold
pool membership vs Hold
pool vs direct member booking
Hold confirm vs expiry
payment arrives after Hold expiry
Reservation confirm missing requirement coverage rejection
shared requirement concurrent partial cancellation
Reservation close with active claims rejection
resource unavailable vs confirmation
Request completion vs outcome amendment
Representation revocation vs mutation
cancellation vs check-in
cancellation vs StartServiceSession
concurrent Queue joins/priority override
Destination change vs Dispatch state
Destination mutation invalidates feasibility
Fulfillment vs scope amendment
one ServiceSession → multiple Requests/Fulfillments
Fulfillment correction lineage
PaymentEvidence cannot satisfy Requirement
PaymentAttempt success cannot satisfy Requirement
out-of-order pending/available/final financial observations
financial eligibility reduction vs AllocatePayment
manual verification unauthorized rejection
dual-control same-Principal rejection
PaymentAllocation overspend
partial reversal budget race
refund-vs-refund
refund-vs-external reversal
duplicate provider event
duplicate event ID conflicting payload
late bank transfer after Hold expiry
concurrent ReconciliationCase resolution
idempotency same key/different payload
idempotent replay after authorization revocation
outbox duplicate delivery
DST ambiguous and nonexistent local times
```

---

## 43. Freeze decision

Schema freeze is permitted only when each I01–I61 has an explicit proof classified as one of:

```text
DB constraint (FK/unique/check/exclusion)
stable row-lock authority + transaction protocol
optimistic version protocol
bounded application policy because physical DB enforcement is neither possible nor semantically desirable
```

For every invariant using locks, the command document must identify the lock target and canonical order.

For every invariant delegated to application policy, the architecture review must explain why a DB invariant would be incorrect or impossible.

If a critical rule is defended only by “the service checks first”, schema freeze remains blocked.
