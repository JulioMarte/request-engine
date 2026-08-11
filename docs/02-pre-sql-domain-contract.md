# Request Engine V2.6 — contrato de dominio pre-SQL

> **Estado:** normativo. Schema freeze bloqueado hasta satisfacer este contrato.
>
> Este documento no diseña tablas finales. Define cardinalidades, semantic states, serialization roots, transaction proofs e invariantes que el futuro PostgreSQL schema deberá demostrar.

---

## 1. Readiness

V2.6 incorpora los findings de la segunda revisión adversarial y cierra semánticamente:

1. concurrent Fulfillment/outcome-budget serialization;
2. completion invalidation after Fulfillment correction;
3. FinancialObservation vs PaymentTransaction vs real FinancialReversal;
4. ObservationCorrection semantics;
5. external field-service feasibility TOCTOU via PlanningRevision;
6. local atomic commitments vs external commitment dependencies;
7. ReservationItem → OfferingSelection cardinality;
8. immutable PaymentRequirement amount after financial use;
9. atomic replacement reschedule;
10. AdmissionScope lock mapping;
11. canonical `[start,end)` capacity interval semantics;
12. variable capacity across schedule change points.

Schema exploration is allowed. Schema freeze is not allowed until every critical proof has a concrete enforcement strategy.

---

## 2. Normative cardinalities

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
External interaction identity N ── M Request

OfferingSelection 1 ── 0..N OutcomeScope
OfferingSelection 1 ── 0..N ReservationItem
ReservationItem N ── 1 OfferingSelection
Request N ── M Reservation via ReservationItem lineage

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CommitmentRequirement 1 ── 1..N ResourceAllocation
CapacityHold 1 ── 1..N local CapacityClaims
Reservation 1 ── 0..N ExternalCommitmentReference

Reservation N ── M ServiceSession
OutcomeScope 1 ── 0..N Fulfillment
Request 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction 1 ── 1..N FinancialObservation
PaymentTransaction 1 ── 0..N ObservationCorrection
PaymentTransaction 1 ── 0..N FinancialReversal
PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

`Reservation ↔ Participant` does not require an independent global relation if requested/admission scope is unambiguous through typed links.

---

## 3. Typed-reference contract

Critical authoritative relationships require enforceable referential integrity.

Forbidden when used for authority/invariants:

```text
entity_type TEXT
entity_id BIGINT/TEXT
```

without DB-provable target existence + tenant equality.

Applies especially to:

```text
RequestTarget
PriceDetermination scope
OutcomeScope requested scope
ReservationItem → OfferingSelection
capacity authority target
Hold/requirement coverage
ExternalCommitmentReference scope
financial observation/correction/reversal lineage
```

Allowed strategies:

```text
explicit typed link tables
real relational supertype
XOR-constrained typed FKs
```

---

## 4. Tenant contract

For every critical tenant-owned relationship:

```text
child.organization_id == parent.organization_id
```

Must be DB-enforceable where authoritative.

Public IDs, external IDs, conversation IDs and idempotency tokens never grant authority.

Public lookup resolves tenant + identifier together.

---

## 5. Request lifecycle and completion-validity contract

Request states:

```text
active
waiting
completed
cancelled
failed_terminal
```

Terminal states are monotonic.

`CompleteRequest` and every command changing required outcome obligations serialize through Request root/version.

`completed` records a historical authoritative completion decision; it is not reopened by later correction.

Derived/materialized `completion_validity`:

```text
valid
under_review
invalidated
```

If authoritative outcome correction causes previously satisfied required criteria to become unsatisfied:

```text
Request remains completed
completion_validity becomes invalidated/under_review
recovery/review work is emitted according to policy
```

Forbidden:

```text
Fulfillment correction invalidates required outcome
AND Request remains externally represented as currently valid completion without any invalidation/recovery signal
```

---

## 6. Party, Principal and Representation contract

Forbidden assumptions:

```text
Principal == Party
RequestParticipant role == authority
ExternalCorrelation == authority
external revocation is instantly serializable locally
```

Authority-dependent mutation requires authenticated/verified Principal, tenant match, capability/scope, relevant Party/subject correlation, current local Representation, current entity state, policy/version and idempotency.

Local Representation revocation and dependent mutation share lock/version authority.

Audit preserves exact Representation/policy snapshot used.

---

## 7. Cross-channel contract

ExternalCorrelation is N:M and never grants authorization.

Durable operation identity may survive Website → WhatsApp → Voice → Human handoff without becoming bearer authority.

---

## 8. OfferingSelection / ReservationItem contract

Each OfferingSelection preserves reconstructible Offering/version, quantity, unit semantics, configuration, recipient scope and historical snapshot.

Quantity without unit semantics is invalid.

Each ReservationItem references exactly one OfferingSelection.

Forbidden:

```text
one ReservationItem → multiple OfferingSelections
```

If multiple commercial components must behave as one package, that packaging belongs in Offering/package semantics.

---

## 9. OutcomeScope contract

Every independently mutable requested outcome budget/scope requires one stable serialization identity or equivalent stable typed row.

An OutcomeScope must prove association to:

```text
Organization
Request
OfferingSelection
recipient/subject when applicable
FulfillmentModel/version
requested quantity/components/result semantics
```

Every operation capable of changing current outcome contribution or required outcome must identify the same OutcomeScope lock target.

OutcomeScope may remain internal and not appear in public APIs.

---

## 10. Fulfillment contract

`ServiceSession` = execution.

`Fulfillment` = append-oriented application of outcome evidence to one OutcomeScope belonging to exactly one Request.

Every Fulfillment proves:

```text
Request/OutcomeScope same tenant
scope belongs to Request
OfferingSelection link valid
recipient/subject scope valid when present
FulfillmentModel/version valid
quantity/components/result valid
ServiceSession/external evidence source valid when present
provenance preserved
```

Corrections preserve lineage; no destructive historical rewrite.

Refund/reversal/dispute never deletes Fulfillment.

---

## 11. Concurrent outcome-budget proof

For additive quantity model with `reject_excess`:

```text
sum(current net valid Fulfillment contribution for OutcomeScope)
<= requested quantity
```

Protocol:

```text
LOCK OutcomeScope
recompute current net valid contribution
validate new contribution/correction
append fact
COMMIT
```

Two concurrent 6/10 Fulfillments cannot both commit under `reject_excess`.

For `allow_excess`, excess may be recorded explicitly; derived remaining requested quantity floors at zero and is never authoritative negative work.

Components/binary models also serialize when concurrent writes could create incompatible current outcome truth.

---

## 12. Fulfillment correction vs completion proof

`CorrectFulfillment` affecting a completed Request must serialize against:

```text
OutcomeScope
Request/completion decision boundary
```

It must:

```text
append correction/supersession
recompute current outcome truth
re-evaluate completion_validity
emit recovery/review if required outcome no longer holds
```

It must not reopen terminal Request automatically.

Concurrent `CompleteRequest` vs `CorrectFulfillment` must have one serialization order; loser reloads/re-evaluates.

---

## 13. CommitmentRequirement contract

Offering configuration uses ResourceRequirementTemplate.

Reservation commitment uses materialized CommitmentRequirement.

Traceability:

```text
Reservation
→ ReservationItem
↔ CommitmentRequirement
→ ResourceAllocation
→ capacity authority
```

Shared requirement consumes capacity once.

Every mandatory requirement remains sufficiently covered while Reservation is operationally valid.

---

## 14. CapacityAuthority / CapacityClaim contract

Every reservable Resource or CapacityPool has one stable lockable capacity identity or equivalent proven mechanism.

Common CapacityClaim conflict-space includes Hold-backed and Allocation-backed claims.

Separate conflict spaces are insufficient unless an equivalent shared serialization proof exists.

---

## 15. Canonical interval contract

Capacity commitments V1 use:

```text
[start_at, end_at)
start_at < end_at
```

Adjacent intervals such as `[10:00,11:00)` and `[11:00,12:00)` do not overlap.

No zero-duration, infinite or open-ended consuming claims V1.

Planned service interval and capacity conflict interval are distinct when setup/transition/cleanup buffers consume capacity.

---

## 16. Local compound CapacityHold contract

CapacityHold is a local commitment set.

For one mandatory local commitment group:

```text
all mandatory local claims are created
OR
zero are created
```

No externally visible active partial Hold caused by contention/storage failure.

CreateCapacityHold proof:

```text
READ complete intended scope
PLAN complete local claim + lock set
LOCK CapacityAuthorities canonical order
VALIDATE revisions/schedules/location/capability/fungibility/planning/live claims
WRITE Hold + all mandatory local claims one transaction
```

Partial commitment only when workflow partitions independent groups before acquisition.

---

## 17. Exclusive capacity proof

Invariant:

> No incompatible logically-live exclusive claims overlap on same CapacityAuthority.

Preferred proof: PostgreSQL range + exclusion constraint over common CapacityClaim relation.

Must cover Hold-vs-Hold, Hold-vs-Allocation and Allocation-vs-Allocation.

---

## 18. Unit and variable capacity proof

Invariant applies throughout interval:

```text
for each relevant subinterval/change point:
sum(logically-live claims) <= effective capacity
```

Protocol:

```text
LOCK CapacityAuthority
revalidate schedule/config revision
derive capacity change points intersecting requested interval
evaluate overlapping live claims in every segment
insert/transform only if every segment is safe
```

Checking capacity only at `start_at` is forbidden.

---

## 19. Hold lifecycle / expiry contract

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

Logical liveness:

```text
state = active
AND expires_at > authoritative wall-clock time
```

Cleanup worker does not define expiry truth.

Late payment never reactivates expired Hold.

---

## 20. ExternalCommitmentReference contract

External inventory/partner/capacity authority is not represented as if locally atomic.

Typed reference preserves at least:

```text
Organization
provider/connection
external commitment identity
covered scope
status
verified_at
valid_until/expiry when known
source policy/version
provenance
release/compensation capability when known
```

Reservation confirmation may depend on such reference only under explicit versioned policy.

No distributed all-or-none guarantee is claimed.

If external lease succeeds and local transaction fails, compensation/release is scheduled idempotently via outbox/recovery.

If compensation fails, retained external commitment is visible operationally/reconcilable; it is not hidden.

---

## 21. Hold confirmation / Reservation completeness contract

ConfirmReservation atomically proves:

```text
Hold logically live
Request/Selection scope current
complete mandatory local claim set
relevant local revisions compatible
required external commitment references currently acceptable by policy
all mandatory CommitmentRequirements fully covered
```

Then atomically writes Reservation, ReservationItems, CommitmentRequirements, ResourceAllocations, local claim transformation, external dependency links and Hold→confirmed.

Forbidden:

```text
Reservation confirmed with mandatory local under-coverage
Reservation confirmed using known-expired required external commitment
```

---

## 22. Schedule/location phantom-race contract

Any mutation affecting reservability locks/increments stable authority revision:

```text
AvailabilitySchedule edit
ScheduleException insert/update
capacity override
Resource unavailable
Resource operating-location eligibility
CapacityPool membership/fungibility
```

Claim wins → config mutation sees commitment and emits recovery.

Config wins → later claim sees new revision and fails/recomputes.

---

## 23. PlanningRevision / external feasibility contract

External field-service feasibility must be bound to a monotonic PlanningRevision over the bounded planning authority/context whose commitments influence that decision.

Flow:

```text
read revision R
perform external feasibility query outside transaction using exact inputs
receive snapshot bound to R
BEGIN
lock planning/capacity authority
if current revision != R → snapshot stale, reject/recompute
validate snapshot/policy
write commitment
increment revision when planning state changes
COMMIT
```

A new/released/replaced commitment capable of changing adjacency/transition feasibility increments relevant PlanningRevision.

If the implementation cannot define a correct bounded revision domain, authoritative external feasibility is not supported; use conservative local buffers.

---

## 24. Canonical lock-order contract

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

Within class: one documented total order.

Commands PLAN complete lock set before acquisition where possible.

Deadlock detection/retry is fallback.

---

## 25. CapacityPool contract

V1 pools are member-derived and late-bind only fungible contributors.

Contributor capacity cannot feed conflicting overlapping reservable pools unless a stronger shared protocol is introduced.

Direct Resource claim and relevant Pool claim serialize together.

Pool claim + concrete realization is one consumption.

---

## 26. Reservation lifecycle contract

```text
confirmed
cancelled
closed
```

Terminal:

```text
Reservation.status IN {cancelled, closed}
→ zero active local capacity-consuming claims/allocations
```

No generic status setter.

---

## 27. Partial cancellation/shared requirement contract

Reservation is serialization root for structural commitment amendment.

Concurrent cancellations cannot release survivor capacity, leave orphan active claim or produce terminal Reservation with active claim.

Protocol locks Reservation, computes surviving scope, locks affected CapacityAuthorities canonical order and writes replacements/releases atomically with Amendment Contract provenance.

---

## 28. Atomic reschedule contract

Reschedule uses replacement-before-release semantics.

Required flow:

```text
prepare replacement CapacityHold + external commitments
BEGIN
lock Reservation
lock replacement Hold
lock old/new CapacityAuthorities canonical order
validate original + replacement + policy/session/admission constraints
confirm replacement commitments
release/replace old allocations
preserve lineage
COMMIT
```

If replacement fails, original commitment remains unless a separate explicit cancellation policy/action says otherwise.

Forbidden:

```text
release original first → replacement fails → accidental loss of reservation
```

---

## 29. AdmissionScope / Queue contract

AdmissionScope maps deterministically to lock root:

```text
reservation-backed → ReservationItem
walk-in             → OfferingSelection/Request scope root
```

Default invariant:

```text
<= 1 active QueueEntry per AdmissionScope + admission context
```

unless versioned policy explicitly allows otherwise.

Queue absolute position is not persisted authoritative truth. Persist ordering inputs/facts and derive position/ETA.

Cancellation vs CheckIn and cancellation vs StartServiceSession serialize against relevant admission root + Reservation/ServiceSession.

No-show applies to explicit AdmissionScope.

---

## 30. ServiceSession contract

Reservation ↔ ServiceSession is N:M.

Cancellation/reschedule conflicting with active execution must observe serialization-safe linkage/current session state.

Planned timestamps remain distinct from actual timestamps.

CompleteServiceSession does not imply CompleteRequest.

---

## 31. Field-service destination contract

Material Destination change after Dispatch planning preserves before/after lineage and invalidates prior feasibility authority.

ChangeDispatchDestination does not silently overwrite historical destination.

No route optimizer in core.

---

## 32. Amendment Contract

Every material post-commitment semantic command preserves:

```text
operation identity
initiator Principal / represented Party
reason
policy/version
before refs/revisions
after refs/revisions
created/released/replaced lineage
evaluated inputs
override provenance
occurred_at
```

Applies to reschedule, partial cancellation, resource replacement, destination change, repricing, payer/recipient material correction, recovery and external commitment replacement.

No GenericAmendment aggregate required.

---

## 33. PaymentRequirement contract

Business disposition:

```text
active
waived
cancelled
```

Derived labels:

```text
open
partial
satisfied
overdue
```

No manual `paid=true`.

After a Requirement has financial use/allocation, `required Money` is historical and not destructively changed by repricing.

Repricing creates replacement/new obligation consequences with explicit policy and lineage.

---

## 34. PaymentTransaction / FinancialObservation contract

`PaymentTransaction` is stable financial operation/value authority.

It is not the mutable latest provider status.

Every current financial interpretation is based on append-oriented `FinancialObservation`s preserving:

```text
source/event identity
source-specific status
normalized finality
amount/value interpretation
occurred/effective_at
observed_at
source policy/version
provenance
```

Current finality/eligible value may be materialized but must be reproducible from authoritative facts/policy or explicitly versioned interpretation.

---

## 35. ObservationCorrection contract

`ObservationCorrection` corrects/invalidate prior knowledge without asserting a new movement of money.

Examples:

```text
duplicate feed observation
wrong manual verification
misidentified transaction
provider correction of prior interpretation
```

It preserves source/authority/reason/target observation lineage.

`ObservationCorrection` is not `FinancialReversal`.

---

## 36. FinancialReversal contract

FinancialReversal/Return is a separate later financial fact representing actual returned/reversed/invalidated value movement/event according to source semantics.

Original PaymentTransaction/observations remain historical.

---

## 37. Financial eligibility contract

Conceptual normalized knowledge distinguishes at least:

```text
observed_pending
observed_available
observed_final
```

Only value eligible under versioned source policy can satisfy PaymentRequirements.

PaymentAttempt success contributes zero eligible value by itself.

PaymentEvidence contributes zero eligible value by itself.

AI screenshot/document interpretation cannot create eligible value.

---

## 38. Financial eligibility reduction contract

Any FinancialObservation, ObservationCorrection or FinancialReversal that can reduce current eligible value must serialize against same PaymentTransaction value authority as AllocatePayment.

If new eligible value becomes less than current net allocations:

1. deterministic attribution → create typed PaymentAllocationAdjustment(s) within same/controlled transaction protocol; or
2. ambiguous attribution → open ReconciliationCase and expose an under_review/inconsistent financial condition.

External truth is never rejected to keep local allocation invariant artificially true.

No silent negative/overallocated state without recovery/reconciliation visibility.

---

## 39. PaymentAllocation contract

PaymentTransaction N:M PaymentRequirement via PaymentAllocation.

Allocation requires same Organization, compatible currency, compatible Requirement disposition/policy and sufficient current eligible value.

Invariant at allocation commit:

```text
sum(current net eligible allocations from transaction)
<= current eligible transaction value
```

Allocation locks PaymentTransaction and Requirements in canonical order where needed.

---

## 40. PaymentAllocationAdjustment contract

Adjustment may be sourced by typed FinancialReversal or ObservationCorrection.

Allocation budget:

```text
sum(invalidating adjustments against Allocation A)
<= A.eligible historical contribution
```

For monetary reversal source:

```text
sum(adjustments attributed to FinancialReversal R)
<= R.amount
```

Creation locks source fact + affected allocations.

Ambiguous attribution creates ReconciliationCase.

---

## 41. Refund contract

```text
requested
processing
succeeded
failed
cancelled
```

Refund creation serializes against PaymentTransaction and enforces pending+succeeded refundable claims <= currently refundable amount under policy/facts.

Void of uncaptured authorization is not Refund.

External reversal/correction still records reality even if it causes deficit/reconciliation.

Refund and PaymentRequirement disposition remain independent.

---

## 42. Manual financial verification contract

Privileged operation requires:

```text
verifier Principal
explicit capability/scope
Organization/source/account/cash context
amount/currency
evidence/reference
occurred_at/observed_at
reason
policy/version
idempotency
```

If dual control required:

```text
verifier A != approver B
```

No eligible authoritative value exists before required approval.

Wrong approved verification is corrected by ObservationCorrection, not destructive deletion.

---

## 43. Provider callback contract

Preferred uniqueness when provider guarantees event IDs:

```text
(provider_connection, provider_event_id)
```

Same ID + same canonical payload → replay.

Same ID + materially different payload → integrity/security conflict.

Webhook envelope authentication and domain authorization/interpretation are distinct.

Provider events normalize into typed domain semantics, especially FinancialObservation, Refund, Dispute or FinancialReversal; payload is not direct generic status mutation.

---

## 44. Reconciliation contract

ReconciliationCase required when matching, attribution, finality, correction effect or treatment is uncertain.

Concurrent resolution uses row lock/version.

Two resolutions cannot consume/attribute same value incompatibly.

No guess-based match merely because amount/time look similar.

---

## 45. Idempotency contract

For scope S, key K, canonical hash H:

```text
unseen → execute and persist H/logical result
same H → replay logical result
other H → conflict
```

Replay rechecks current read authorization.

Transport idempotency and durable cross-channel operation identity are distinct.

---

## 46. Outbox contract

Domain mutation + outbox append = same DB transaction.

Worker claim prevents concurrent processing of same row; delivery remains at-least-once.

Consumers idempotent.

External commitment compensation/release is also at-least-once and idempotent.

---

## 47. Projection contract

Derived/rebuildable state includes:

```text
Availability
materialized slots
Queue position/ETA
Operational health
completion_validity
PaymentRequirement open/partial/satisfied/overdue
current PaymentTransaction finality/eligible value interpretation
remaining fulfillment scope
Resource utilization
```

If materialized, projections are not arbitrary write endpoints and never independently authorize mutation without revalidation.

---

## 48. Required command proofs

Before schema freeze document READ / PLAN / LOCK / VALIDATE / WRITE / EMIT for:

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

## 49. Invariant-to-enforcement matrix required before SQL freeze

### Tenant / authority

```text
I01 no cross-tenant authoritative reference
I02 public/external IDs never grant authority
I03 participant role never grants authority
I04 local Representation revocation races serialize
I05 audit preserves exact authority/policy version
```

### Request / outcome

```text
I06 terminal Request is monotonic
I07 completion serializes with required-outcome mutation
I08 completion correction can invalidate completion_validity without reopening Request
I09 RequestTarget type valid for RequestType
I10 RequestTarget and generated lineage remain distinct
I11 Selection quantity has explicit unit semantics
I12 ReservationItem references exactly one OfferingSelection
I13 every mutable requested outcome has stable OutcomeScope serialization identity
I14 Fulfillment references exactly one valid OutcomeScope/Request
I15 Fulfillment correction preserves history
I16 reject_excess additive outcome cannot over-fulfill concurrently
I17 allow_excess never creates negative authoritative remaining scope
I18 CorrectFulfillment vs CompleteRequest serializes
```

### Capacity / commitments

```text
I19 every local consuming commitment has authoritative claim lineage
I20 incompatible exclusive live claims never overlap
I21 unit claims never exceed effective capacity over any relevant subinterval
I22 capacity interval semantics are [start,end) with start<end
I23 compound mandatory local Hold is all-or-none
I24 expired/released Hold cannot confirm
I25 Hold and Allocation claims share conflict space
I26 Reservation confirmation cannot leave mandatory local requirements under-covered
I27 shared requirement consumes capacity once
I28 partial cancellation cannot release surviving shared capacity
I29 pool claim + realization never double-consume
I30 direct Resource and Pool claim serialize
I31 non-fungible pools cannot remain unresolved late-bound
I32 schedule/location/membership change serializes with local commitment
I33 external commitments are explicit dependencies, not represented as local atomic claims
I34 failed local transaction after external lease produces compensation/recovery work
I35 terminal Reservation has zero active local consuming claims
I36 all multi-authority lock sets use canonical total ordering
I37 reschedule replacement failure preserves original commitment
```

### Field service / admission / execution

```text
I38 external feasibility snapshot is bound to PlanningRevision
I39 relevant intervening commitment invalidates stale feasibility snapshot
I40 Destination material change preserves before/after lineage and invalidates feasibility
I41 no-show applies to explicit AdmissionScope
I42 AdmissionScope maps deterministically to lock root
I43 default active QueueEntry uniqueness holds per AdmissionScope/context
I44 Queue absolute position is not authoritative persisted truth
I45 planned and actual timestamps remain distinct
I46 cancellation conflicting with active execution serializes
```

### Amendments / pricing

```text
I47 every material post-commitment change preserves Amendment Contract provenance
I48 old committed facts are not destructively rewritten
I49 PaymentRequirement required Money is not destructively repriced after financial use
```

### Payments

```text
I50 PaymentEvidence creates zero eligible value
I51 PaymentAttempt success creates zero eligible value by itself
I52 PaymentTransaction identity is distinct from FinancialObservation history
I53 FinancialObservation source/finality/provenance is reconstructible
I54 ObservationCorrection is distinct from FinancialReversal
I55 only policy-eligible financial value satisfies Requirements
I56 net allocations cannot exceed eligible value at allocation commit
I57 currency mismatch cannot allocate without explicit FX
I58 eligibility reduction serializes with allocation
I59 deterministic eligibility reduction creates typed adjustments; ambiguous reduction creates reconciliation
I60 adjustment cannot exceed allocation historical contribution
I61 reversal-sourced adjustments cannot exceed reversal amount
I62 original financial facts/observations survive refund/reversal/correction/dispute
I63 Refund and Requirement disposition are independent
I64 manual verification requires privileged authority/provenance
I65 dual-control policy cannot be satisfied by same Principal
```

### Callbacks / agents / platform

```text
I66 provider events dedupe within provider connection/account semantics
I67 same event ID with conflicting payload is integrity conflict
I68 idempotency same key+same hash replays logical result
I69 idempotency same key+different hash conflicts
I70 replay does not bypass current read authorization
I71 agent interpretation never grants authority
I72 hallucinated IDs cannot escape tenant boundary
I73 stale availability never authorizes commitment
I74 screenshot evidence cannot become settlement through AI inference
I75 business mutation + outbox append commit atomically
I76 external delivery/compensation is treated as at-least-once
```

---

## 50. Required race/integration tests

At minimum:

```text
cross-tenant typed FK rejection
hallucinated public ID tenant attack
Request completion vs outcome amendment
concurrent 6/10 + 6/10 Fulfillment reject_excess
allow_excess quantity behavior
CorrectFulfillment after completion invalidates completion_validity
CorrectFulfillment vs concurrent CompleteRequest
Fulfillment correction lineage
one ServiceSession → multiple Requests/Fulfillments
compound Hold all-or-none 3+ authorities
compound Hold final-claim rollback
concurrent compound Holds opposite input ordering
exclusive Hold-vs-Allocation overlap
unit capacity oversell
variable capacity change-point crossing
adjacent [start,end) capacity claims
schedule exception vs Hold
Resource location change vs Hold
pool membership vs Hold
pool vs direct member booking
Hold confirm vs expiry
payment arrives after Hold expiry
Reservation confirm missing mandatory coverage rejection
external lease succeeds + local failure → compensation
external commitment expires before confirmation
shared requirement concurrent partial cancellation
atomic reschedule success
atomic reschedule replacement failure preserves original
Reservation close with active claims rejection
resource unavailable vs confirmation
external feasibility revision changes after provider check
Destination mutation invalidates feasibility
cancellation vs check-in
cancellation vs StartServiceSession
concurrent Queue join same AdmissionScope
repricing after partial allocation preserves old requirement history
PaymentEvidence cannot satisfy Requirement
PaymentAttempt success cannot satisfy Requirement
out-of-order FinancialObservations
ObservationCorrection vs AllocatePayment
ObservationCorrection after manual verification
FinancialReversal vs ObservationCorrection behavior
eligibility reduction with deterministic allocation attribution
eligibility reduction with ambiguous attribution → reconciliation
manual verification unauthorized rejection
dual-control same-Principal rejection
PaymentAllocation overspend
partial reversal adjustment budget race
refund-vs-refund
refund-vs-external reversal
provider duplicate event
same event ID conflicting payload
late bank transfer after Hold expiry
concurrent ReconciliationCase resolution
idempotency same key/different payload
idempotent replay after auth revocation
outbox duplicate delivery
external compensation duplicate delivery
DST ambiguous/nonexistent local time
```

---

## 51. Freeze decision

Schema freeze is permitted only when each I01–I76 has an explicit enforcement classification:

```text
DB constraint (FK/unique/check/exclusion)
stable row-lock authority + transaction protocol
optimistic revision protocol
bounded application policy because DB enforcement is semantically incorrect/impossible
```

For lock-based invariants, command docs identify lock target and canonical order.

For application-policy invariants, review explains why DB enforcement is not the right authority.

If a critical rule is defended only by “the service checks first”, schema freeze remains blocked.
