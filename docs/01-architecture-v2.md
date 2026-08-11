# Request Engine V2.4 — arquitectura de referencia

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

El sistema debe mantener autoridad bajo retries, duplicate/out-of-order callbacks, races de capacity, schedule changes, authority revocation, late payments, multichannel handoffs, partial financial reversals y concurrent recovery.

---

## 2. Stack

### PostgreSQL

Source of truth para:

```text
tenant isolation
referential integrity
capacity conflict protection
stable lock authorities
row/advisory locking where justified
exclusion/unique/check constraints
optimistic versioning
financial allocation/adjustment invariants
idempotency
transactional outbox
authoritative business/audit facts
```

### Python + FastAPI

Domain/application/workers/integrations en Python. FastAPI como transport.

### SQLAlchemy + Alembic

Persistence mapping y migrations.

```text
Pydantic → FastAPI → OpenAPI → generated SDKs
```

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
│   ├── commands/
│   ├── queries/
│   └── services/
├── infrastructure/
│   ├── postgres/
│   ├── webhooks/
│   ├── integrations/
│   ├── media/
│   └── observability/
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

No network calls dentro de authoritative DB transactions.

External data needed for a transaction must be obtained beforehand and represented as validated snapshot/reference, or processed asynchronously after commit.

---

## 5. Aggregate philosophy

Aggregate roots probables:

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
PaymentTransaction observation boundary
Refund
PaymentDispute
ReconciliationCase
ServiceSession
Dispatch only if lifecycle justifies root status
```

Children/value objects/links probables:

```text
RequestParticipant
RequestTarget typed links
ExternalCorrelation links
Authority version/snapshot
OfferingSelection
ResourceRequirementTemplate
CommitmentRequirement
ReservationItem
ResourceAllocation
FulfillmentModel
PaymentAllocation
PaymentAllocationAdjustment
PaymentInstruction
PriceDetermination components
```

Persistence-internal structures may exist without becoming domain vocabulary:

```text
CapacityAuthority
CapacityClaim
ScheduleAuthority / AvailabilityRevision
```

No noun-to-table mapping automático.

---

## 6. Tenancy and referential integrity

Toda critical tenant-owned relation debe poder demostrar:

```text
child.organization_id == parent.organization_id
```

Prefer tenant-aware composite FKs where practical.

### No generic polymorphic authoritative FK

Forbidden for critical relationships:

```text
entity_type
entity_id
```

when it bypasses actual FK integrity.

Examples that require typed relational design:

```text
RequestTarget
PriceDetermination scope
capacity allocation target
financial provenance links
```

Use one of:

```text
explicit typed FK/link tables
real common relational supertype
XOR constrained typed FKs
```

Do not trade referential integrity for schema convenience.

---

## 7. Identity and authority transaction semantics

Authentication:

```text
credential/session → Organization → Principal → scopes
```

Business identity:

```text
channel/external identity → verified Party when possible
```

Authorization:

```text
Principal
+ tenant
+ capability
+ Party/subject correlation
+ local AuthorityGrant/Representation
+ entity state
+ policy/version
```

### Local authority rule

Strong serializable authorization can only depend on authority represented locally in the same PostgreSQL authority boundary.

External authority is materialized as a verified snapshot/reference:

```text
source
verified_at
valid_until?
version/hash/reference
revocation state known locally
```

No claim of instantaneous external revocation awareness.

### Authority race

For revocable local authority:

```text
BEGIN
  lock/read current authority version
  validate active + scope
  lock target aggregate
  validate current target state
  mutate
  persist authority decision snapshot in audit
COMMIT
```

Revocation and dependent mutation therefore serialize.

---

## 8. Request serialization boundary

`Request` is the serialization root for changes that alter its outcome obligations or terminality.

Commands that can change:

```text
OfferingSelections
recipient scope
required fulfillment components
required approvals
workflow outcome criteria
terminal status
```

must revision-check/lock the Request.

`CompleteRequest` must lock/revalidate the same root before terminal transition.

A terminal Request is not reopened by later financial/operational events.

---

## 9. RequestTarget physical rule

`RequestTarget` is semantically typed and closed by RequestType.

Do not implement as opaque polymorphic `(target_type, target_id)`.

For V1, target relationships should be explicit per supported kind, for example a typed reservation target relation for cancel/reschedule flows.

If future target kinds proliferate enough to justify a true common supertype, introduce it deliberately rather than simulating one.

---

## 10. Cross-channel and operation identity

External correlation is N:M semantically.

### Transport idempotency

Retry protection scoped to:

```text
organization
operation
caller/context
idempotency key
canonical payload hash
```

### Durable operation identity

Server-generated operation/action token may survive controlled handoff across Website → WhatsApp → Voice → Human.

Replay returns same logical outcome/reference, but response fields are filtered under current read authorization.

---

## 11. Workflow persistence

Conceptual Request workflow state:

```text
workflow_key
workflow_version
workflow_status
current_step
next_action_at
revision
typed/versioned workflow payload only where necessary
```

Outcome criteria cannot live solely in opaque JSON.

No generic state-machine framework.

---

## 12. Pricing persistence rule

`PriceDetermination` preserves:

```text
priced scope
pricing source/policy + version
base Money
quantity semantics
adjustments
final Money
provenance
override Principal/reason
```

Priced scope must use typed relational links rather than opaque generic object identifiers for authoritative provenance.

PaymentRequirement separately stores/references amount derivation:

```text
commercial basis
payment policy/version
calculation inputs
required Money
```

No FX implicit.

---

## 13. Capacity architecture — key V2.4 change

The domain keeps these distinct:

```text
Resource
CapacityPool
CapacityHold
ResourceAllocation
```

The persistence model should likely use two internal concepts:

### CapacityAuthority

Stable row/identity against which capacity-changing transactions can lock.

One Resource or CapacityPool that can be reserved has one authoritative capacity identity.

Conceptually:

```text
CapacityAuthority
  organization
  capacity_model
  revision
  schedule_revision / availability_revision
  active/config state
```

This can be implemented as a true supertype or equivalent typed authority rows. The key requirement is **one deterministic lock target**.

### CapacityClaim

Physical/common conflict-space representation for capacity consumption.

Conceptual fields:

```text
organization
capacity_authority
origin kind/reference: hold | allocation
interval
quantity
claim state
expires_at when hold-backed
```

`CapacityClaim` is not a domain aggregate exposed to API. It exists so Holds and confirmed Allocations can conflict in the same PostgreSQL relation/protocol.

---

## 14. Exclusive capacity enforcement

For `exclusive` authority, preferred physical strategy:

```text
CapacityClaim rows
+ PostgreSQL range type
+ exclusion constraint over live claims
```

Important: Hold claims and Allocation claims must participate in the same relation or equivalent serialization mechanism. Separate tables with independent exclusion constraints are insufficient because they cannot detect cross-table overlap.

A live hold is logically live only while:

```text
state = active
AND expires_at > authoritative wall-clock time
```

Cleanup worker materializes expiry but does not define temporal truth.

If exclusion design cannot express time-based liveness directly, the transaction protocol must ensure stale expired claims are retired/ignored safely before conflict insertion.

---

## 15. Unit capacity enforcement

For `units`, exclusion constraint alone is insufficient.

Preferred V1 protocol:

```text
LOCK CapacityAuthority
revalidate authority/schedule revision
calculate overlapping live claim sum
validate requested quantity
insert/update claim
COMMIT
```

This intentionally serializes contention on scarce capacity.

Do not implement check-then-insert without authority lock.

Do not prematurely shard capacity authorities; measure first.

---

## 16. Schedule and availability authority

Schedule rows/exceptions alone are not adequate lock targets because concurrent insertion creates phantom races.

Every reservable Resource/Pool requires a stable authority revision that changes when capacity-affecting configuration changes:

```text
schedule edits
ScheduleException insertion/update
capacity override
pool membership changes
eligibility/fungibility configuration changes
resource unavailable state
```

CapacityHold/confirmation protocol:

```text
LOCK CapacityAuthority
read current schedule/availability revision
re-evaluate date-specific schedule
re-evaluate live claims
commit claim
```

Schedule mutation protocol:

```text
LOCK same CapacityAuthority
apply schedule/config mutation
increment revision
detect commitments potentially affected
commit + outbox recovery work
```

Thus:

```text
claim wins first → schedule change sees existing commitment → disruption/recovery
schedule change wins first → subsequent claim sees new revision and fails/recomputes
```

---

## 17. Canonical lock ordering

Any command locking multiple authorities must acquire them in deterministic canonical order.

Suggested conceptual ordering key:

```text
organization_id
lock_class
internal_id
```

Lock classes themselves must be ordered globally, e.g.:

```text
AUTHORITY/REPRESENTATION
REQUEST
RESERVATION
CAPACITY_AUTHORITY
PAYMENT_TRANSACTION
PAYMENT_REQUIREMENT
RECONCILIATION_CASE
```

Exact physical order may differ, but must be documented and used consistently.

PostgreSQL deadlock detection is fallback protection, not primary lock strategy.

---

## 18. CommitmentRequirement and partial cancellation

Reservation is structural serialization root for commitment amendments.

For shared requirements:

```text
Item A ─┐
        ├→ Requirement X
Item B ─┘
```

partial cancellation protocol:

```text
LOCK Reservation
lock/revision-check affected CommitmentRequirements/claims as needed
mark/remove affected item scope
recompute surviving requirement coverage
release/replace capacity only if no surviving scope needs it
commit atomically
```

Two concurrent item cancellations cannot both independently decide the other surviving item still owns the shared allocation.

---

## 19. CapacityPool architecture

V1 supports member-derived reservable pools only.

### Contributor exclusivity

A Resource cannot contribute the same reservable capacity to overlapping pools that can claim it concurrently.

### Pool/direct claim concurrency

A direct claim on a contributing Resource must serialize with the relevant pool authority as well as the concrete Resource authority.

Because V1 forbids overlapping reservable contributors, the lock set remains bounded.

### Fungibility

Unresolved late binding is allowed only when candidate members are interchangeable for the CommitmentRequirement at reservation time.

If capability/eligibility leaves only a subset where generic pool arithmetic would be misleading, bind concrete Resource during Hold/confirmation.

### Pool mutation

Membership/eligibility changes lock/increment the pool authority revision and detect affected commitments.

---

## 20. ResourceAllocation and binding

ResourceAllocation is domain truth linking CommitmentRequirement to capacity.

Binding strategies may use:

1. pool claim + concrete realization reference that does not consume another pool unit; or
2. atomic replacement preserving lineage.

Whichever is chosen must prove:

```text
pool unit not double-counted
member not double-booked
claim lineage preserved
```

No independent Assignment source of truth.

---

## 21. Reservation lifecycle transaction rules

States:

```text
confirmed
cancelled
closed
```

Terminal transition protocol must atomically ensure:

```text
no active capacity-consuming claims remain
```

`SetReservationStatus` generic command is forbidden.

Close/cancel is a semantic command that releases claims, evaluates admission/session constraints, writes audit/event/outbox, then changes terminal status in one transaction.

---

## 22. Admission and ServiceSession concurrency

CheckIn, QueueEntry and no-show use explicit admission scope.

Cancellation/reschedule that may conflict with active execution must inspect/lock relevant Reservation plus active ServiceSession linkage/current session state.

If execution has started, policy chooses legal transition such as reject cancellation, stop/partial outcome, or manual override.

---

## 23. Dispatch boundary

Dispatch = movement toward one Destination.

May link multiple Reservations only when destination/movement semantics are shared.

Cancellation of Reservation does not automatically mutate Dispatch outside transaction if Dispatch also serves surviving Reservations; command/application policy determines whether Dispatch remains, changes linkage, or is compensated asynchronously.

No route graph inside Request Engine.

---

## 24. Payment transaction authority

PaymentTransaction is natural lock target for operations spending/refunding its financial value.

### Positive allocations

Protocol:

```text
LOCK PaymentTransaction
lock PaymentRequirements in canonical order when needed
recompute eligible transaction value
recompute existing allocations/adjustments
validate new allocation
insert
```

Invariant:

```text
sum(net eligible positive contribution) <= eligible transaction value
```

---

## 25. PaymentAllocationAdjustment two-sided budget

Creating invalidating adjustment requires protecting two budgets:

```text
source reversal budget
allocation contribution budget
```

Protocol:

```text
LOCK FinancialReversal/source financial fact
LOCK affected PaymentAllocation(s) in canonical order
validate sum adjustments from reversal <= reversal amount
validate sum invalidation against allocation <= eligible contribution
insert adjustment
```

If attribution cannot be determined, create/continue ReconciliationCase instead of inventing allocation effects.

---

## 26. Refund concurrency

Refund creation locks original PaymentTransaction/value authority and validates:

```text
pending + succeeded refundable claims <= refundable amount allowed by policy/facts
```

Concurrent external reversal still must be recorded even if it creates a deficit/negative net position. That conflict becomes reconciliation; external financial facts are not rejected because local refund already occurred.

---

## 27. Provider event ingestion

Dedupe identity is scoped to the provider connection/account semantics, not assumed globally.

Conceptual uniqueness:

```text
PaymentProviderConnection + provider_event_id
```

Same event identity + same canonical payload → duplicate/replay.

Same event identity + materially different payload → integrity/security conflict requiring audit/review.

Flow:

```text
receive
→ authenticate/signature
→ dedupe envelope
→ persist minimal/raw reference safely
→ normalize
→ execute internal command
→ record outcome
```

Out-of-order events never blindly regress internal state.

---

## 28. Idempotency storage

Persist conceptually:

```text
organization
operation
caller/context scope
idempotency key
canonical request hash
logical result reference
status
created/expires timestamps
```

Same key + different hash → conflict.

Response snapshot is not an authorization bypass; serialize response under current read policy.

---

## 29. Transactional outbox

Domain mutation + outbox append = same DB transaction.

Workers use claim protocol such as `FOR UPDATE SKIP LOCKED` or equivalent.

Delivery is at-least-once. Consumers idempotent.

---

## 30. Time semantics

Persist instants in UTC.

Local input uses IANA timezone and explicit ambiguity handling.

Hold expiry logic must use database wall-clock semantics appropriate to the decision. Do not accidentally depend on transaction-start `now()` for a long-running expiry-sensitive transaction.

Transactions should remain short; expiry checks occur immediately before authoritative state transition.

---

## 31. Availability projections

Availability caches/materialized slots are projections only.

Booking flow always revalidates under capacity authority lock/revision before creating Hold/Reservation claim.

Never reserve solely because a cached slot says `available=true`.

---

## 32. Commands — lock ownership examples

### CreateCapacityHold

```text
READ: Request/Selection snapshot, requirement templates
LOCK: involved CapacityAuthorities canonical order
VALIDATE: authority revisions, schedule, pool fungibility, live claims
WRITE: CapacityHold + CapacityClaims
EMIT: audit/domain event/outbox if needed
```

### ConfirmReservation

```text
LOCK: CapacityHold + involved CapacityAuthorities + Request/Reservation creation boundary as needed
VALIDATE: hold still logically live, authority revisions, payment policy
WRITE: Reservation, items, CommitmentRequirements, ResourceAllocations; transform/realize claims atomically
EMIT: audit/event/outbox
```

### CancelReservationScope

```text
LOCK: Reservation + affected CapacityAuthorities/claims + relevant session/admission state
VALIDATE: policy, authority, surviving shared requirements
WRITE: item/requirement/allocation replacements/releases; terminal status only if no commitment remains
EMIT: financial consequences/outbox
```

### CompleteRequest

```text
LOCK: Request
VALIDATE: current version + typed outcome criteria against facts
WRITE: terminal Request state
EMIT: audit/event/outbox
```

### AllocatePayment

```text
LOCK: PaymentTransaction + Requirements canonical order
VALIDATE: eligible financial value/currency/current net allocations
WRITE: PaymentAllocation
```

### ApplyAllocationAdjustment

```text
LOCK: reversal/source fact + PaymentAllocations canonical order
VALIDATE: two-sided budgets
WRITE: adjustment or ReconciliationCase
```

---

## 33. Test matrix before schema freeze

Required concurrent/integration tests:

```text
cross-tenant FK rejection
polymorphic-link prohibition/typed FK integrity
exclusive hold-vs-allocation overlap
unit capacity oversell
concurrent last-unit holds
schedule exception vs hold creation
pool membership mutation vs hold
pool claim vs direct member booking
heterogeneous pool rejection/bind-concrete path
Hold confirm-vs-expire
shared requirement concurrent partial cancellation
Reservation close with active claims rejected
resource unavailable vs confirmation
multi-resource lock ordering/deadlock retry
Request completion vs concurrent obligation amendment
authority revocation vs dependent mutation
PaymentAllocation overspend
partial reversal two-sided budget
refund-vs-refund
refund-vs-external reversal
duplicate provider event
duplicate event id with different payload
out-of-order provider event
late payment after Hold expiry
concurrent reconciliation
idempotency same key/different payload
idempotent replay after read authorization revocation
outbox duplicate delivery
DST ambiguous/nonexistent local time
```

---

## 34. Schema design gate

Before writing final SQL, `docs/02-pre-sql-domain-contract.md` must map every critical invariant to one of:

```text
FK/unique/check/exclusion constraint
stable lock authority + transaction protocol
optimistic version check
bounded application policy where DB enforcement is impossible/irrelevant
```

If a critical invariant is defended only by “the service will check first”, the architecture is not ready.