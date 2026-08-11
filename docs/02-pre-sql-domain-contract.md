# Request Engine V2.2 — contrato de dominio pre-SQL

> **Estado:** normativo. Schema freeze bloqueado hasta satisfacer este contrato.
>
> Este documento no diseña tablas. Define cardinalidades, state semantics, concurrency ownership e invariantes que el futuro schema deberá demostrar.

## 1. Readiness

V2.1 declaró prematuramente cerrados todos los blockers. V2.2 reabre cuatro gates fundacionales:

1. Party identity;
2. authority/on-behalf-of;
3. Reservation vs admission;
4. recipient/service-subject scope.

Gates adicionales: Reservation N:M ServiceSession, partial cancellation, travel/transition capacity, policy provenance, cross-channel correlation, external inventory dependency y Dispatch cardinality.

El schema puede explorarse, pero no congelarse hasta pasar los vertical slices y concurrency proofs de este documento.

---

## 2. Cardinalidades normativas

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                  via RequestParticipant
Request 1 ── 0..N OfferingSelection
Offering 1 ── 0..N OfferingSelection

Request N ── M Reservation            via Selection/ReservationItem lineage
OfferingSelection N ── M Reservation  via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem 1 ── 0..N EffectiveResourceRequirement
EffectiveResourceRequirement 1 ── 0..N ResourceAllocation
Resource 1 ── 0..N ResourceAllocation

Reservation N ── M ServiceSession
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
Request 1 ── 0..N ExternalCorrelation
```

### Party

Initial kinds:

```text
person
organization
```

`Principal` is authenticated actor. `Party` is business subject. No implicit 1:1 relation.

### Participant

RequestParticipant carries business role, never authentication authority.

### Authority

The physical model may use AuthorityGrant, verified relationship or external authorization reference, but must answer:

```text
who acted?
on behalf of whom?
for which action/scope?
why was it allowed?
what authority provenance existed then?
```

### Recipient scope

When recipients differ, the model must explicitly relate Party/Participant to OfferingSelection and ReservationItem/admission scope. Do not require a ReservationParticipant aggregate unless lifecycle proves it necessary.

### Dispatch

Do not freeze Reservation 1:N Dispatch. One movement may serve multiple commitments; the physical model must keep N:M operational linkage representable unless Dispatch is deliberately defined more narrowly.

---

## 3. Request lifecycle

Semantically distinguish:

```text
active
waiting
completed
cancelled
failed_terminal
```

Request completion occurs only when versioned workflow/outcome obligations are satisfied or terminally resolved.

Reservation.closed, PaymentRequirement.satisfied or ServiceSession.completed alone are insufficient.

---

## 4. Reservation contract

Reservation means **confirmed capacity commitment only**.

States:

```text
confirmed
cancelled
expired
closed
```

Allowed:

```text
confirmed → cancelled
confirmed → expired   only with explicit policy
confirmed → closed
```

No reopen in place.

Forbidden Reservation states:

```text
no_show
completed
checked_in
waiting
in_service
en_route
```

Pure queue position must never require a fake Reservation.

### Partial cancellation

Canceling a subset must identify exact item/recipient/quantity scope, release or replace only corresponding allocations, and preserve unaffected commitment. Global `cancelled` applies only when no remaining commitment survives and cancellation is the terminating cause.

---

## 5. Admission contract

Admission is orthogonal to capacity commitment.

`QueueEntry` may exist with or without Reservation.

Valid walk-in:

```text
Request/subject → QueueEntry → ServiceSession
```

Valid appointment flow:

```text
Reservation → CheckIn → QueueEntry → ServiceSession
```

WaitlistEntry never itself consumes capacity:

```text
WaitlistEntry → match → CapacityHold → acceptance → Reservation
```

No-show belongs to explicit admission/recipient/item scope. Same scope cannot be simultaneously authoritative attended + no_show without correction/supersession history.

---

## 6. Party and authority contract

Required cases:

```text
person requests for self
parent requests for child
parent pays for child
business pays for employee
third-party organization pays
```

Forbidden assumption:

```text
Principal == Party
Participant role == authority
```

Mutation requiring subject authority validates:

```text
authenticated Principal
Organization match
capability/scope
verified Party/subject correlation
on-behalf-of authority
entity/resource authorization
current state
policy
idempotency
```

Historical mutation preserves authority provenance even if authority later expires/revokes.

---

## 7. Cross-channel contract

ExternalCorrelation is tenant-scoped correlation, not authentication or authorization.

May reference website session, WhatsApp identity/thread, voice session/call or external ticket.

Knowing `request_id` or external thread identifier never grants mutation authority.

Website → WhatsApp → Voice → Human may continue the same Request while every mutation independently resolves current authority.

---

## 8. Fulfillment contract

Fulfillment is append-oriented evidence and preserves:

```text
Request
optional OfferingSelection
recipient/service-subject scope when relevant
fulfilled quantity/scope
outcome
optional ServiceSession/evidence
recorded_at
Principal/source
```

Partial fulfillment must be deterministic:

```text
requested=10
fulfilled=6+2
remaining=2
```

Without explicit over-fulfillment/amendment semantics, fulfilled scope cannot exceed requested amended scope.

Refund/chargeback never deletes Fulfillment.

---

## 9. ServiceSession contract

Actual execution timestamps never overwrite planned Reservation timestamps.

Must support:

```text
Reservation A → Session 1 + Session 2
Reservation A + Reservation B → Session X
walk-in → Session Y without Reservation
```

Session completion does not imply Request completion. Session linkage does not itself imply Fulfillment.

---

## 10. Pricing contract

Every PaymentRequirement created by Request Engine requires auditable PriceDetermination/provenance:

```text
priced scope
quantity/inputs
source/policy/version
adjustments
final Money
override Principal/reason
calculated_at
```

Historical determination is immutable in meaning.

Quote remains deferred unless acceptance/expiry/supersession lifecycle becomes required.

---

## 11. PaymentRequirement contract

Represents obligation, not invoice.

Must know Money, purpose, payer Party when known, pricing provenance, policy reference/snapshot, optional due_at and explicit disposition active/waived/cancelled.

`open/partial/satisfied/overdue` are derived/materialized financial state.

No manual `paid=true` authority.

---

## 12. Financial facts

Original settlement remains historical after refund/reversal/dispute.

A new economic movement is represented as a related fact, never by rewriting history to pretend original settlement did not exist.

Refund operation, FinancialReversal/Return and PaymentDispute remain distinct.

External reversal must still be recorded even if concurrent internal refund creates a deficit requiring reconciliation.

---

## 13. PaymentAllocation invariants

```text
sum(eligible allocations from transaction)
<= eligible transaction value
```

Historical allocations are not erased because later reversals change their net contribution.

Overpayment may remain unallocated.

Concurrent refund claims cannot exceed internally refundable budget.

---

## 14. Capacity contract

CapacityHold and confirmed ResourceAllocation compete for the same capacity.

Forbidden confirmation gap:

```text
release Hold
COMMIT
later create Reservation
```

For exclusive Resources, incompatible live claims cannot overlap.

For units:

```text
sum(live holds + active confirmed claims) <= effective capacity
```

Every active allocation identifies Reservation, ReservationItem, EffectiveResourceRequirement, Resource/pool, quantity, interval, status and lineage.

Confirmed Reservation with insufficient required allocations must be immediately detectable as at_risk/blocked.

---

## 15. CapacityHold and pool binding

Hold states:

```text
active
confirmed
released
expired
```

Only active can transition to a terminal state. Confirmation and expiry serialize. Late payment never revives expired Hold.

Pool binding must prove:

```text
pool not oversold
member not double-booked
binding not double-counted
lineage preserved
```

No independent Assignment truth source.

---

## 16. Travel/setup/transition capacity

If two service intervals do not overlap but the same Resource cannot physically transition between them, the second commitment must be rejected/replanned.

Example:

```text
A service 09:00–10:00 at destination A
travel A→B = 45m
B service 10:00–11:00 at destination B
```

Accepted strategies include blocking intervals, transition claims or another serializable deterministic feasibility authority.

Route optimization remains external.

---

## 17. Schedule/time contract

Authoritative instants: UTC. Schedule interpretation: IANA timezone.

Ambiguous local time requires explicit fold/offset/choice. Nonexistent local time is rejected or resolved by explicit communicated policy.

ScheduleException never rewrites confirmed Reservation history. Capacity-affecting changes produce detectable risk/recovery.

HolidayCalendar is not required as aggregate.

---

## 18. Destination and inventory dependencies

Confirmed Destination is historical snapshot. ChangeDestination validates revision, ServiceArea, pricing, travel/capacity and Dispatch consequences while preserving old snapshot.

External stock observation is not inventory commitment. If fulfillment depends on external stock, workflow preserves the external reservation/commitment reference/provenance necessary to justify the decision.

No network call inside authoritative DB transaction.

---

## 19. Policy provenance

Material policy decision preserves:

```text
policy key/version
scope
relevant inputs
precedence/winning source
override flag
Principal/reason
```

Current policy changes never rewrite historical decisions.

No generic rules DSL.

---

## 20. Amendment contract

After commitment/payment/fulfillment, material fields are changed only by semantic commands.

Material includes offering, quantity, recipient scope, planned interval, Destination, price, EffectiveResourceRequirements and policy snapshot.

No universal Amendment aggregate.

---

## 21. Idempotency and callbacks

For tenant/operation/caller scope S, key K and canonical hash H:

```text
unseen → execute + persist H/result
same K/H → replay logical result
same K/different H → conflict
```

DB uniqueness is mandatory.

Provider event identity is deduplicated within tenant/provider-connection namespace. Duplicate event has one logical effect. Out-of-order event cannot blindly regress authoritative state.

Agent adapter should not rely on free-form LLM reasoning to generate stable retry identity.

---

## 22. Multi-tenancy

For every critical tenant-owned relation:

```text
child.organization_id == parent.organization_id
```

Protect in DB where relationally enforceable.

Resolve tenant + public_id together where possible. Never leak another tenant's existence/metadata from a hallucinated or malicious ID.

---

## 23. Agent authorization

LLM text never constitutes authority.

Payment screenshot/text creates PaymentEvidence only.

Generic `update_entity`, `set_status`, `set_paid` agent tools are prohibited.

Mutating tools revalidate current authoritative state, authorization, policy and idempotency every time.

---

## 24. Derived state

Derived/projection examples:

```text
Reservation operational_health
PaymentRequirement satisfaction
overdue
Request progress
availability
queue estimate
attendance summary
remaining fulfillment
```

If materialized, they must be reconstructible and have no arbitrary write endpoint.

---

## 25. Audit and outbox

Material/privileged mutation records Organization, Principal, Party/on_behalf_of when relevant, authority provenance, action, entity/revision, reason, policy/version, override, channel/correlation and occurred_at.

Domain mutation + outbox append = same transaction.

Delivery is at-least-once; consumers are idempotent; concurrent workers use claiming protocol.

---

## 26. State-machine independence

Request, CapacityHold, Reservation, Admission, Dispatch, ServiceSession, PaymentRequirement disposition, PaymentAttempt, financial facts, Refund, PaymentDispute and Fulfillment are related but not one global state machine.

Examples:

```text
Reservation=closed + no ServiceSession
```
may be valid after no-show resolution.

```text
Reservation=confirmed + missing required allocation + health=valid
```
is invalid projection.

```text
PaymentRequirement=satisfied + all contributing value reversed
```
is invalid if satisfied is treated as authority; derived net state must change.

```text
Dispatch=en_route + all related commitment scopes cancelled
```
may be temporarily valid while compensation is pending, never indefinitely.

```text
Hold=expired + later Reservation confirmed from it
```
is forbidden.

```text
same admission scope attended + no_show
```
is forbidden without correction history.

---

## 27. Required concurrency proofs

### C1 Last capacity
Two concurrent final-unit holds → at most one commits. Primary guarantee: DB capacity authority.

### C2 Hold confirm vs expiry
Exactly one wins. Primary: row/version lock.

### C3 Payment vs Hold expiry
Payment remains fact; capacity never resurrects. Primary: independent financial commit + locked Hold state.

### C4 Cancellation vs CheckIn
Serialize relevant commitment/admission scope; policy decides permitted outcome.

### C5 Resource unavailable vs confirmation
If unavailable wins, confirmation fails/recomputes. If confirmation wins, later unavailability creates risk/recovery.

### C6 Duplicate webhook
One logical effect. Primary: DB unique provider-event identity + idempotent command.

### C7 Refund vs reversal
Internal refund respects refundable budget; external reversal is still recorded even if net deficit results.

### C8 Two concrete bindings
Competing exclusive Resource bindings cannot both become active.

### C9 Two outbox workers
One active claim; duplicate external delivery remains harmless.

### C10 Concurrent reconciliation
Incompatible allocations/resolutions cannot both commit.

### C11 Partial cancellation vs ServiceSession start
Same item/recipient scope cannot be silently released while execution starts without explicit policy outcome.

### C12 Travel constraint race
Concurrent field bookings cannot create impossible technician transition from stale feasibility reads.

### C13 Waitlist promotion
Only CapacityHold grants temporary exclusivity; waitlist rank does not.

### C14 Cross-tenant ID attack
No mutation and no descriptive leakage.

### C15 Agent retry
Repeated tool call produces same logical result once.

---

## 28. Guarantee ownership

| Invariant | Primary guarantee |
|---|---|
| cross-tenant relation | DB FK/constraint |
| tenant public ID uniqueness | DB unique |
| idempotency key | DB unique |
| provider event dedupe | DB unique |
| exclusive capacity | DB exclusion/lock |
| unit capacity | DB transaction/lock |
| Hold confirm/expire | DB lock/version |
| pool/member conflict | DB capacity invariant |
| PaymentAllocation budget | DB transaction/lock |
| refund budget | DB transaction/lock |
| stale aggregate mutation | optimistic version |
| authority/policy eligibility | application + persisted provenance |
| cancellation/no-show consequence | application policy |
| outbox atomicity | DB transaction |
| external exactly-once delivery | not assumed; idempotency |
| derived labels | deterministic projection |

If violating an invariant can create impossible money, impossible capacity or cross-tenant leakage, application-only prechecks are insufficient.

---

## 29. Premature abstractions prohibited

Do not create first-class aggregate/table merely because the noun exists:

```text
Assignment
ResourceGroup
HolidayCalendar
ReservationDisruption
ReservationParticipant
Quote
ReservationSeries
Agreement
Subscription
GenericAmendment
GenericRelationship
GenericPolicyRule
GenericWorkflowStep engine
```

Introduce only when a concrete invariant/lifecycle cannot be expressed cleanly without it.

---

## 30. Mandatory vertical-slice proofs

### Barbershop

Prove requester != recipient, haircut+beard, barber+chair, walk-in queue without Reservation, appointment+queue, scoped late/no-show, partial cancellation, employee sickness and last-capacity race.

### Dental

Prove child+guardian+separate payer, organization payer, role != authority, staged chair/hygienist/dentist requirements, equipment failure, mixed attendance, multiple ServiceSessions and partial Fulfillment.

### Plumbing

Prove arrival window, Destination/ServiceArea, travel constraint, pool→technician binding, vehicle failure, destination change en_route, one visit executing multiple Reservations/Requests, bank transfer without reference, fake receipt and late payment after Hold expiry.

### Group/tour

Prove 10 seats, multiple recipients, 8 attended + 2 no-show, waitlist promotion, partial recipient cancellation and unit-capacity race.

### Retail + service

Prove product+installation, inventory observation != commitment, external stock commitment reference, technician capacity independent from stock and invalidated stock before internal confirmation.

### Multi-channel agent

Prove Website→WhatsApp→Voice→Human on same Request, correlation != authority, hallucinated ID, cross-tenant ID, unauthorized on-behalf-of write, duplicate tool execution, stale availability and payment screenshot abuse.

### Payments

Prove partial payment, overpayment, N→1 and 1→N allocations, refund after cancellation, chargeback after Fulfillment, duplicate/out-of-order webhook, false manual verification remains auditable, refund/reversal race and concurrent reconciliation.

---

## 31. Required invariant tests

Before schema freeze:

```text
no cross-tenant critical FK
no duplicate logical idempotent command
no exclusive overlap
no unit oversell
no Hold confirmation after expiry
no Hold→Reservation capacity gap
no pool/member double count
no queue=Reservation assumption
no global no-show
no recipient-scope ambiguity
no over-fulfillment without amendment
no PaymentEvidence settlement
no allocation/refund overspend
no historical financial fact erasure
no Fulfillment erasure after chargeback
no policy decision without provenance
no silent DST normalization
no impossible field-service transition
no agent authority from role/text alone
no cross-channel correlation as bearer token
```

Concurrency tests must use real competing DB transactions, not only mocked services.

---

## 32. Physical decisions still open

Allowed during SQL design:

```text
UUID/ULID/public-ID encoding
Money storage strategy
range representation
capacity authority/bucket strategy
AuthorityGrant physical shape
recipient-scope link shape
Reservation-ServiceSession link shape
pool realization strategy
projection materialization
outbox claiming details
```

Physical freedom is valid only if semantic invariants remain provable.

---

## 33. Explicitly deferred

```text
Quote lifecycle
ReservationSeries/ServicePlan
subscriptions
advanced OR/k-of-n resource algebra
FX
full inventory
invoice/tax engine
accounting ledger
route optimization
workforce optimization
generic workflow/rules DSL
```

---

## 34. Schema-freeze gate

PostgreSQL exploration may begin, but freeze is prohibited until:

```text
[ ] Party supports person + organization without CRM expansion.
[ ] Principal/Party/Participant/authority are distinct.
[ ] on-behalf-of mutation has durable provenance.
[ ] QueueEntry can exist without Reservation.
[ ] Reservation means capacity commitment only.
[ ] recipient/admission scope is unambiguous.
[ ] partial cancellation releases exact capacity scope.
[ ] Reservation N:M ServiceSession is representable.
[ ] transition/travel cannot create impossible field schedules.
[ ] policy decisions preserve version/precedence provenance.
[ ] cross-channel correlation cannot become bearer authority.
[ ] external inventory distinguishes observation from commitment.
[ ] capacity races have DB/transaction proof.
[ ] payment/refund/allocation races have DB/transaction proof.
[ ] tenant isolation is relationally enforced for critical relations.
[ ] agent retry/hallucinated-ID tests pass.
[ ] mandatory vertical slices pass without industry-specific core entities.
```

If a slice passes only by adding fake Reservations, generic nullable fields, arbitrary status setters or application-only checks for critical invariants, the model is not ready.

---

## 35. Exit criterion

READY FOR SQL FREEZE means we can answer unambiguously:

```text
What was requested and for whom?
Who was allowed to act and why?
What capacity was committed?
What admission occurred independently?
Which requirement does every allocation satisfy?
What execution occurred across which Reservations?
Why was each amount determined?
What money was authoritatively observed?
What value remains after refund/reversal/dispute?
What exact scope was fulfilled?
Which policy/version produced each material decision?
What happens when conflicting actors race?
```

Until those answers are backed by passing proofs, this document remains the blocking gate.