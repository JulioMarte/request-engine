# Request Engine V2.4 — contrato de dominio pre-SQL

> **Estado:** normativo. Schema freeze bloqueado hasta satisfacer este contrato.
>
> Este documento no diseña tablas definitivas. Define cardinalidades, state semantics, lock ownership, physical proof obligations e invariantes que el futuro schema PostgreSQL deberá demostrar.

---

## 1. Readiness

V2.4 considera semánticamente resueltos los blockers anteriores y añade pruebas físicas obligatorias para:

1. tenant-safe typed references;
2. common capacity conflict space;
3. stable capacity/schedule authority revisions;
4. pool/direct-resource serialization;
5. canonical multi-authority lock ordering;
6. shared-requirement partial cancellation;
7. hold expiry wall-clock semantics;
8. two-sided financial adjustment budgets;
9. Request completion serialization;
10. local-vs-external authority boundary.

Schema exploration is allowed. Schema freeze is not.

---

## 2. Cardinalidades normativas

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                    via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
External interaction identity N ── M Request

Request N ── M Reservation              via Selection/ReservationItem lineage
OfferingSelection N ── M Reservation    via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CommitmentRequirement 1 ── 1..N ResourceAllocation

Reservation N ── M ServiceSession
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

Physical persistence may introduce internal supertypes/claim rows, but those may not change the semantic cardinalities above.

---

## 3. Typed-reference contract

Critical authoritative relationships must have enforceable referential integrity.

Forbidden shortcut:

```text
entity_type TEXT
entity_id BIGINT/TEXT
```

when the database cannot prove the referenced entity exists in the same tenant.

Applies especially to:

```text
RequestTarget
PriceDetermination priced scope
capacity authority target
financial source/provenance links
```

Allowed strategies:

```text
explicit typed link table
real relational supertype
XOR constrained typed foreign keys
```

Audit/log-like references may be looser only if they are not used to enforce business authority or invariants.

---

## 4. Tenant contract

For every critical tenant-owned relationship:

```text
child.organization_id == parent.organization_id
```

Must be DB-enforceable where relationship is authoritative.

Public IDs and external IDs never grant authority.

Public lookups resolve tenant + identifier together where possible.

---

## 5. RequestTarget contract

RequestTarget represents an existing entity that the Request intends to act upon.

Initial supported target:

```text
cancel_reservation / reschedule_reservation → Reservation
```

Target type must be allowed by RequestType.

Target link is typed and tenant-safe.

Generated lineage is separate and must not be inferred from RequestTarget.

---

## 6. Request lifecycle and serialization

Semantic states:

```text
active
waiting
completed
cancelled
failed_terminal
```

Terminal states are monotonic initially.

`CompleteRequest` and every command that changes required outcome obligations must serialize through the same Request root/version.

Forbidden race result:

```text
T1 CompleteRequest sees obligations satisfied
T2 adds required component
both commit
→ completed Request with unmet obligation
```

Expected:

```text
one wins; loser reloads/re-evaluates
```

Opaque workflow JSON cannot be sole completion authority.

---

## 7. Party and authority contract

Forbidden assumptions:

```text
Principal == Party
RequestParticipant role == authority
external authority state is instantly serializable with local DB
```

Mutation depending on authority requires:

```text
authenticated Principal
Organization match
capability/scope
verified Party/subject correlation
current locally materialized authority version
entity authorization
current entity state
policy/version
idempotency
```

### Local revocation race

Authority revocation and dependent mutation must lock/version-check the same local authority root.

Expected:

```text
revocation commits first → mutation fails/re-evaluates
mutation commits first → audit stores authority version used
```

### External authority

External authority is represented by verified snapshot/reference with provenance and optional validity window. Request Engine does not promise atomic awareness of external revocation without a local callback/reverification event.

---

## 8. Cross-channel contract

ExternalCorrelation is N:M.

Forbidden uniqueness assumption:

```text
(org, channel, external_id) → exactly one Request
```

Correlation never grants authority.

Durable operation identity may survive controlled channel handoff without conflating it with Party identity.

---

## 9. Fulfillment contract

Offering/version defines one FulfillmentModel:

```text
binary
quantity
components
external_authoritative
```

`quantity` arithmetic only when unit semantics make it valid.

`components` uses explicit versioned component keys/scopes.

Fulfillment is append-oriented and references one Request. It may reference optional OfferingSelection, ServiceSession and recipient scope.

Refund/reversal does not erase Fulfillment.

---

## 10. CommitmentRequirement contract

Offering configuration uses ResourceRequirementTemplate.

Reservation commitment uses CommitmentRequirement.

Required traceability:

```text
Reservation
→ CommitmentRequirement
↔ covered ReservationItems
→ ResourceAllocation(s)
→ capacity authority
```

Shared requirements consume capacity once.

Every ReservationItem requiring capacity must be covered by the necessary CommitmentRequirements.

Every required CommitmentRequirement must have sufficient active allocation/claim coverage while Reservation remains operationally valid.

---

## 11. CapacityAuthority physical contract

Physical design must provide a stable lockable identity for every reservable capacity authority.

Semantically that authority may represent:

```text
Resource
CapacityPool
```

Required properties:

```text
organization
capacity model
current revision
current schedule/availability revision
active/config state
```

It may be implemented as a relational supertype or equivalent typed stable rows.

What matters:

> Every transaction capable of changing or consuming the same capacity can identify and lock the same authority.

---

## 12. CapacityClaim physical contract

Holds and confirmed allocations compete in one logical conflict space.

Physical design must therefore either:

1. represent their live claims in a common claim relation; or
2. prove an equivalent serialization protocol with identical correctness.

Preferred conceptual common claim:

```text
organization
capacity_authority
origin kind/reference
interval
quantity
claim state
expires_at if hold-backed
```

`CapacityClaim` is persistence-internal; it does not merge CapacityHold and ResourceAllocation semantically.

---

## 13. Exclusive capacity proof

Invariant:

> No incompatible live exclusive claims overlap on the same CapacityAuthority.

Preferred proof:

```text
PostgreSQL range + exclusion constraint on common CapacityClaim relation
```

Separate Hold and Allocation tables with independent exclusion constraints do **not** prove cross-table conflict safety.

The final SQL design must show the actual exclusion/serialization mechanism.

---

## 14. Unit capacity proof

Invariant:

```text
sum(overlapping live hold claims + active allocation claims)
<= effective capacity
```

V1 proof protocol:

```text
LOCK CapacityAuthority
revalidate schedule/availability revision
calculate overlapping live claims
validate requested quantity
insert/transform claim
COMMIT
```

No check-then-insert outside authority lock.

A single authority row becoming a hotspot is an accepted V1 correctness tradeoff until measurement proves otherwise.

---

## 15. Hold lifecycle and expiry

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

A hold is logically live only while:

```text
state = active
AND expires_at > authoritative wall-clock time
```

Cleanup worker does not define expiry truth.

Confirmation must check logical liveness immediately before transition under relevant lock.

A long transaction must not accidentally treat transaction-start timestamp as current wall clock for expiry-sensitive validation.

Late payment never reactivates expired capacity.

---

## 16. Schedule mutation / phantom-race contract

Schedule rows and exceptions alone are not safe lock targets because concurrent inserts create phantoms.

Any mutation capable of changing reservability must lock/increment a stable authority revision.

Examples:

```text
AvailabilitySchedule edit
ScheduleException insert/update
capacity_override
Resource unavailable
CapacityPool membership/eligibility change
```

Claim creation and schedule mutation therefore serialize through the same authority.

Expected race:

```text
claim commits first
→ schedule mutation sees existing commitment and triggers recovery/disruption

schedule mutation commits first
→ claim sees new revision/schedule and fails/recomputes
```

---

## 17. CapacityPool contract

V1 pools are member-derived and late-bind only fungible contributors.

### Contributor exclusivity

A Resource cannot contribute the same capacity simultaneously to reservable pools whose claims may overlap.

Must be structurally forbidden or serializably proven.

### Direct-resource vs pool race

A direct claim against a contributing Resource must serialize with both:

```text
concrete Resource capacity authority
relevant CapacityPool authority
```

in canonical order.

### Fungibility

Pool late binding only when candidate members are interchangeable for the CommitmentRequirement.

If not, concrete Resource binding occurs at Hold/confirmation time.

### Pool mutation

Membership/eligibility changes lock/increment pool authority revision and evaluate existing pool commitments.

---

## 18. Canonical lock-order contract

Any transaction locking multiple authority rows must acquire them in deterministic order.

The architecture must define one global lock ordering over lock classes and IDs.

Example conceptual order:

```text
AuthorityGrant
Request
Reservation
CapacityAuthority
PaymentTransaction
PaymentRequirement
ReconciliationCase
```

Within same class, ascending internal key.

Exact order may differ, but inconsistency across commands is forbidden.

Deadlock detection/retry is fallback, not design strategy.

---

## 19. Reservation contract

Reservation states:

```text
confirmed
cancelled
closed
```

No `expired` in initial Reservation lifecycle.

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

This need not be a simple CHECK, but the terminal command transaction must prove it before commit.

Generic status setter is forbidden.

---

## 20. Partial cancellation / shared requirement race

If Items A and B share Requirement X, concurrent cancellation of A and B must not leave orphan active capacity.

Required serialization root:

```text
Reservation
```

Protocol:

```text
LOCK Reservation
revalidate current item/revision state
recompute surviving Requirement coverage
release/replace affected claims
set terminal Reservation only if no commitment remains
COMMIT
```

Commands may additionally lock affected CapacityAuthorities in canonical order.

---

## 21. ServiceSession concurrency contract

Reservation ↔ ServiceSession is N:M.

Cancellation/reschedule that conflicts with active execution must observe a serialization-safe session linkage/current session state.

Forbidden result:

```text
Session starts work for Reservation B
concurrent cancellation commits as if execution never started
```

Policy determines reject/stop/partial/manual behavior after serialization.

---

## 22. Dispatch contract

Dispatch represents movement toward one Destination.

May link multiple Reservations only when the same movement/destination is shared.

Cancellation of one Reservation does not automatically cancel a Dispatch also serving surviving commitments.

No route planning graph.

---

## 23. Pricing provenance contract

Every PaymentRequirement created internally must reference enough pricing/amount-derivation provenance to answer:

```text
what commercial scope?
what price determination/version?
what payment policy/version?
which calculation inputs?
what Money resulted?
who overrode it?
```

Critical priced-scope references must be typed/FK-safe; opaque polymorphic IDs are forbidden.

---

## 24. PaymentRequirement contract

Business disposition:

```text
active
waived
cancelled
```

Derived/materialized financial labels:

```text
open
partial
satisfied
overdue
```

No manual `paid=true` authority.

Refund does not automatically change business disposition.

Reversal/return may make an active Requirement outstanding again according to net allocation contribution.

---

## 25. PaymentTransaction / allocation contract

Original financial observation remains historical after refund/reversal/dispute.

Positive PaymentAllocation invariant:

```text
sum(net eligible allocation contributions from transaction)
<= eligible transaction value
```

Allocation command locks PaymentTransaction financial authority before spending value.

Currencies must match unless a future explicit FX model exists.

---

## 26. PaymentAllocationAdjustment contract

Adjustment is append-oriented attribution of invalidated/corrected value against PaymentAllocation.

Two budgets must be protected simultaneously:

### Source budget

```text
sum(adjustments attributed to FinancialReversal R)
<= R.amount
```

### Allocation budget

```text
sum(invalidating adjustments against Allocation A)
<= A.eligible historical contribution
```

Creation locks source financial fact and affected allocations in canonical order.

If attribution is ambiguous, no arbitrary adjustment is created; ReconciliationCase is used.

---

## 27. Refund contract

Refund lifecycle:

```text
requested
processing
succeeded
failed
cancelled
```

Refund command locks original PaymentTransaction/value authority and enforces:

```text
pending + succeeded refundable claims
<= refundable amount allowed by facts/policy
```

External reversal cannot be rejected because local refund exists. If both occur and create a deficit, preserve both facts and reconcile.

Void of uncaptured authorization is not Refund.

---

## 28. Provider callback contract

Dedupe identity is scoped by provider connection/account semantics.

Preferred uniqueness when provider guarantees event IDs:

```text
(provider_connection, provider_event_id)
```

Same identity + same canonical payload → duplicate/replay.

Same identity + materially different payload → integrity conflict, audit/review.

Out-of-order events may append facts or update the same external operation when semantically valid, but never blindly regress authoritative domain state.

---

## 29. Reconciliation contract

ReconciliationCase is required when financial treatment/matching/attribution is uncertain.

Concurrent resolution uses row lock/version.

Two resolutions cannot consume/attribute the same financial value incompatibly.

---

## 30. Idempotency contract

For scope S, key K, canonical hash H:

```text
unseen → execute and persist H/logical result
same H → replay logical result
other H → conflict
```

Replay does not bypass current read authorization.

Transport idempotency and durable cross-channel operation identity are distinct.

Keys/tokens are not bearer authorization.

---

## 31. Outbox contract

Domain mutation + outbox append = same DB transaction.

Worker delivery is at-least-once.

Claim protocol prevents concurrent execution of same outbox row; consumer idempotency handles redelivery.

---

## 32. Availability projection contract

Availability/materialized slots/current queue estimate/operational health/payment labels are projections.

If materialized:

- rebuildable;
- not arbitrary write endpoints;
- never sufficient to create authoritative capacity/payment mutation without locked revalidation.

---

## 33. Required command proofs

Before schema freeze, architecture/schema design must document at minimum the following command plans using:

```text
READ
LOCK
VALIDATE
WRITE
EMIT
```

Required commands:

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
StartServiceSession
CompleteServiceSession
RecordFulfillment
CreatePaymentRequirement
RecordPaymentTransaction
AllocatePaymentTransaction
ApplyPaymentAllocationAdjustment
RequestRefund
RecordFinancialReversal
ResolveReconciliationCase
ChangeDestination
Create/UpdateDispatch
RevokeAuthorityGrant
```

If a command cannot identify a bounded lock set or deterministic lock order, aggregate/authority design is not ready.

---

## 34. Required race proofs

### C1 — Last unit

Two concurrent holds for final unit. Maximum one valid claim commits.

### C2 — Hold confirm vs expiry

Only one semantic terminal outcome wins. Wall-clock expiry is respected.

### C3 — Payment vs Hold expiry

Payment remains financial fact; expired capacity is not resurrected.

### C4 — Schedule exception vs Hold

Serialize through same CapacityAuthority revision.

### C5 — Resource unavailable vs confirmation

Serialize through same capacity authority.

### C6 — Pool claim vs direct member booking

No pool/direct oversell.

### C7 — Pool membership mutation vs Hold

One revision wins; loser recomputes.

### C8 — Shared requirement dual cancellation

No orphan active allocation remains.

### C9 — Session start vs cancellation

Execution/current-state policy determines deterministic winner/consequence.

### C10 — Request completion vs outcome amendment

No completed Request with newly unmet obligation.

### C11 — Authority revocation vs mutation

Local authority version serializes.

### C12 — Duplicate webhook

One logical effect.

### C13 — Same provider event ID, different payload

Integrity conflict; no silent replay.

### C14 — Allocation overspend

Concurrent allocations cannot exceed eligible transaction value.

### C15 — Partial reversal attribution

Two-sided budgets cannot be exceeded.

### C16 — Refund vs refund

Refundable budget not overspent.

### C17 — Refund vs external reversal

Both facts may exist; deficit represented/reconciled, never erased.

### C18 — Two reconciliations

Conflicting resolutions cannot both commit.

### C19 — Two workers same outbox

At most one active row claim; redelivery still idempotent.

### C20 — Idempotent replay after authorization revocation

No duplicate write; no unauthorized disclosure.

---

## 35. DB-guarantee map

### Must be DB structural/transactional

```text
cross-tenant FK integrity
typed authoritative references
tenant-scoped public ID uniqueness
idempotency uniqueness/provider-event dedupe
exclusive claim overlap
unit-capacity serialized totals
hold confirmation/expiry serialization
schedule/capacity revision serialization
pool/direct claim serialization
financial allocation budget
adjustment source/allocation budgets
refund budget
reconciliation exclusivity
outbox mutation atomicity
```

### Application policy over DB-protected current state

```text
who may cancel/reschedule
cancellation/no-show fees
which policy version applies
whether active ServiceSession permits cancellation
whether a pool is semantically fungible for a requirement
how ambiguous reversal attribution is resolved
Request outcome criteria
external inventory acceptance policy
```

Application policy must never replace DB protection for capacity, money or tenant integrity.

---

## 36. Canonical lock-order proof

The SQL design must publish one canonical lock-order table and all command plans must comply.

At minimum it must cover:

```text
AuthorityGrant/Representation
Request
Reservation
CapacityAuthority
ServiceSession
PaymentTransaction
PaymentRequirement
FinancialReversal/Refund
ReconciliationCase
```

Multi-row locks within a class use deterministic key order.

---

## 37. Pre-SQL acceptance checklist

Schema freeze is allowed only when all answers are concrete:

```text
What row/authority serializes each capacity change?
How do Hold and Allocation conflict in the same physical space?
How does a new ScheduleException race a Hold without phantom oversell?
How does a direct Resource booking race its pool?
How are multiple capacity authorities locked without deadlock-prone arbitrary order?
How does shared requirement cancellation release exactly the right capacity?
How is hold expiry evaluated independently of worker delay?
How are polymorphic-looking relationships given real FK integrity?
How does Request completion race outcome mutation?
How does local authority revocation race an on-behalf-of command?
How are partial reversals attributed without inventing balances?
How are refund and reversal both preserved if they exceed prior net value?
Which invariants are DB-enforced versus application-policy-enforced?
```

If any answer is still “query current rows, check, then insert/update” without a stable locked authority, the model is not ready for SQL implementation freeze.

---

## 38. Deliberately deferred

Do not add yet:

```text
microservices by module
BPMN/Temporal clone
generic policy/rules DSL
universal pricing DSL
full inventory
invoice/tax engine
accounting ledger
route optimizer
raw GPS store
ReservationSeries
Subscription/Agreement framework
advanced OR/k-of-n resource requirements
overlapping arbitrary reservable pools
capacity sharding/bucket optimization before measured contention
universal polymorphic entity graph
```

Correctness first; measured optimization later.