# Request Engine V2.3 — arquitectura de referencia

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

El sistema debe mantener autoridad bajo retries, callbacks duplicados/desordenados, races de capacity, cambios de Resource, payments tardíos, authority revocation concurrente, handoffs multicanal y partial financial reversals.

---

## 2. Stack

### PostgreSQL

Source of truth para:

```text
tenant isolation
referential integrity
capacity conflict protection
row/advisory locking where justified
exclusion/unique/check constraints
optimistic versioning
financial allocation/adjustment invariants
idempotency
transactional outbox
authoritative business/audit facts
```

### Python + FastAPI

Domain/application/workers/integrations en Python; FastAPI como transport.

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

---

## 5. Aggregate philosophy V2.3

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
RequestTarget
ExternalCorrelation
Authority version/snapshot components
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

No noun-to-table mapping automático.

---

## 6. Tenancy e IDs

Relaciones críticas deben garantizar:

```text
child.organization_id == parent.organization_id
```

Preferir tenant-aware composite references para critical FKs.

Public IDs separados de PKs internos. External provider IDs nunca son primary identity. Public/request IDs no son authorization tokens.

---

## 7. Identity, authority y concurrency

Authentication:

```text
credential/session → organization → Principal → scopes
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
+ AuthorityGrant/Representation
+ entity state
+ policy/version
```

### Authority as transactional dependency

Si un command requiere authority revocable, la transaction debe revalidar la versión/current state relevante antes de commit.

Patrón conceptual:

```text
BEGIN
  lock/read authority version
  validate active + scope
  validate target state
  apply mutation
  persist authority decision snapshot/version in audit
COMMIT
```

Una cached authority decision fuera de la transaction no basta para high-risk mutations.

---

## 8. Request targeting vs lineage

Request puede producir Reservations/Fulfillments, pero también puede actuar sobre una entidad preexistente.

No mezclar:

```text
Request → generated Reservation lineage
```

con:

```text
CancelReservationRequest → RequestTarget(Reservation X)
```

`RequestTarget` es child tipado, no polymorphic generic graph abierto. Los target kinds permitidos se validan por RequestType/application command.

---

## 9. Cross-channel and operation identity

`ExternalCorrelation` es link N:M semántico entre external interaction identities y Requests.

No imponer uniqueness que fuerce un thread externo a un solo Request.

### Two idempotency layers

1. **transport idempotency** — retry de la misma operación/caller;
2. **durable operation identity** — token server-generated que puede continuar entre channels/principals durante un handoff controlado.

No deduplicar intenciones humanas distintas automáticamente.

Idempotency replay devuelve mismo logical outcome/reference, pero serializa la respuesta según autorización de lectura vigente.

---

## 10. Request/workflow execution

Persistencia conceptual:

```text
workflow_key
workflow_version
workflow_status
current_step
next_action_at
revision
typed/versioned workflow data only where needed
```

Completion criteria materiales no pueden existir sólo como opaque JSON boolean. Deben mapear a facts tipados/versionados: fulfillment requirements, approval requirements, payment/business disposition requirements u otros criterios explícitos.

Terminal Request no se reabre automáticamente. Eventos posteriores generan nuevo trabajo/case si policy lo exige.

---

## 11. Pricing and PaymentRequirement derivation

`PriceDetermination` conserva commercial value provenance.

`PaymentRequirement` conserva además `amount_derivation`:

```text
pricing/commercial basis
payment policy + version
calculation inputs
required Money
```

Ejemplo: price 55 + 50% deposit → requirement 27.50.

Partial cancellation con shared discounts ejecuta repricing/amendment policy; no automatic line-item proration.

---

## 12. Capacity model: template → commitment requirement

V2.3 sustituye ownership rígido por scope compuesto:

```text
Offering
→ ResourceRequirementTemplate

Reservation
├─ ReservationItem A ─┐
├─ ReservationItem B ─┼→ CommitmentRequirement
└─────────────────────┘          ↓
                         ResourceAllocation(s)
```

`CommitmentRequirement` materializa capability, quantity, interval y coverage scope.

Un requirement puede cubrir uno o varios ReservationItems. Una Allocation satisface el requirement materializado, evitando double count cuando dos items comparten el mismo chair/person/equipment.

La transaction de confirmation debe validar que todos los required commitment requirements quedan satisfechos.

---

## 13. Exclusive and units capacity

### Exclusive

No live incompatible claims overlapping sobre la misma capacity authority.

Preferir PostgreSQL ranges/exclusion constraints donde encajen limpiamente.

### Units

```text
sum(live Hold claims + active Allocation claims) <= effective capacity
```

Requiere serializable locking strategy sobre una authority/bucket apropiada; check-then-insert sin lock es inválido.

---

## 14. CapacityPool architecture

`CapacityPool` es distinto de `Resource` y distinto de query grouping.

V1 sólo soporta **member-derived reservable pools con contributors no superpuestos para la misma capacity authority/interval**.

El modelo físico debe demostrar:

```text
eligible member set
member availability
pool claims
concrete member claims
binding lineage
```

Reglas:

- Resource contributor no puede contar simultáneamente en dos reservable pools competidores durante el mismo intervalo;
- pool claim reduce available fungible capacity;
- concrete binding no vuelve a consumir la misma pool unit;
- concrete Resource no puede estar double-booked;
- membership/schedule changes posteriores generan at-risk/recovery, no history rewrite.

Overlapping dynamic pools se difieren.

---

## 15. CapacityHold confirmation

Hold y Reservation compiten en el mismo conflict space.

```text
active Hold → confirmed
active Hold → released
active Hold → expired
```

Confirmation transforma/realiza claim atómicamente. Nunca debe existir una ventana:

```text
hold released
reservation not yet committed
```

Expiry vs confirm serializan sobre la misma authority/version.

---

## 16. Reservation lifecycle

V2.3:

```text
confirmed
cancelled
closed
```

`expired` se elimina del Reservation lifecycle inicial.

Terminality invariant:

```text
Reservation in {cancelled, closed}
→ no active capacity-consuming allocations remain
```

`closed` puede persistirse si simplifica commands/audit, pero debe ser coherente con capacity facts; si se materializa una projection equivalente, authoritative allocation state gana ante inconsistencia.

Partial cancellation opera por exact item/recipient/quantity scope y no destruye unaffected commitment.

---

## 17. Travel/transition boundary

No implementar pairwise route-aware scheduler general.

V1 acepta:

```text
fixed/conservative transition buffers
OR
external feasibility decision + immutable reference/snapshot
```

Si external feasibility se usa para confirmation, command conserva provenance suficiente para explicar la decisión.

---

## 18. Admission

QueueEntry puede existir sin Reservation. Appointment + QueueEntry también.

Admission records usan recipient/operational scope explícito.

No-show requiere authoritative observation/transition, no `now > start` como verdad permanente.

---

## 19. ServiceSession N:M Reservation

Usar explicit association/link.

Start/complete Session no implica Fulfillment automáticamente.

Cancellation/reschedule de Reservation debe consultar/lockear relevant active session linkage cuando execution state cambia la policy permitida.

Race ejemplo:

```text
T1 StartServiceSession(A,B)
T2 CancelReservation(B)
```

Una sola decisión gana según locks/revisions/policy; no permitir execution activa + cancellation semánticamente incompatible sin corrective workflow.

---

## 20. Fulfillment architecture

Offering snapshot define `FulfillmentModel`:

```text
binary
quantity
components
external_authoritative
```

Fulfillment records son append-oriented.

`quantity` permite remaining arithmetic.

`components` identifica component keys/scopes versionados; no inventar 0.5 de un servicio cualitativo.

Request completion evalúa required outcome scopes, no `ServiceSession.completed`.

---

## 21. Dispatch boundary

Dispatch representa movement hacia un **Destination**.

Puede vincular varias Reservations sólo si comparten ese Destination/movement. Multi-destination route = múltiples Dispatches.

Esto mantiene fuera route planning/optimization.

Cancellation de Reservation no puede dejar Dispatch incompatible activo indefinidamente; compensation/re-evaluation puede ser async post-commit mediante outbox.

---

## 22. Payment facts and allocation

`PaymentAllocation` asigna positive eligible value desde PaymentTransaction a Requirement.

DB/application transaction impide:

```text
sum(net eligible contributions from transaction) > eligible transaction value
```

Overpayment queda unallocated o se reasigna explícitamente.

---

## 23. Partial reversals and PaymentAllocationAdjustment

Un partial reversal sobre una transaction repartida entre varios Requirements es indeterminado sin attribution.

`PaymentAllocationAdjustment` es append-oriented y atribuye invalidación/corrección a una PaymentAllocation concreta (o al scope reconciliable equivalente definido en SQL design).

Flow:

```text
FinancialReversal observed
→ determine attribution from provider/source
   OR apply explicit versioned policy
   OR open ReconciliationCase
→ append PaymentAllocationAdjustment(s)
→ recompute net Requirement satisfaction
```

Nunca prorratear o elegir "latest allocation" implícitamente.

### Refund vs obligation

Refund lifecycle y Requirement disposition se cambian mediante reglas/commands separados pero coordinados.

Ejemplos:

```text
goodwill refund → may not reopen debt
cancellation refund → usually cancel/waive/replace requirement
bank return/reversal → may make requirement outstanding
```

Financial fact nunca dicta por sí solo business obligation disposition.

---

## 24. Refund/reversal concurrency

External reversal no se rechaza porque un refund interno ya esté pending/succeeded.

Puede producir deficit/reconciliation.

Locks protegen refundable budget de operaciones internas, pero authoritative external facts siempre se registran.

`PaymentAllocationAdjustment`/reconciliation determina downstream attribution.

---

## 25. Commands V2.3

### Request / identity

```text
CreateRequest
AddRequestParticipant
AttachRequestTarget
AttachExternalCorrelation
Record/UpdateAuthorityGrant
RevokeAuthorityGrant
ProvideRequestData
AdvanceRequest
CompleteRequest
```

### Capacity / reservation

```text
SearchAvailability              [query]
CreateCapacityHold
ReleaseCapacityHold
ConfirmReservation
CancelReservationScope
RescheduleReservationScope
CloseReservation
BindPoolAllocationToResource
ReplaceResourceAllocation
ReleaseResourceAllocation
```

### Admission / execution

```text
CheckIn
JoinQueue
LeaveQueue
MarkAdmissionNoShow
StartServiceSession
CompleteServiceSession
RecordFulfillment
```

### Field

```text
CreateDispatch
BindDispatchResources
MarkDispatchEnRoute
UpdateDispatchEta
MarkDispatchArrived
CancelDispatch
ChangeDestination
```

### Payments

```text
CreatePaymentRequirement
CancelPaymentRequirement
WaivePaymentRequirement
CreatePaymentAttempt
SubmitPaymentEvidence
RecordFinancialTransaction
AllocatePaymentTransaction
RecordFinancialReversal
AttributeFinancialAdjustment
OpenPaymentReconciliationCase
ResolvePaymentReconciliationCase
RequestRefund
RecordRefundProviderEvent
OpenPaymentDispute
UpdatePaymentDispute
```

No generic `SetPaid`, `SetStatus`, `UpdateAnything`.

---

## 26. Transaction template

```text
BEGIN
  resolve tenant + Principal
  resolve Party/authority if required
  lock relevant authority/state/capacity/financial rows
  validate current revisions
  re-evaluate policy/invariants
  mutate authoritative facts
  append audit/domain events
  append outbox
COMMIT
```

Network calls outside transaction.

---

## 27. Concurrency ownership

### DB/transaction hard guarantees

```text
cross-tenant references
exclusive capacity overlap
units oversell
Hold confirm-vs-expire
pool/member claim correctness
terminal Reservation without active claims
PaymentAllocation overspend
PaymentAllocationAdjustment oversubtraction/invalid references
idempotency uniqueness
provider event dedupe
outbox claim protocol
```

### Application policy + locks/versioning

```text
authority eligibility
partial cancellation semantics
shared discount repricing
reversal attribution policy
Session-vs-cancel race
refund business consequence
workflow completion criteria
```

If breaking a rule can create impossible capacity, duplicated money or cross-tenant leakage, correctness cannot depend on an unlocked Python pre-check.

---

## 28. External callback ingestion

```text
receive
→ authenticate
→ dedupe
→ persist event identity/minimal envelope
→ normalize
→ internal command
→ processed outcome
```

Out-of-order events may append new facts but never blindly regress state.

---

## 29. Transactional outbox

Domain mutation + outbox append same DB transaction.

Workers use claim protocol such as `FOR UPDATE SKIP LOCKED` where appropriate. Delivery remains at-least-once; consumers idempotent.

---

## 30. Audit requirements

Critical audit captures:

```text
organization
Principal
Party/on_behalf_of subject
exact authority version/snapshot reference
action
entity/revision
policy key/version
reason/override
operation identity
correlation/causation
source channel/integration
```

Audit ≠ logs ≠ domain events.

---

## 31. Agent tool design

Tools orientadas a goals:

```text
search_offerings
create_or_continue_request
find_reservation_options
prepare_reservation
confirm_reservation
cancel_reservation_scope
reschedule_reservation_scope
check_in
get_service_status
start_payment
get_payment_status
submit_payment_evidence
```

Mutating tools usan server-managed operation identity/idempotency cuando sea posible y siempre revalidan current authority/state.

No exponer raw joins, locks, capacity buckets, reconciliation internals ni arbitrary setters al LLM.

---

## 32. Boundary decisions

### Inventory

RE conserva external inventory commitment/reference si fulfillment depende de stock. No replica full inventory.

### Routing

RE acepta fixed buffers o external feasibility decisions. No optimiza rutas.

### Workforce

RE conserva capacity/resource availability necesaria para commitments. No HR/optimizer.

### Communications

RE conserva correlation/provenance, no inbox/conversation history universal.

### Accounting

RE conserva obligations y observed financial facts, no general ledger.

---

## 33. Test matrix obligatorio

Antes de schema freeze probar:

```text
shared Resource across multiple ReservationItems without double count
last capacity race
unit capacity oversell
pool capacity with contributor unavailable
pool concrete binding race
cross-pool contributor rejection
Hold confirm-vs-expire
partial cancellation with shared requirement
Reservation terminal with no live allocation
Session start-vs-cancellation
authority revoke-vs-command
multi-channel durable operation retry
ExternalCorrelation one thread → multiple Requests
partial reversal attribution across two Requirements
refund-vs-reversal deficit
refund without reopening obligation
bank return reopening obligation
PaymentAllocationAdjustment net arithmetic
shared discount partial cancellation
component-based partial fulfillment
terminal Request + later chargeback
idempotency replay after permission revocation
outbox duplicate delivery
```

---

## 34. Schema design gate

Cada invariante crítica debe mapear a una garantía concreta:

```text
DB constraint
OR lock/transaction protocol
OR optimistic versioning
OR explicit application policy backed by authoritative facts
```

"El código normalmente lo comprobará" no es una garantía aceptable.