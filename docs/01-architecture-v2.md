# Request Engine V2.2 — arquitectura de referencia

> **Estado:** arquitectura objetivo; schema freeze bloqueado hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> Este documento traduce el dominio canónico a decisiones técnicas. Si existe conflicto, gana `00-product-definition.md`. `02-pre-sql-domain-contract.md` define las garantías que el diseño físico debe demostrar.

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

Request Engine debe conservar autoridad aunque:

- clientes/agents reintenten commands;
- callbacks lleguen duplicados o fuera de orden;
- capacity cambie concurrentemente;
- payments lleguen tarde;
- Resources fallen después de confirmation;
- workflows crucen canales, procesos y días;
- una Party actúe mediante otra Party/Principal;
- admission ocurra sin Reservation;
- una ServiceSession ejecute varias Reservations;
- field-service travel haga imposible un schedule aparentemente libre.

---

## 2. Stack

### PostgreSQL

Source of truth transaccional para:

```text
tenant isolation
referential integrity
capacity conflict protection
row/advisory locking where justified
exclusion/unique/check constraints
optimistic versioning
financial allocation invariants
idempotency
transactional outbox
authoritative domain/audit facts
```

PostgreSQL no se usa como document store accidental.

### Python + FastAPI

Domain/application/workers/integrations en Python; FastAPI como HTTP transport.

### SQLAlchemy + Alembic

Persistence mapping + migrations.

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
│   ├── identity/          # Principal, Party, authority
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

Boundary de dominio antes que boundary de red.

No microservices por módulo sin necesidad real de deployment/scaling/isolation/ownership.

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

Domain rules no llaman servicios remotos.

Routes/tools no contienen business authority.

---

## 5. Aggregate philosophy

No convertir nouns en aggregate roots automáticamente.

Aggregate roots probables:

```text
Organization
Party
Request
Offering
Resource
CapacityHold
Reservation
Dispatch        only if lifecycle justifies it
PaymentRequirement
PaymentAttempt
PaymentTransaction observation boundary
Refund
PaymentDispute
ReconciliationCase
ServiceSession
```

Children/value objects/links/projections probables:

```text
RequestParticipant
OfferingSelection
Authority evidence/reference components
ExternalCorrelation
ReservationItem
EffectiveResourceRequirement
ResourceAllocation
recipient/admission scope links
PaymentAllocation
PaymentInstruction
PriceDetermination components
```

No asumir aggregate root para:

```text
ReservationDisruption
ResourceGroup
HolidayCalendar
Assignment
Quote
```

hasta que tengan invariantes/lifecycle propios que lo exijan.

---

## 6. Tenancy e IDs

Toda relación tenant-owned crítica debe poder demostrar:

```text
child.organization_id == parent.organization_id
```

Preferencia estructural:

```text
(parent.organization_id, parent.id)
       ↑
(child.organization_id, child.parent_id)
```

No depender sólo de ORM filters.

Public IDs separados de internal PKs.

Ejemplos conceptuales:

```text
org_...
pty_...
prn_...
req_...
off_...
sel_...
hld_...
res_...
ses_...
dsp_...
prc_...
prq_...
pat_...
ptx_...
rfd_...
ful_...
```

External provider IDs son references, nunca primary identity.

Public ID no es authorization.

---

## 7. Principal, Party, authority y agents

Authentication resuelve:

```text
credential/session
→ organization
→ Principal
→ scopes/capabilities
```

Business identity resuelve separadamente:

```text
external/channel identity
→ verified Party when possible
```

Authorization evalúa:

```text
Principal
Organization
required capability
Party/subject correlation
on-behalf-of authority
entity ownership/relationship
current state
policy/version
```

`RequestParticipant(role=guardian)` no concede por sí solo cancel/refund/consent authority.

Un `AuthorityGrant/Representation` puede materializarse como entity o como verified relationship + provenance; el schema design debe escoger la forma más pequeña que preserve:

```text
actor
represented subject
allowed scope/action
source/policy
validity/revocation when relevant
audit provenance
```

No construir generic ACL/relationship graph.

High-risk scopes:

```text
reservations.override_policy
reservations.force_recovery
payments.verify
payments.refund
payments.reconcile
payments.override
```

requieren audit + reason y, cuando policy lo exija, stronger approval.

---

## 8. Cross-channel continuation

Persistir `ExternalCorrelation` mínima:

```text
organization
request
channel/integration kind
external correlation identifier
optional verified Party reference
verification/provenance metadata
created/last-seen timestamps as needed
```

No almacenar conversación completa por defecto.

Un channel/thread/call identifier:

```text
is correlation
≠ authentication
≠ authorization
```

Website → WhatsApp → Voice → Human puede continuar `req_123`, pero cada mutation revalida authority.

---

## 9. Request/workflow execution

Request conserva durable intent y workflow correlation.

Persistencia conceptual:

```text
workflow_key
workflow_version
workflow_status
current_step
workflow_state typed/versioned only when necessary
next_action_at
revision
```

Resultados internos posibles:

```text
need_input
execute_capability
wait_confirmation
wait_capacity
wait_payment
wait_payment_verification
wait_external
wait_human
recover_capacity
complete
fail_recoverable
fail_terminal
```

Request terminality depende de workflow/outcome rules, no de Reservation/payment aislado.

No state-machine framework universal.

---

## 10. Pricing architecture

`PriceDetermination` conserva explicación histórica de una cantidad:

```text
priced scope
pricing source/policy key+version
base Money
quantity semantics
adjustments
final Money
provenance
calculated_at
override Principal/reason when applicable
```

PaymentRequirement referencia determination/provenance relevante.

No FX implícito.

`Money` nunca usa binary floating point.

`Quote` sólo aparece si necesitamos lifecycle de oferta/acceptance/expiry independiente. `request_quote` no obliga a crear tabla Quote.

---

## 11. OfferingSelection y amendment semantics

Selections pueden evolucionar durante intake.

Después de contribuir a commitment/payment/fulfillment, campos materiales no se sobrescriben ciegamente.

Commands:

1. validan current revision;
2. identifican affected recipient/selection scope;
3. calculan efectos en capacity/pricing/payments/admission;
4. preservan snapshot/lineage;
5. producen replacement facts cuando corresponda.

No generic Amendment aggregate.

---

## 12. Resource requirements

Separar configuración de Offering de commitment histórico:

```text
Offering
→ ResourceRequirementTemplate

ReservationItem
→ EffectiveResourceRequirement
→ ResourceAllocation
→ Resource/pool
```

`EffectiveResourceRequirement` debe materializar quantity, interval y relevant subject scope.

Una confirmed Reservation con requirement insuficientemente allocated debe ser detectablemente `at_risk/blocked`; no puede aparentar `valid`.

No OR/k-of-n requirement algebra en V2.2.

---

## 13. Capacity conflict model

Availability es query; authority empieza con CapacityHold/confirmed Allocation.

### Exclusive

Intervals incompatibles no pueden coexistir como live claims.

PostgreSQL range/exclusion constraints son candidato preferido cuando la representación física lo permita.

### Units

Debe demostrarse serializabilidad de:

```text
sum(live holds + active confirmed claims) <= effective capacity
```

No aceptar check-then-insert sin lock authority.

### Holds

```text
active → confirmed | released | expired
```

Sólo active consume capacity como hold.

Confirmation transforma/realiza el claim sin ventana de oversell.

Expiry y confirmation compiten bajo lock/version.

### Transition/setup/travel time

Si travel/setup/cleanup hace físicamente incompatibles dos commitments, debe participar en el capacity conflict model.

Opciones físicas aceptables incluyen:

- ampliar/reservar blocking intervals;
- materializar transition claims;
- serializar contra una authority que evalúe travel constraint de forma determinista.

Lo no aceptable es confirmar dos commitments físicamente imposibles porque sus service intervals no se solapan.

Request Engine no optimiza rutas; sólo protege feasibility cuando el constraint es material.

---

## 14. Pool late binding

Pool representa capacity agregada.

Estrategias físicas candidatas:

1. pool allocation parent + concrete realization child sin doble consumo; o
2. atomic replacement pool claim → concrete claim preservando lineage.

Debe probar:

```text
pool not oversold
member not double-booked
binding not double-counted
lineage preserved
```

No `Assignment` como segunda truth source.

---

## 15. Reservation lifecycle

Reservation es **capacity commitment**, no admission.

Estados:

```text
confirmed
cancelled
expired
closed
```

No persistir globalmente:

```text
completed
no_show
checked_in
waiting
in_service
en_route
```

### Partial cancellation

Cancelación parcial debe actuar sobre ReservationItem/allocation/recipient scope y liberar exactamente capacity afectada.

`Reservation.cancelled` sólo aplica cuando todo el commitment termina por cancel operation.

### Operational health

```text
valid
at_risk
blocked
```

es projection derivada.

---

## 16. Admission architecture

Admission es un módulo ortogonal a capacity commitment.

### CheckIn

Observed presence/readiness sobre admission scope específico.

### QueueEntry

Puede existir:

```text
with Reservation
without Reservation (walk-in)
```

Nunca crear Reservation ficticia sólo para representar queue position.

### WaitlistEntry

Interés sin capacity comprometida.

```text
Waitlist → match → Hold → acceptance → Reservation
```

### Mixed attendance

El schema debe poder mapear Party/Participant/recipient scope a Selection/ReservationItem/admission unit.

No global `Reservation.no_show`.

No crear `ReservationParticipant` aggregate si una join/link structure preserva las invariantes.

---

## 17. ServiceSession y Fulfillment

### ServiceSession

Actual execution episode.

Cardinalidad semántica:

```text
Reservation N:M ServiceSession
```

Necesitamos un link explícito porque:

- una Reservation puede ejecutarse en varias sessions;
- una session puede ejecutar varias Reservations;
- walk-in/external work puede producir ServiceSession sin Reservation.

El link no implica que toda session satisfaga toda Reservation: Fulfillment conserva scope específico.

### Fulfillment

Preferencia:

```text
one Fulfillment → one Request
optional OfferingSelection
explicit recipient/quantity/scope
optional ServiceSession/evidence
```

Una session que satisface dos Requests crea dos Fulfillments.

Remaining fulfillment debe ser determinístico.

---

## 18. Schedule/time architecture

Persist authoritative instants UTC.

Schedules usan IANA timezone.

Ambiguous local time:

```text
require offset/fold or return explicit choices
```

Nonexistent local time:

```text
reject or apply explicit communicated policy
```

BusinessHours ≠ AvailabilitySchedule.

ScheduleException no reescribe Reservation existente; detecta affected commitments y activa recovery.

`HolidayCalendar` no necesita aggregate inicial.

---

## 19. Dispatch architecture

Dispatch representa operational movement toward Destination, no route plan universal.

State útil:

```text
planned
assigned
en_route
arrived
cancelled
failed
ETA
tracking/share reference
latest meaningful position
```

No congelar `Reservation 1:N Dispatch`.

El diseño físico debe permitir que un Dispatch/trip se relacione con uno o varios Reservation/Service scopes si un mismo movement sirve varios commitments.

Cancellation de todos los scopes relacionados no puede dejar Dispatch activo indefinidamente; compensating action/event es obligatorio.

No raw GPS time-series.

---

## 20. External inventory boundary

Offering product no implica inventory subsystem.

Si fulfillment requiere stock externo, application layer debe poder exigir un external commitment/reference antes de confirmar el paso que dependa de él.

No convertir cada SKU en Resource salvo que represente genuinamente capacity reusable/reservable.

Inventory adapters pueden producir:

```text
availability observation
reservation/commitment reference
release/consume result
```

pero Request Engine conserva sólo lo necesario para explicar por qué el workflow consideró satisfecha la precondición.

---

## 21. Payment model

### PaymentRequirement

Conceptualmente:

```text
Money required
purpose
payer Party when known
PriceDetermination/provenance
policy snapshot/reference
due_at
revision
explicit disposition active/waived/cancelled
```

`open/partial/satisfied/overdue` son derivados/materialized projections.

### PaymentAttempt

Provider/method interaction attempt. Success no equivale necesariamente a settlement.

### PaymentEvidence

Nunca crea settlement.

### PaymentTransaction

Financial fact observado.

Original settlement permanece histórico aunque exista refund/reversal/dispute posterior.

---

## 22. Financial facts, refunds y disputes

Distinguir:

```text
original transaction/observation
refund operation
refund financial confirmation/movement
reversal/return financial fact
payment dispute lifecycle
```

Refund:

```text
requested → processing → succeeded | failed
requested → cancelled
```

Dispute:

```text
opened → under_review → won/lost → closed
```

Lost dispute puede relacionarse con reversing financial fact.

---

## 23. PaymentAllocation invariants

Debe impedirse:

```text
sum(eligible allocations from transaction) > eligible transaction value
```

Y calcularse deterministicamente:

```text
net satisfied value toward requirement
```

después de refunds/reversals/returns.

Overpayment queda unallocated o explícitamente reasignado.

No `paid=true` authority.

---

## 24. Manual verification

Manual verification requiere:

```text
payments.verify scope
Principal
independent verification source
reason/reference
audit timestamp
```

Un screenshot aceptado es PaymentEvidence, no independent verification.

El sistema puede hacer una falsa verificación humana auditable; no puede convertir una mentira humana en certeza epistemológica.

Dual-control queda como policy opcional.

---

## 25. Reconciliation

ReconciliationCase para:

```text
missing_reference
ambiguous_match
unknown_attempt
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
```

Concurrent resolution usa lock/version y financial allocation invariants.

---

## 26. Policy provenance

Toda decisión material basada en policy debe poder reconstruir:

```text
policy key/version
resolved scope
inputs relevant to decision
winning precedence/source
override Principal/reason
```

No generic rules DSL.

La application layer resuelve precedence; el audit/domain fact conserva el resultado suficiente para reproducir por qué se tomó la decisión histórica.

---

## 27. Commands

### Requests / identity

```text
CreateRequest
AddRequestParticipant
VerifyPartyCorrelation
GrantOrRecordRepresentation
RevokeRepresentation
AddExternalCorrelation
SelectOffering
UpdateOfferingSelectionBeforeCommitment
ProvideRequestData
AdvanceRequest
CompleteRequest
```

No todos deben exponerse públicamente; algunos son internal/application capabilities.

### Pricing

```text
DeterminePrice
RecordExternalPriceDetermination
OverridePrice
```

### Capacity / reservations

```text
SearchAvailability                  [query]
CreateCapacityHold
ReleaseCapacityHold
ConfirmReservation
RescheduleReservation
CancelReservation
CancelReservationScope
CloseReservation
ReplaceResourceAllocation
ReleaseResourceAllocation
```

### Admission

```text
CheckIn
MarkAdmissionNoShow
JoinQueue
LeaveQueue
PromoteWaitlistEntry
```

### Dispatch/service

```text
CreateDispatch
LinkDispatchScope
BindDispatchResources
MarkDispatchEnRoute
UpdateDispatchEta
MarkDispatchArrived
CancelDispatch
ChangeDestination
StartServiceSession
LinkServiceSessionReservation
CompleteServiceSession
RecordFulfillment
```

### Payments

```text
CreatePaymentRequirement
CancelPaymentRequirement
WaivePaymentRequirement
CreatePaymentAttempt
SubmitPaymentEvidence
RecordProviderFinancialEvent
RecordBankTransaction
VerifyBankTransferManually
RecordCashReceived
AllocatePaymentTransaction
OpenPaymentReconciliationCase
ResolvePaymentReconciliationCase
RequestRefund
RecordRefundProviderEvent
RecordFinancialReversal
OpenPaymentDispute
UpdatePaymentDispute
```

Forbidden generic authority commands:

```text
SetPaid
SetReservationStatus
UpdateAnything
```

---

## 28. Queries

```text
GetRequest
ListOpenRequests
GetRequestParticipants
GetRequestAuthorityContext
ListOfferingSelections
ListOfferings
GetPriceDetermination
GetLocation
GetLocationCurrentHours
SearchAvailability
GetReservation
GetReservationOperationalStatus
GetAdmissionState
GetQueueState
GetDispatch
GetServiceStatus
GetPaymentRequirement
GetPaymentStatus
GetPaymentAttempt
ListUnallocatedTransactions
GetReconciliationCase
GetFulfillmentStatus
```

Queries no producen side effects.

---

## 29. Authoritative transaction template

```text
BEGIN
  resolve organization + Principal
  resolve Party/subject authority if required
  validate current revision/state
  lock authoritative rows/buckets
  revalidate policy/capacity/financial invariants
  mutate domain state
  append audit/domain facts
  append outbox if needed
COMMIT
```

No network calls dentro de transaction.

Cuando una external precondition requiere network I/O:

```text
call external system outside authoritative transaction
→ obtain signed/versioned/reference result
→ begin short transaction
→ revalidate current state + external result freshness
→ commit internal decision/reference
```

---

## 30. Concurrency strategy

### Optimistic versioning

Usar para stale mutable aggregate commands:

```text
UPDATE ... WHERE id=? AND revision=?
```

0 rows → conflict/reload.

### Pessimistic locking

Cuando invariant depende de competing totals/claims:

```text
unit capacity
Hold confirm/expire
PaymentAllocation budget
refundability budget
reconciliation resolution
```

### Exclusion constraints

Preferidas para exclusive temporal Resource conflicts cuando la representación física lo permita.

### Unique constraints

Obligatorias para:

```text
tenant-scoped public IDs
idempotency scope/key
provider event identity
provider transaction identity when semantics guarantee uniqueness
external correlation identity within its namespace when appropriate
```

---

## 31. Explicit race handling

### Last capacity

Both contenders serialize/conflict on same capacity authority; at most one valid claim commits.

### Hold confirmation vs expiry

Exactly one terminal transition wins.

### Payment vs Hold expiry

Payment may settle. Expired capacity never resurrects. Workflow revalidates/refunds/reconciles.

### Cancellation vs CheckIn

Reservation commitment and admission facts are separate. Commands serialize on relevant scope/revision and policy decides whether cancellation remains allowed after CheckIn.

### Resource unavailable vs confirmation

Serialize around capacity authority. If confirmation wins first, later unavailability creates detectable risk/recovery. If unavailability wins, confirmation fails/recomputes.

### Partial cancellation vs ServiceSession start

Both operate on explicit ReservationItem/recipient scope. One cannot silently release capacity already converted into active execution without policy decision.

### Refund vs reversal

Refund reservation/budget and external reversal may race. Internal refund command cannot exceed refundable budget, but external reversal is still recorded even if it produces negative/net-deficit financial position.

### Two workers same outbox

Claim with `FOR UPDATE SKIP LOCKED` or equivalent. Delivery remains at-least-once.

### Two reconciliations

Case/transaction revision + allocation budget prevents incompatible resolution.

---

## 32. Idempotency requirements

Persist conceptually:

```text
organization
operation
caller/principal/context scope
idempotency key
canonical request hash
status
logical result reference/response snapshot
created/expires timestamps
```

Same scope/key + same hash → replay same logical result.

Same scope/key + different hash → conflict.

Agent adapters should generate/provide operation tokens outside free-form LLM reasoning whenever possible.

---

## 33. External event ingestion

```text
receive
→ authenticate
→ anti-replay/dedupe
→ persist provider event identity/reference
→ normalize
→ execute internal command
→ record processed outcome
```

Out-of-order events never blindly regress authoritative state.

Favor financial/domain facts over copying provider state machines wholesale.

---

## 34. Transactional outbox

Outbox write occurs in same transaction as domain mutation.

Worker supports:

```text
claim
attempt count
retry/backoff
next_attempt_at
failure/dead-letter state
idempotent delivery/consumer key
event version
```

External queue sólo después de measured need.

---

## 35. Audit vs events vs logs

### Audit

Security/business accountability.

### DomainEvent

Business fact/reaction trigger.

### Log

Technical diagnosis.

Critical audit context:

```text
organization
Principal
Party/on_behalf_of subject when relevant
action
entity + revision
policy key/version
reason/override
authority provenance
ExternalCorrelation/source channel
correlation/causation
```

---

## 36. Correlation and causality

Propagar cuando aplique:

```text
request_id
party_id
principal_id
offering_selection_id
reservation_id
reservation_item_id
effective_requirement_id
resource_allocation_id
service_session_id
dispatch_id
payment_requirement_id
payment_attempt_id
payment_transaction_id
fulfillment_id
external_correlation_id
correlation_id
causation_id
trace_id
```

Debe reconstruirse el camino de negocio sin depender de logs.

---

## 37. Agent tool design

Goal-oriented tools:

```text
search_offerings
create_or_resume_request
provide_request_information
find_reservation_options
prepare_reservation
confirm_reservation
check_in
join_queue
get_service_status
get_payment_options
start_payment
get_payment_status
submit_payment_evidence
cancel_reservation
reschedule_reservation
change_destination
```

No exponer al LLM:

```text
raw relationship tables
raw authority grants
locks/capacity buckets
provider secrets
bank internals
reconciliation internals
arbitrary status setters
```

Mutating tool:

```text
current-state revalidation
+ authorization
+ policy
+ idempotency
```

siempre.

---

## 38. Derived/projection state

No direct writes a:

```text
operational_health
overdue
payment satisfied/partial
request progress
availability
queue estimate
attendance summary
remaining fulfillment
```

Materialization por performance requiere rebuild/reconciliation strategy.

---

## 39. External-system boundaries

### CRM

RE conserva Party/Participant/correlation state mínimo requerido por Requests; CRM conserva relationship history broader.

### Identity

IdP autentica credentials. RE conserva Principal reference, verified Party correlation y authority provenance requerida por business commands.

### Accounting/invoicing

RE conserva PriceDetermination, obligations y operational financial facts; accounting conserva journals/invoices/tax compliance.

### Inventory

RE conserva external commitment/reference necesario para explicar fulfillment feasibility; no general stock ledger.

### Workforce/routing

RE protege feasibility de commitments y meaningful assignment/ETA state. Optimizer externo elige plan óptimo.

### GPS

RE conserva meaningful latest state/reference, no telemetry stream.

### Communications

RE conserva ExternalCorrelation/provenance, no inbox universal.

---

## 40. Required test matrix before schema freeze

```text
cross-tenant FK rejection
Principal ≠ Party authorization
organization payer for employee
unauthorized guardian/on-behalf-of mutation
cross-channel correlation without bearer authority
walk-in QueueEntry without Reservation
appointment + QueueEntry coexistence
mixed recipient attendance
partial Reservation cancellation
exclusive-resource overlap
unit-capacity oversell
concurrent CapacityHolds
Hold confirm-vs-expire
resource unavailable-vs-confirm
pool late-binding without double count
travel/transition induced conflict
one ServiceSession linked to multiple Reservations
multiple ServiceSessions for one Reservation
partial fulfillment
price provenance preservation
PaymentAllocation overspend
Requirement net satisfaction after reversal
partial refund
refund-vs-reversal race
duplicate provider webhook
out-of-order provider webhook
late payment after Hold expiry
concurrent reconciliation
idempotency payload mismatch
schedule exception after existing Reservations
DST ambiguous/nonexistent local time
outbox duplicate delivery
agent retry duplication
hallucinated/cross-tenant ID
external inventory precondition invalidated before commit
```

---

## 41. Schema design gate

Antes del SQL definitivo, `docs/02-pre-sql-domain-contract.md` debe mapear cada invariante a una garantía primaria:

```text
DB constraint
OR lock/transaction protocol
OR optimistic concurrency
OR deterministic application policy
```

Para invariantes de:

```text
money
capacity
tenancy
idempotency
```

“el código normalmente lo comprueba” no es una garantía aceptable.

---

## 42. Lo que NO construiremos todavía

```text
microservices por módulo
BPMN
Temporal clone
rules DSL
generic pricing engine
generic relationship graph
generic Amendment aggregate
Assignment truth source
ResourceGroup aggregate
HolidayCalendar aggregate
ReservationDisruption aggregate unless lifecycle proves need
Quote aggregate unless acceptance/expiry proves need
accounting ledger
invoice/tax platform
inventory system
workforce optimizer
route optimizer
GPS telemetry store
ReservationSeries
Agreement
Subscription
Delivery platform
advanced requirement algebra
FX
```

La siguiente etapa no es traducir nouns a tablas. Es demostrar el contrato pre-SQL y sólo entonces diseñar PostgreSQL alrededor de las invariantes.