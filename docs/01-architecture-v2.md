# Request Engine V2.5 — arquitectura de referencia

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

La arquitectura debe mantener autoridad bajo retries, duplicate/out-of-order callbacks, races de capacity, schedule/location changes, authority revocation, compound reservations, late payments, financial reversals, cross-channel handoffs y concurrent recovery.

---

## 2. Stack

### PostgreSQL

Source of truth para:

```text
tenant isolation
referential integrity
capacity conflict protection
compound commitment atomicity
stable lock authorities
row/advisory locking where justified
exclusion/unique/check constraints
optimistic versioning
financial allocation/finality invariants
idempotency
transactional outbox
authoritative business/audit facts
```

### Python + FastAPI

Domain/application/workers/integrations en Python. FastAPI es transport, no domain boundary.

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

## 4. Dependency and transaction rule

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

External data requerido por una decisión debe obtenerse antes y convertirse en validated snapshot/reference, o procesarse asincrónicamente después del commit.

---

## 5. Aggregate philosophy

Probables roots/boundaries:

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
PaymentTransaction observation/value authority
Refund
PaymentDispute
ReconciliationCase
ServiceSession
Dispatch only if lifecycle justifies root status
```

Children/value objects/links:

```text
RequestParticipant
RequestTarget typed links
ExternalCorrelation links
Representation version/snapshot
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

Persistence-internal:

```text
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision / AvailabilityRevision
```

No noun-to-table mapping automático.

---

## 6. Tenancy and typed referential integrity

Toda critical tenant-owned relation debe probar:

```text
child.organization_id == parent.organization_id
```

Prefer tenant-aware composite FKs where practical.

Forbidden for authoritative references:

```text
entity_type
entity_id
```

si bypassa FK integrity.

Usar explicit typed links, real relational supertype o XOR-constrained typed FKs.

Public/external IDs nunca son authority.

---

## 7. Identity and Representation serialization

Authentication:

```text
credential/session → Organization → Principal → scopes
```

Business identity:

```text
channel/external identity → Party correlation/verification
```

Authorization:

```text
Principal
+ tenant
+ capability
+ Party/subject correlation
+ current Representation
+ target state
+ policy/version
+ idempotency
```

Para authority local revocable:

```text
BEGIN
  lock/read Representation current version
  validate active + scope
  lock target aggregate when needed
  validate target state
  mutate
  persist authority decision snapshot
COMMIT
```

External authority usa verified snapshot/reference; no se promete atomic awareness de revocación remota.

---

## 8. Request serialization boundary

`Request` es serialization root para cambios que alteren:

```text
OfferingSelections
recipient/requested scope
required fulfillment components
required approvals
workflow outcome criteria
terminal state
```

`CompleteRequest` y cualquier amendment de required outcome usan la misma Request revision/lock.

Terminal Request no se reabre por eventos financieros u operacionales posteriores.

---

## 9. RequestTarget and cross-channel identity

RequestTarget es tipado y cerrado por RequestType; no generic polymorphic FK.

ExternalCorrelation es N:M y nunca autoriza.

Transport idempotency se scopea a:

```text
organization
operation
caller/context
idempotency key
canonical payload hash
```

Durable operation identity puede sobrevivir Website → WhatsApp → Voice → Human, pero replay reevalúa current read authorization.

---

## 10. Workflow persistence

Conceptual Request workflow state:

```text
workflow_key
workflow_version
workflow_status
current_step
next_action_at
revision
typed/versioned payload only where necessary
```

Outcome criteria no pueden existir sólo en opaque JSON.

No generic state-machine framework.

---

## 11. Pricing and obligation derivation

`PriceDetermination` preserva scope tipado, policy/version, Money, quantity semantics, adjustments, provenance y overrides.

`PaymentRequirement` preserva commercial basis + PaymentPolicy/version + calculation inputs + required Money.

No FX implícito.

Tax/fee calculation sólo se considera owned por Request Engine cuando una policy explícita del producto lo declara; de lo contrario se conserva resultado/provenance de una source externa.

---

## 12. Capacity architecture V2.5

Dominio:

```text
Resource
CapacityPool
CapacityHold
ResourceAllocation
```

Persistence interna:

### CapacityAuthority

Stable row/identity que todas las operaciones capaces de consumir o cambiar la misma capacity pueden identificar y lockear.

Conceptualmente:

```text
organization
capacity model
revision
schedule/location/availability revision
active/config state
```

### CapacityClaim

Common conflict-space para claims originados por Holds o active Allocations.

Conceptualmente:

```text
organization
capacity authority
origin kind/reference
interval
quantity
claim state
expires_at when hold-backed
```

Hold y Allocation permanecen semánticamente distintos aunque sus claims compitan físicamente en el mismo espacio.

---

## 13. Compound CapacityHold protocol — blocker cerrado

`CapacityHold` es un commitment set, no un claim individual.

### Required invariant

> Si un requested commitment necesita múltiples mandatory requirements, la adquisición es all-or-nothing dentro de una única DB transaction.

Ejemplo:

```text
Hold H
├─ dentist authority
├─ chair authority
├─ room authority
└─ xray authority
```

### CreateCapacityHold

```text
READ:
  Request/OfferingSelection snapshot
  requirement templates
  intended interval/location context

PLAN:
  materialize required claim intents
  resolve concrete/pool authority candidates
  derive complete deterministic lock set

LOCK:
  involved CapacityAuthorities in canonical order

VALIDATE:
  Request version/scope still current
  authority active/config revisions
  schedule/location eligibility
  pool fungibility
  resource capability
  transition/field feasibility snapshot if required
  all live claims
  hold policy/expiry

WRITE atomically:
  one CapacityHold
  all mandatory CapacityClaims
  coverage lineage to requirement intents

EMIT:
  audit/domain event/outbox
```

Failure at any mandatory claim rolls back the entire transaction.

Partial commitment requires an explicit workflow/policy declaration that separates independent requirement groups before the transaction. Storage failure, contention or unavailable resource never implicitly creates a partial Hold.

---

## 14. Hold confirmation protocol

### ConfirmReservation

```text
LOCK:
  CapacityHold
  Request as required
  involved CapacityAuthorities canonical order

VALIDATE:
  Hold state=active
  expires_at > authoritative wall clock immediately before transition
  complete mandatory claim set still exists
  authority/schedule/location revisions still compatible
  payment/admission prerequisites
  every mandatory CommitmentRequirement will be fully covered

WRITE atomically:
  Reservation
  ReservationItems
  CommitmentRequirements
  ResourceAllocations
  transform/repoint all relevant CapacityClaims
  Hold → confirmed

EMIT:
  audit/event/outbox
```

Forbidden committed state:

```text
Reservation confirmed
AND any mandatory CommitmentRequirement under-covered
```

---

## 15. Exclusive and unit capacity enforcement

### Exclusive

Preferred:

```text
common CapacityClaim relation
+ PostgreSQL range type
+ exclusion constraint for incompatible live claims
```

Separate Hold and Allocation exclusion constraints are insufficient.

### Units

```text
LOCK CapacityAuthority
revalidate revision/schedule/location
sum overlapping logically-live claims
validate requested units
insert/transform claims
COMMIT
```

Correctness before throughput optimization.

---

## 16. Hold expiry and authoritative clock

A Hold is logically live only when:

```text
state = active
AND expires_at > authoritative current time
```

Cleanup worker no define la verdad.

Expiry-sensitive checks usan wall-clock semantics apropiados; no asumir transaction-start `now()` en transacciones largas.

Late payment nunca reactiva expired Hold.

---

## 17. Schedule/location authority and phantom races

Schedule rows/exceptions no son stable lock targets por sí mismas.

Todo cambio que afecte reservability debe lock/increment la misma authority revision que booking consume:

```text
schedule edit
ScheduleException
capacity override
Resource unavailable
Resource operating-location eligibility
CapacityPool membership
fungibility/eligibility change
```

Protocol:

```text
claim wins first
→ configuration mutation sees commitments
→ marks affected operational scope / emits recovery

configuration mutation wins first
→ later Hold sees new revision and fails/recomputes
```

Un Resource multi-location sigue siendo un Resource; location eligibility participa en schedule/capacity validation, no mediante duplicación del Resource.

---

## 18. Canonical lock ordering

Toda operation multi-authority usa orden global determinista.

Conceptual ordering:

```text
organization_id
lock_class
internal_id
```

Lock classes iniciales:

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

La lista final se documenta antes de SQL. PostgreSQL deadlock detection/retry es fallback, no estrategia primaria.

Nunca descubrir nuevas rows que debieron lockearse después de adquirir una parte del set en orden incompatible; primero PLAN, luego LOCK.

---

## 19. Shared requirements and partial cancellation

Reservation es structural serialization root para commitment amendments.

```text
Item A ─┐
        ├→ Requirement X
Item B ─┘
```

CancelReservationScope:

```text
LOCK Reservation
PLAN surviving scope
LOCK affected CapacityAuthorities canonical order
VALIDATE policy/session/admission + surviving coverage
WRITE item/requirement/allocation releases/replacements atomically
terminal Reservation only if no commitment survives
EMIT amendment provenance + financial consequences/outbox
```

Dos cancellations concurrentes no pueden dejar orphan claims ni liberar shared capacity aún requerida.

---

## 20. CapacityPool binding

V1 sólo member-derived fungible pools.

Direct Resource claim y relevant Pool claim serializan juntos.

Pool → concrete realization usa:

1. realization reference que no crea segundo consumption; o
2. atomic claim replacement con lineage.

Debe probar:

```text
pool unit not double-counted
member not double-booked
claim lineage preserved
```

No independent Assignment source of truth.

---

## 21. Reservation lifecycle

```text
confirmed
cancelled
closed
```

No generic `SetReservationStatus`.

Close/cancel commands deben atomically:

```text
validate authority/policy
inspect active admission/session constraints
release/replace consuming claims
persist amendment/audit provenance
write terminal state only after zero active consuming claims
```

---

## 22. Admission and queue concurrency

Admission operations usan explicit AdmissionScope identity.

### CheckIn

Presence/readiness fact para scope concreto.

### QueueEntry

Persistir lifecycle + ordering inputs, no una posición absoluta como verdad durable.

Ejemplos de ordering inputs:

```text
joined_at
priority class
appointment entitlement
policy version
manual override provenance
```

Current position/ETA son projections.

Cancellation/check-in/start-session races serializan contra Reservation/AdmissionScope/ServiceSession según el caso.

No-show es scoped fact/policy decision, nunca Reservation status.

---

## 23. ServiceSession and Fulfillment transaction rules

`ServiceSession` representa ejecución.

`Fulfillment` aplica outcome evidence a exactamente un Request requested scope.

### RecordFulfillment

```text
READ:
  Request requested scope
  OfferingSelection/FulfillmentModel version
  recipient scope
  ServiceSession/external evidence source

LOCK:
  Request when fulfillment can satisfy completion criteria or race with requested-scope amendment

VALIDATE:
  scope belongs to Request
  quantity/components valid for model
  remaining arithmetic valid when applicable
  evidence/source authority

WRITE:
  append Fulfillment
  correction/supersession lineage if applicable

EMIT:
  audit/event/outbox
```

A ServiceSession que satisface dos Requests produce Fulfillment records separados por Request scope.

`CompleteServiceSession` no implica automáticamente `CompleteRequest`.

---

## 24. Amendment Contract implementation

No `GenericAmendment` aggregate.

Todo semantic command post-commitment que altera materialmente scope/consequences debe escribir audit/domain lineage suficiente para reconstruir:

```text
operation identity
initiator/represented Party
reason
policy/version
before entity revisions/references
after entity revisions/references
created/released/replaced links
evaluated inputs
override provenance
occurred_at
```

Esto aplica a reschedule, partial cancellation, resource replacement, destination change, repricing, payer/recipient correction material y recovery.

Implementación puede ser command-specific typed records + AuditRecord/DomainEvent; no requiere universal amendment table si las FKs materiales viven en sus módulos.

---

## 25. Field-service feasibility invalidation

V1 permite:

```text
fixed/conservative transition buffers
OR
external feasibility snapshot
```

External snapshot debe incluir provenance y inputs relevantes, por ejemplo:

```text
origin/destination reference
resource/vehicle context
planned interval
provider/source
verified_at
valid_until? / policy version
```

Material changes a Destination, interval, assigned Resource/vehicle o schedule invalidan la snapshot.

### ChangeDispatchDestination

No overwrite silencioso.

```text
LOCK Dispatch + relevant Reservation(s)
VALIDATE authority/policy/current dispatch state
WRITE destination change lineage
INVALIDATE previous feasibility snapshot
RE-EVALUATE synchronously if local/conservative, or mark blocked/pending external recheck
EMIT outbox/recovery
```

No route graph en core.

---

## 26. Financial observation model V2.5

`PaymentTransaction` es financial fact + natural value authority para allocation/refund coordination.

Conceptualmente conserva:

```text
direction
Money
source/provider/account reference
external transaction identity
occurred/effective time
observed time
counterparty reference when known
financial status/finality
eligible value
observation provenance
correction/reversal lineage
```

Adapters normalizan source-specific states a policy-governed semantics; el dominio no asume que `succeeded`, `captured`, `posted`, `settled` o `cash received` son equivalentes.

### Eligibility vs finality

Financial source policy/version decide qué state puede aportar `eligible value`.

Ejemplo:

```text
card authorization      → 0 eligible
captured PSP payment    → policy may allow provisional eligible value
bank posted transfer    → policy may allow available/final value
PaymentEvidence         → 0 eligible
PaymentAttempt.success  → 0 eligible by itself
```

Request Engine preserva finality/provenance aunque una business policy acepte valor provisional.

---

## 27. RecordPaymentTransaction protocol

Provider/bank/manual source:

```text
AUTHENTICATE source/principal
DEDUPE source event/transaction identity where available
NORMALIZE financial state/finality under source policy version

BEGIN
  validate tenant/provider connection/account context
  lock existing transaction observation/value authority when updating known external operation
  append/update only semantically legal observation facts
  derive current eligible value without deleting history
  write audit/event/outbox
COMMIT
```

Out-of-order callbacks pueden añadir facts o advance knowledge; nunca blindly regress domain state.

Same event identity + materially different payload → integrity/security conflict.

---

## 28. Manual financial verification protocol

Manual verification es privileged semantic command, no generic create-transaction endpoint.

Required checks:

```text
Principal capability
Organization scope
source/account/cash context
amount/currency
observed evidence/reference
occurred_at/observed_at
policy/version
reason
optional dual-control requirement
idempotency
```

Si tenant policy exige four-eyes control, primera acción crea pending review/case/evidence y un Principal distinto debe aprobar antes de generar eligible authoritative value.

AI/screenshot analysis jamás ejecuta este command por inferencia visual sola.

---

## 29. Payment allocation and adjustment protocols

### AllocatePayment

```text
LOCK PaymentTransaction
LOCK PaymentRequirements canonical order
VALIDATE current eligible value, currency, current net allocations, requirement disposition
WRITE PaymentAllocation
```

Invariant:

```text
sum(net allocations) <= eligible transaction value
```

### ApplyAllocationAdjustment

```text
LOCK FinancialReversal/source fact
LOCK affected PaymentAllocations canonical order
VALIDATE reversal budget + allocation contribution budget
WRITE adjustment OR ReconciliationCase
```

Ambiguous attribution no se adivina.

---

## 30. Refund, reversal and dispute concurrency

Refund creation locks original PaymentTransaction/value authority and validates:

```text
pending + succeeded refundable claims
<= currently refundable amount under policy/facts
```

External reversal/dispute facts siempre se registran aunque un local Refund ya exista. Si ambos producen deficit, se conserva la realidad y se abre reconciliation; no se rechaza el hecho externo para mantener una ilusión contable.

Original PaymentTransaction y Fulfillment no se borran.

---

## 31. Provider event ingestion

Conceptual dedupe cuando provider garantiza IDs:

```text
PaymentProviderConnection + provider_event_id
```

Flow:

```text
receive
→ authenticate/signature
→ dedupe envelope
→ persist safe raw/minimal reference
→ normalize
→ execute internal semantic command
→ record outcome
```

Webhook payload no es domain command directo.

---

## 32. Idempotency storage

Persist conceptualmente:

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

Same key + same hash → replay logical outcome.

Same key + different hash → conflict.

Current authorization siempre se reevalúa para response visibility.

---

## 33. Transactional outbox

Business mutation + outbox append = same DB transaction.

Workers pueden usar `FOR UPDATE SKIP LOCKED` o equivalente para claim de trabajo.

Delivery es at-least-once; consumers son idempotentes. No diseñar bajo ilusión de exactly-once external effects.

---

## 34. Time semantics

Persistir instants UTC.

Local input usa IANA timezone + explicit resolution of ambiguous/nonexistent time.

Hold expiry usa authoritative wall-clock check inmediatamente antes de state transition.

Planned and actual timestamps permanecen separados.

---

## 35. Availability projections

Availability, materialized slots, queue position/ETA, operational health y payment labels son projections.

Pueden cachearse/materializarse, pero:

```text
rebuildable
not arbitrary write endpoints
never sufficient authority for commitment/payment mutation
```

CreateCapacityHold siempre revalida bajo authoritative locks.

---

## 36. Command proof catalogue before schema freeze

Cada command crítico debe documentar `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT`.

Mínimo:

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
AllocatePayment
ApplyAllocationAdjustment
RequestRefund
RecordFinancialReversal
Open/ResolvePaymentDispute
Open/ResolveReconciliationCase
```

---

## 37. Required race/integration test matrix

```text
cross-tenant FK rejection
hallucinated public ID tenant escape rejection
exclusive hold-vs-allocation overlap
unit capacity oversell
compound hold all-or-nothing across 3+ authorities
compound hold rollback on final authority conflict
concurrent compound holds with opposite input ordering
schedule/location mutation vs compound hold
pool membership mutation vs hold
pool claim vs direct member booking
heterogeneous pool bind-concrete path
Hold confirm-vs-expire
Hold payment-arrival-vs-expiry
Reservation confirmation with missing mandatory coverage rejected
shared requirement concurrent partial cancellation
Reservation close with active claims rejected
resource unavailable vs confirmation
Request completion vs concurrent outcome amendment
authority revocation vs mutation
check-in vs cancellation
start-session vs cancellation
queue ordering concurrent joins/priority override
Destination change invalidates feasibility
destination change vs dispatch en_route
Fulfillment vs requested-scope amendment
one ServiceSession fulfilling multiple Requests
Fulfillment correction lineage
PaymentEvidence cannot satisfy requirement
PaymentAttempt success cannot satisfy requirement
financial pending→available/final out-of-order callbacks
manual payment verification unauthorized rejection
dual-control manual verification same-Principal rejection
PaymentAllocation overspend
eligible-value reduction vs concurrent allocation
partial reversal two-sided budget
refund-vs-refund
refund-vs-external reversal
duplicate provider event
duplicate event id different payload
late bank transfer after Hold expiry
concurrent reconciliation
idempotency same key/different payload
idempotent replay after read authorization revocation
outbox duplicate delivery
DST ambiguous/nonexistent local time
```

---

## 38. Schema design gate

Antes de final SQL, `docs/02-pre-sql-domain-contract.md` debe mapear cada critical invariant a:

```text
FK/unique/check/exclusion constraint
stable lock authority + transaction protocol
optimistic version check
bounded application policy where DB enforcement is impossible/irrelevant
```

Un invariant crítico defendido sólo por “the service checks first” bloquea schema freeze.
