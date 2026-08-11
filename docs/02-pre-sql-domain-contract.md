# Request Engine V2.3 — contrato de dominio pre-SQL

> **Estado:** normativo. Schema freeze bloqueado hasta satisfacer este contrato.
>
> Este documento no diseña tablas. Define las cardinalidades, state semantics, concurrency ownership e invariantes que el futuro schema PostgreSQL deberá demostrar.

---

## 1. Readiness

V2.3 considera resueltos semánticamente, pero todavía no demostrados físicamente, estos blockers:

1. Party identity;
2. authority/on-behalf-of;
3. Reservation vs admission;
4. recipient/service-subject scope;
5. shared capacity requirements across ReservationItems;
6. pool capacity authority;
7. partial reversal attribution;
8. Request target semantics;
9. authority revocation races;
10. qualitative/component fulfillment.

El schema no puede congelarse hasta pasar todos los proofs de este documento.

---

## 2. Cardinalidades normativas

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                    via RequestParticipant
Request 1 ── 0..N RequestTarget
Request 1 ── 0..N OfferingSelection

External correlation identity N ── M Request

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

No introducir `Reservation.request_id` como ownership authority.

---

## 3. RequestTarget contract

`RequestTarget` representa la entidad preexistente sobre la que actúa un Request.

Ejemplos:

```text
cancel_reservation → Reservation
reschedule_reservation → Reservation
```

No se utiliza para expresar Reservations/Fulfillments generados por el Request.

Invariant:

```text
RequestTarget.target_type must be allowed by RequestType
```

Target lookup es tenant-scoped y subject to authorization.

No generic arbitrary object graph.

---

## 4. Request lifecycle contract

Semánticamente:

```text
active
waiting
completed
cancelled
failed_terminal
```

Terminal states son monotónicos inicialmente.

Forbidden implicit behavior:

```text
completed Request
+ later chargeback
→ reopen same Request
```

Eventos posteriores crean nuevo Request/case/recovery work cuando policy lo requiera.

Completion debe depender de typed/versioned outcome criteria y authoritative facts. Opaque workflow JSON/boolean no puede ser la única autoridad.

---

## 5. Party and authority contract

Forbidden:

```text
Principal == Party
RequestParticipant role == authority
```

Mutation que depende de representation requiere:

```text
authenticated Principal
Organization match
required capability
verified Party/subject correlation
current AuthorityGrant/Representation state
entity authorization
current entity state
policy/version
idempotency
```

### Authority revocation race

Si authority puede revocarse concurrentemente, mutation y revocation deben competir mediante lock/version/current-state check dentro de la authoritative transaction.

Expected:

```text
revocation commits first → dependent mutation fails/re-evaluates
mutation commits first → audit preserves authority version used
```

Historical audit conserva immutable version/snapshot/hash/provenance de la authority decision. No depende de leer posteriormente una fila mutable y asumir que representa el pasado.

---

## 6. Cross-channel contract

External correlation is N:M semantically.

Valid:

```text
WhatsApp thread X → Request A
WhatsApp thread X → Request B
Request A → website session Y
Request A → voice call Z
```

Forbidden uniqueness assumption:

```text
(org, channel, external_id) → exactly one Request
```

Correlation never grants authorization.

---

## 7. Offering / fulfillment contract

Offering/version defines `FulfillmentModel`:

```text
binary
quantity
components
external_authoritative
```

### Quantity

Remaining scope may be calculated arithmetically only when the model/unit permits it.

### Components

Component keys/scopes are versioned and explicit.

Example:

```text
plumbing repair
required components:
- diagnosis
- permanent_repair
```

A temporary fix does not become `0.5 fulfilled` unless the Offering contract explicitly defines such semantics.

Fulfillment remains append-oriented and survives refunds/reversals.

---

## 8. Recipient / admission scope contract

When different recipients can have different outcomes, the model must identify exact Party/Participant scope across:

```text
OfferingSelection
ReservationItem
CheckIn / Queue / no-show
Fulfillment
```

A group Reservation can represent mixed attendance without global `Reservation.no_show`.

---

## 9. ResourceRequirementTemplate vs CommitmentRequirement

Offering configuration uses `ResourceRequirementTemplate`.

Confirmed capacity uses `CommitmentRequirement`.

A CommitmentRequirement belongs to a Reservation commitment and may cover 1..N ReservationItems.

Required traceability:

```text
Reservation
→ CommitmentRequirement
↔ covered ReservationItems
→ ResourceAllocation(s)
→ Resource / CapacityPool
```

### Shared requirement invariant

If ReservationItems A and B share one chair requirement, the chair is consumed once for the materialized requirement, not once per item.

### Coverage invariant

Every ReservationItem that requires capacity must be covered by the required set of CommitmentRequirements; every required CommitmentRequirement must have sufficient active Allocation coverage while Reservation is valid.

Do not force one requirement per item when semantics say the commitment is shared.

---

## 10. CapacityPool contract

`CapacityPool` is a reservable capacity authority, not a Resource and not query grouping.

V1 supports only member-derived pools with non-overlapping contributors for the same reservable capacity/interval.

Required properties:

```text
explicit/versioned membership
eligible contributor set
member availability
pool claims
concrete bindings
lineage
```

### Contributor exclusivity

A Resource cannot contribute the same capacity simultaneously to two reservable pools whose claims could overlap.

The SQL design must either structurally forbid such overlapping membership or prove an equivalent serialization model.

### Effective pool capacity

Must be deterministically derived from eligible members minus incompatible concrete/member claims and pool claims according to the chosen binding strategy.

No static `pool.capacity=3` may claim capacity unsupported by members unless the pool is explicitly modeled as an independent fixed capacity authority in a future extension.

### Binding invariant

Pool claim → concrete member binding does not consume a second pool unit.

Binding must simultaneously prove:

```text
member eligible
member not otherwise double-booked
pool claim still owns capacity
lineage preserved
```

If no member can be bound later, Reservation becomes at-risk/blocked and recovery applies; history is not rewritten.

Overlapping arbitrary dynamic pools are out of V1 scope.

---

## 11. CapacityHold contract

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

No terminal → active transition.

Hold and future Reservation allocations compete in same conflict space.

Confirmation and expiry serialize; a payment received after expiry never reactivates capacity.

---

## 12. Reservation contract

Reservation means confirmed capacity commitment only.

States V2.3:

```text
confirmed
cancelled
closed
```

`expired` is deliberately absent from initial Reservation lifecycle.

Forbidden global states:

```text
completed
no_show
checked_in
waiting
in_service
en_route
```

### Terminal capacity invariant

```text
Reservation.status in {cancelled, closed}
→ zero active capacity-consuming ResourceAllocations
```

### Closed semantics

`closed` means no remaining committed future capacity. It does not imply paid, attended or fulfilled.

### Partial cancellation

A command cancelling subset S must:

```text
identify exact item/recipient/quantity scope
re-evaluate shared CommitmentRequirements
release/replace only capacity no longer required
preserve unaffected items/requirements
apply pricing/payment consequences explicitly
```

Global `cancelled` only when no commitment survives and cancellation is terminal cause.

---

## 13. Travel/transition contract

V1 explicitly does not implement general pairwise route-aware scheduling.

Supported:

```text
fixed/conservative transition buffer
OR
external feasibility decision + immutable reference/snapshot
```

If feasibility is material to confirmation, provenance must be stored sufficiently to explain why the schedule was accepted.

No silent dynamic routing assumptions.

---

## 14. Admission contract

Admission orthogonal to capacity commitment.

QueueEntry may exist without Reservation.

WaitlistEntry never consumes capacity.

No-show requires explicit observation/transition according to policy; it is not permanently inferred only from wall clock.

Same admission scope cannot be authoritative attended + no-show simultaneously without correction/supersession history.

---

## 15. ServiceSession contract

```text
Reservation N:M ServiceSession
```

Valid:

```text
Reservation A → Session 1 + 2
Reservation A + B → Session X
walk-in → Session Y without Reservation
```

Session completion does not imply Fulfillment or Request completion.

### Session-vs-cancellation race

If cancellation semantics depend on whether execution has started, StartServiceSession and CancelReservationScope must serialize/revalidate relevant linkage/state.

Expected:

```text
session starts first → cancellation re-evaluates under in-service policy
cancellation commits first → start fails/re-evaluates affected scope
```

---

## 16. Dispatch contract

Dispatch means movement/coordinating Resources toward one Destination.

Multiple Reservations may link to one Dispatch only if they share the same relevant Destination/movement.

Multiple destinations require multiple Dispatches.

This prevents Dispatch from becoming route/trip optimizer.

---

## 17. Pricing contract

PriceDetermination explains commercial value.

Historical determination is immutable in meaning.

Shared discounts/fees across selections do not create implicit per-line allocation unless pricing policy defines it.

Partial cancellation may trigger new PriceDetermination/repricing rather than naive proration.

---

## 18. PaymentRequirement amount derivation

PaymentRequirement must preserve:

```text
required Money
commercial/pricing basis
payment policy + version
calculation inputs
purpose
payer Party when known
due_at when relevant
business disposition
```

Business disposition:

```text
active
waived
cancelled
```

Financial labels:

```text
open
partial
satisfied
overdue
```

are derived/materialized from net eligible contribution and disposition rules.

No `paid=true` authority.

---

## 19. PaymentTransaction and PaymentAllocation

Original financial observation remains historical after later facts.

PaymentAllocation represents positive assignment from eligible transaction value to PaymentRequirement.

Invariant:

```text
sum(current net contributions from a transaction)
<= current eligible transaction value
```

No over-allocation.

---

## 20. PaymentAllocationAdjustment contract

`PaymentAllocationAdjustment` is append-oriented attribution of invalidated/corrected value to an existing allocation or equivalent explicitly modeled allocation scope.

It must preserve:

```text
amount/currency
source financial fact or correction
PaymentAllocation target
reason
policy/source provenance
Principal/system source
recorded_at
```

Conceptually:

```text
net contribution(allocation)
= allocated positive value
- attributed invalidating adjustments
+ explicit restoring adjustments if future design permits them
```

V1 should prefer monotonic invalidating adjustments; restoration should generally be represented by new financial facts/allocations unless a provider correction truly refers to the same observation.

### Partial reversal example

```text
Transaction = 100
Allocation A = 50
Allocation B = 50
Reversal = 30
```

Forbidden:

```text
silently assume A loses 30
silently assume B loses 30
silently prorate 15/15
```

Required:

```text
provider/source attribution
OR explicit versioned policy attribution
OR ReconciliationCase
```

Until attribution is resolved, no ambiguous Requirement satisfaction is fabricated.

---

## 21. Refund vs reversal vs obligation contract

Refund operation, FinancialReversal/Return and PaymentDispute remain distinct.

Financial value changes do not themselves dictate business obligation disposition.

Required examples:

### Goodwill refund

```text
fulfilled service
payment 100
refund 20
policy may leave original obligation satisfied/terminal
```

### Cancellation refund

```text
payment 100
business cancellation
Requirement explicitly cancelled/waived/replaced
refund 100
```

### Bank return

```text
payment previously satisfied Requirement
bank return invalidates value
Requirement may become outstanding again while disposition remains active
```

The policy/command must explicitly define business consequence.

---

## 22. Reconciliation contract

Open ReconciliationCase when treatment is unsafe or ambiguous, including:

```text
missing_reference
ambiguous_match
partial_reversal_attribution
unknown_attempt
late_payment
unallocated_overpayment
provider_mismatch
refund/reversal deficit
manual_review_required
```

Concurrent reconciliation uses lock/version to prevent incompatible resolutions.

---

## 23. Idempotency contract

For transport scope S, key K and canonical hash H:

```text
unseen → execute
same H → same logical outcome/reference
new H → conflict
```

Uniqueness is DB-backed.

### Disclosure rule

Replayed response is subject to current read/disclosure authorization. Idempotency prevents duplicate mutation; it is not a perpetual read capability.

### Durable operation identity

A server-generated operation identity may survive controlled channel/principal handoff.

It does not merge unrelated human intentions.

---

## 24. Multi-tenancy contract

Critical tenant-owned relation:

```text
child.organization_id == parent.organization_id
```

Protect in DB where feasible.

Resolve public IDs tenant-first. Hallucinated/cross-tenant IDs must not reveal existence/details across tenants.

External identifiers scoped by Organization/provider connection/context.

---

## 25. Provider callback contract

Authenticate, anti-replay, persist event identity/fingerprint, dedupe, normalize, process idempotently.

Out-of-order event may append facts but cannot blindly regress internal state.

Provider event uniqueness is DB-backed within correct provider/tenant scope.

---

## 26. Audit contract

Privileged mutation records:

```text
Organization
Principal
Party/on_behalf_of subject
action
entity/revision
exact authority version/snapshot provenance
policy/version
reason/override
operation identity
correlation/causation
source
occurred_at
```

Audit history remains interpretable after authority/policy configuration changes.

---

## 27. Derived state contract

Derived/projection examples:

```text
Reservation operational_health
PaymentRequirement open/partial/satisfied/overdue
Request progress
availability
queue estimate
remaining quantity fulfillment
```

If materialized, they must be rebuildable and not arbitrary write endpoints.

---

## 28. Outbox contract

Domain mutation + outbox append same DB transaction.

Delivery at-least-once. Consumer idempotent.

Two workers need claiming protocol; duplicate delivery cannot duplicate business effect.

---

## 29. Required concurrency proofs

### C1 — Last exclusive/unit capacity

Two Holds compete for final capacity. At most one incompatible claim commits.

### C2 — Hold confirmation vs expiry

Only one terminal transition wins.

### C3 — Payment vs Hold expiry

Payment remains financial fact; expired capacity does not resurrect.

### C4 — Pool claim vs concrete booking

A pool claim and a direct booking of a contributor cannot both consume the same physical Resource capacity.

### C5 — Pool binding race

Two Reservations attempt to bind the last eligible pool member. At most one succeeds.

### C6 — Cross-pool contributor race

V1 must structurally reject a Resource contributing the same capacity to overlapping reservable pools, or prove equivalent isolation.

### C7 — Partial cancellation with shared requirement

Cancel Item A while Item B shares chair requirement. Release only capacity no longer needed; do not release shared chair if B still needs it.

### C8 — Reservation close vs allocation

Close/cancel and allocation creation/replacement race. Terminal Reservation cannot commit with active consuming allocations.

### C9 — Start Session vs cancellation

One wins according to current state/policy; loser re-evaluates.

### C10 — Authority revoke vs command

Revocation first blocks command; command first records authority version used.

### C11 — Duplicate webhook

One logical financial effect.

### C12 — Partial reversal attribution

Two workers cannot attribute the same reversed value inconsistently or beyond reversed amount.

### C13 — Refund and external reversal

External reversal is recorded even if refund already exists; internal refundable budget cannot be overspent, and deficit becomes explicit reconciliation state.

### C14 — Two reconciliations

Only one incompatible resolution commits.

### C15 — Two workers same outbox

Claim protocol prevents concurrent logical execution; consumer idempotency handles redelivery.

### C16 — Multi-channel operation retry

Same durable operation identity cannot create duplicate mutation after handoff to new Principal.

---

## 30. Required DB guarantees vs application policy

### Must have DB/transaction guarantee

```text
tenant integrity
idempotency uniqueness
provider event dedupe
exclusive capacity conflicts
units capacity bounds
pool/member capacity ownership
Hold confirm-vs-expire
terminal Reservation/no active consuming allocations
financial transaction allocation bound
financial adjustment attribution bound
refund internal budget
outbox claim consistency
```

### Application policy with locked authoritative inputs

```text
authority eligibility
RequestTarget validity
partial cancellation semantics
shared discount repricing
Session-vs-cancel policy
partial reversal attribution policy
refund business consequence
workflow completion criteria
```

No critical invariant may rely on an unlocked check performed before the transaction.

---

## 31. Required vertical slices

### Barbershop

Prove:

```text
haircut + beard sharing barber without double count
chair + barber requirements
walk-in QueueEntry without Reservation
appointment + queue
partial cancellation
barber sickness
capacity race
```

### Dental

Prove:

```text
child + guardian + payer
authority revocation race
organization payer
cleaning + exam sharing chair
staged dentist/hygienist requirements
partial attendance
equipment failure
component/quantity fulfillment
```

### Plumbing

Prove:

```text
arrival window
Destination/ServiceArea
conservative travel buffer or external feasibility snapshot
technician CapacityPool
pool → concrete binding
vehicle failure
one Session satisfying multiple Reservations/Requests
destination change after dispatch
bank transfer + late payment
```

### Group/class/tour

Prove:

```text
10 recipients
8 attend / 2 no-show
partial cancellation
waitlist promotion
units capacity race
```

### Retail + service

Prove:

```text
product external inventory commitment reference
technician capacity
stock observation without commitment cannot guarantee fulfillment
```

### Payments

Prove:

```text
partial payment
multiple transactions → one Requirement
one transaction → multiple Requirements
overpayment
partial reversal across multiple allocations
provider-attributed reversal
policy-attributed reversal
ambiguous reversal → ReconciliationCase
goodwill refund without debt reopening
cancellation refund
bank return reopening active obligation
refund + reversal deficit
chargeback after Fulfillment
duplicate/out-of-order callback
```

### Agent / multichannel

Prove:

```text
Website → WhatsApp → Voice → Human
one thread linked to multiple Requests
RequestTarget authorization
hallucinated ID
cross-tenant ID attack
authority revoked during agent command
same durable operation retried by different Principal
idempotency replay after caller loses read permission
```

---

## 32. Deliberately deferred

Do not add yet:

```text
Assignment
ReservationSegment
ReservationSeries
Quote aggregate
Agreement
Subscription
Invoice/tax engine
Accounting ledger
Generic relationship graph
Generic workflow/rules/pricing DSL
Route optimizer
Dynamic overlapping reservable pools
Advanced OR/k-of-n resource algebra
FX
Full inventory
```

---

## 33. Schema freeze checklist

El diseño PostgreSQL no se congela hasta que pueda responder y demostrar:

```text
How can one capacity requirement cover several ReservationItems without double count?
How does pool capacity correspond to real eligible Resources?
Can pool claims and concrete claims ever oversell the same person/equipment?
How is a partial reversal attributed when one transaction paid several obligations?
Can the same financial facts produce two different Requirement balances? If yes, reconciliation must remain open.
Does a refund automatically reopen debt? It must not.
Can a cancel/reschedule Request identify its target without confusing lineage?
Can authority be revoked concurrently without a stale-authority write?
Can historical audit prove exactly which authority version allowed the action?
Can qualitative partial fulfillment be represented without fake arithmetic?
Can a terminal Request receive later financial events without reopening itself?
Can a terminal Reservation retain active capacity claims? It must not.
Can one external thread correlate to multiple Requests?
Can an idempotency replay leak data after permission revocation? It must not.
```

If any answer is “application code will probably handle it”, schema freeze remains blocked.