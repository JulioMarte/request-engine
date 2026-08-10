# Request Engine V2.1 — arquitectura de referencia

> **Estado:** arquitectura objetivo para la reimplementación.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> **Contrato pre-SQL:** `docs/02-pre-sql-domain-contract.md`.
>
> Este documento traduce el dominio canónico a decisiones técnicas. Si existe conflicto, gana `00-product-definition.md`; `02-pre-sql-domain-contract.md` define las garantías mínimas que el schema debe poder implementar.

---

## 1. Objetivo técnico

Request Engine es un motor headless, multi-tenant, API-first y transaccional.

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

El sistema debe mantener autoridad aun cuando:

- clientes reintentan requests;
- agentes LLM repiten tools;
- callbacks llegan duplicados/desordenados;
- capacity cambia concurrentemente;
- payments llegan tarde;
- Resources fallan después de confirmation;
- workflows cruzan procesos/canales/días.

---

## 2. Stack

### PostgreSQL

Source of truth transaccional.

Se utilizará para:

- tenant isolation referential;
- relational integrity;
- temporal/capacity conflict protection;
- row locking;
- exclusion/unique/check constraints;
- optimistic versioning support;
- financial allocation invariants;
- idempotency;
- transactional outbox;
- audit/domain facts.

PostgreSQL no se usa como document store accidental.

### Python + FastAPI

Domain/application/workers/integrations en Python. FastAPI como transporte HTTP.

### SQLAlchemy + Alembic

SQLAlchemy para persistence mapping; Alembic para migrations; Pydantic para contracts/API.

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
│   ├── principals/
│   ├── contacts/
│   ├── offerings/
│   ├── requests/
│   ├── pricing/
│   ├── workflows/
│   ├── reservations/
│   ├── schedules/
│   ├── locations/
│   ├── dispatch/
│   ├── payments/
│   └── fulfillments/
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

No crear microservicios por módulo sin necesidad de scaling/isolation/ownership/deployment real.

---

## 4. Regla de dependencia

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

Mantener aggregates pequeños con invariantes claras.

No convertir cada noun del vocabulario en aggregate root.

Aggregate roots probables iniciales:

```text
Organization
Request
Offering
Resource
CapacityHold
Reservation
ReservationDisruption
Dispatch
PaymentRequirement
PaymentAttempt
PaymentTransaction observation boundary
Refund
PaymentDispute
ReconciliationCase
ServiceSession
```

Algunos conceptos son children/value objects/projections:

```text
Participant
OfferingSelection
ReservationItem
ResourceRequirement snapshot
ResourceAllocation
PaymentAllocation
PaymentInstruction
PriceDetermination components
```

La decisión final depende de invariantes transaccionales, no del nombre.

---

## 6. Tenancy e IDs

Toda tabla tenant-owned tendrá `organization_id` como parte de sus garantías referenciales.

No basta con filtrar en application code.

Objetivo:

```text
(parent.organization_id, parent.id)
       ↑
(child.organization_id, child.parent_id)
```

Las relaciones críticas deben ser capaces de impedir cross-tenant FKs en DB.

Public IDs separados de internal PKs.

Ejemplos:

```text
org_...
cnt_...
off_...
sel_...
req_...
res_...
dsp_...
prc_...  PriceDetermination
prq_...
pat_...
ptx_...
rfd_...
dspu_... PaymentDispute if public
ful_...
evt_...
```

External provider IDs son references, nunca primary identity.

Public ID no es authorization.

---

## 7. Principal, authorization y agents

Authentication resuelve:

```text
credential/session
→ organization
→ principal
→ scopes
```

Authorization además evalúa:

```text
subject/on-behalf-of relationship
resource ownership
current state
policy
```

Un scope como `reservations.cancel` no permite cancelar cualquier Reservation del tenant automáticamente.

High-risk scopes:

```text
reservations.override_policy
reservations.force_recovery
payments.verify
payments.refund
payments.reconcile
payments.override
```

Todos requieren audit + reason.

Agent tools utilizan la misma application layer pero una superficie más estrecha que REST.

---

## 8. Request / workflow execution

Request conserva durable intent y workflow correlation.

Persistencia conceptual del workflow:

```text
workflow_key
workflow_version
workflow_status
current_step
workflow_state (typed/versioned payload only where necessary)
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

No construir state-machine framework universal.

Request terminality debe evaluarse mediante workflow rules y Fulfillment/outcome requirements, no por Reservation status o payment aislado.

---

## 9. Pricing architecture

Pricing es un boundary mínimo, no un commerce engine universal.

`PriceDetermination` conserva la explicación histórica de una cantidad.

Debe poder vincularse al scope que priced y a la policy/source utilizada.

Inputs tipados/versionados; no arbitrary code/DSL.

Conceptualmente:

```text
scope
pricing_source / policy key+version
base amount
quantity semantics
adjustments[]
final Money
provenance
calculated_at
```

`PaymentRequirement` referencia la determinación/revisión relevante.

Un override humano genera nueva determination/revision con Principal + reason; no modifica silenciosamente el cálculo anterior.

Request Engine puede aceptar un authoritative external price, pero conserva source/reference/snapshot.

---

## 10. Money

`Money` siempre es:

```text
amount decimal/integer-minor-units strategy chosen consistently
currency ISO-like code
```

Nunca binary floating point.

No FX implícito.

Comparaciones/allocations sólo entre currencies compatibles salvo un futuro explicit FX model.

---

## 11. OfferingSelection y immutable-after-commit semantics

Selections pueden evolucionar durante intake.

Después de que una Selection haya contribuido a un commitment/payment/fulfillment, campos históricos materiales no se sobrescriben ciegamente.

Cambios materiales se ejecutan mediante commands de negocio que:

1. validan current revision;
2. determinan efectos sobre ReservationItems/capacity/pricing/payments;
3. preservan snapshot previo;
4. producen nuevas revisions/facts cuando corresponde.

No introducir todavía aggregate genérico `Amendment`.

---

## 12. ResourceRequirement y ResourceAllocation

Ésta es una garantía estructural central.

Cada effective ResourceRequirement materializado para un ReservationItem debe poder relacionarse con las ResourceAllocations que lo satisfacen.

```text
ReservationItem
    ↓
effective ResourceRequirement
    ↓
ResourceAllocation
    ↓
Resource / pool
```

Allocation incluye conceptualmente:

```text
reservation
reservation_item/effective_requirement
resource or pool
capacity model
quantity
planned interval
status
provenance/replacement relationship
```

Una Reservation confirmada debe tener requirements satisfechos por active allocations o encontrarse en un disruption state detectable.

---

## 13. Capacity conflict model

Availability es query; authority empieza con Hold/Reservation.

### Exclusive resources

Intervals incompatibles sobre un exclusive Resource no pueden coexistir como live capacity claims.

PostgreSQL range/exclusion constraints son candidato preferido cuando el modelo físico lo permita.

### Unit resources

Para `units`, la suma de live claims no puede superar capacity efectiva.

Como una suma entre filas no es un simple CHECK constraint, el schema/transaction strategy debe escoger una garantía serializable mediante locking sobre una capacity bucket/resource-period authority apropiada o una estrategia equivalente demostrable.

No aceptar un algoritmo check-then-insert sin lock autoritativo.

### Holds

CapacityHold consume el mismo capacity conflict space que confirmed allocations.

Estados mínimos conceptuales:

```text
active
confirmed
released
expired
```

Sólo `active` consume capacity como hold; confirmation transforma/realiza el claim sin ventana de oversell.

Expiry y confirmation compiten bajo lock/version.

---

## 14. Pool late binding

Un pool representa capacity agregada reservable.

La concreción posterior de miembro puede usar una de estas estrategias físicas, a decidir en SQL design:

1. allocation parent pool + child realization que no vuelve a consumir pool total; o
2. atomic replacement del pool claim por concrete claim conservando lineage.

La implementación elegida debe probar:

- no double counting;
- concrete Resource no oversold;
- pool capacity no oversold;
- replacement history preservada.

No introducir `Assignment` como segunda fuente de verdad.

---

## 15. Reservation lifecycle

Commitment states canónicos:

```text
confirmed
cancelled
expired
closed
```

`closed` significa no remaining committed future capacity. No significa universalmente fulfilled/paid/attended.

No persistir globalmente:

```text
completed
no_show
checked_in
in_service
en_route
```

como Reservation commitment states.

Esos hechos pertenecen a Fulfillment/admission/ServiceSession/Dispatch/projections.

### Operational health

```text
valid
at_risk
blocked
```

Projection derivada, no arbitrary mutable authority.

---

## 16. Admission and partial attendance

CheckIn y QueueEntry deben poder asociarse al admission scope apropiado.

Para Reservation multi-recipient/group:

```text
Reservation remains confirmed/closed
participant A → attended
participant B → no_show
participant C → cancelled admission
```

No colapsar a `Reservation.no_show`.

NoShowPolicy produce consecuencias por scope afectado y puede generar payment/refund consequences sin alterar hechos de otros participants.

---

## 17. Fulfillment architecture

Fulfillment es pequeño y scope-specific.

Preferencia:

```text
one Fulfillment → one Request
one Fulfillment → optional OfferingSelection
one Fulfillment → explicit fulfilled quantity/scope
one Fulfillment → optional ServiceSession/evidence reference
```

Una ServiceSession que satisface dos Requests crea dos Fulfillment records.

Una Selection parcialmente satisfecha puede tener múltiples Fulfillments.

Request completion se calcula por workflow/outcome rules sobre el conjunto de Fulfillments, no por un único boolean.

---

## 18. Schedule/time architecture

Persistir instantes autoritativos como UTC.

Schedules conservan timezone IANA.

La API que recibe local date/time debe resolver DST explícitamente.

Para hora ambigua:

```text
require offset/fold or return disambiguation options
```

Para hora inexistente:

```text
reject or return next valid options according to explicit policy
```

Nunca normalizar silenciosamente.

BusinessHours y AvailabilitySchedule son diferentes.

ScheduleException nueva no modifica Reservation existente; detection job/command abre disruptions cuando corresponda.

---

## 19. Dispatch architecture

Reservation 1 → 0..N Dispatches.

Dispatch conserva state útil:

```text
planned
assigned
en_route
arrived
cancelled
failed
ETA
tracking/share reference
latest meaningful position when allowed
```

Cancellation de Reservation no puede dejar Dispatch activo indefinidamente. La cancelación dispara compensating action/event; durante consistencia eventual la projection debe poder mostrar la operación pendiente.

No raw GPS time-series.

---

## 20. Payment model

### PaymentRequirement

Obligación concreta.

Conceptualmente:

```text
Money required
purpose
payer when known
PriceDetermination/provenance
policy snapshot
status projection/cache
due_at
revision
```

Estados como `open/partial/satisfied` deben ser derivables del financial state; si se materializan por performance deben mantenerse transaccionalmente/projection-safe.

`waived/cancelled` sí son decisiones explícitas de negocio.

### PaymentAttempt

Representa interaction attempt con método/provider. Provider success no equivale necesariamente a settlement.

### PaymentEvidence

Nunca crea settlement por sí sola.

### PaymentTransaction

Representa un financial fact observado.

No modelar todo como una fila mutable que cambia de `settled` a `reversed` destruyendo semántica previa.

Se conserva original observation y se registran facts posteriores relacionados.

---

## 21. Financial facts, refunds and disputes

El modelo físico debe distinguir:

```text
original transaction/observation
refund operation
refund financial movement/confirmation
reversal/return financial fact
payment dispute lifecycle
```

### Refund

Operation lifecycle:

```text
requested
processing
succeeded
failed
cancelled
```

Debe referenciar el value/original transaction scope refundable.

### Reversal/return

Financial fact relacionado con original transaction. Reduce eligible net value.

### PaymentDispute

Lifecycle separado:

```text
opened
under_review
won
lost
closed
```

`lost` puede producir/relacionarse con reversing financial fact.

No todas las PSPs exponen los mismos estados; adapters normalizan a facts internos mínimos.

---

## 22. PaymentAllocation invariants

PaymentAllocation asigna eligible financial value a PaymentRequirement.

DB/application transaction debe impedir:

```text
sum(active eligible allocations from transaction) > eligible transaction value
```

Y debe poder determinar:

```text
net allocated value toward requirement
```

después de refunds/reversals/returns.

Overpayment permanece unallocated o explícitamente reasignado; no se fuerza dentro de Requirement.

No usar `paid=true` como source of truth.

---

## 23. Payment verification strength

Manual verification es permitida, pero requiere:

```text
payments.verify scope
Principal
verification source
reason/reference
audit timestamp
```

La UI/tool debe expresar que el humano verificó una fuente independiente, no que aprobó visualmente un screenshot.

Para tenants que lo requieran puede añadirse policy de dual-control/approval, pero no es requisito core inicial.

---

## 24. Reconciliation

ReconciliationCase se abre cuando existen financial facts pero no es seguro cómo tratarlos.

Examples:

```text
missing_reference
ambiguous_match
unknown_attempt
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
```

Concurrent reconciliation debe usar lock/version para impedir resoluciones incompatibles.

---

## 25. Commands

Commands iniciales de application layer:

### Requests

```text
CreateRequest
AddRequestParticipant
SelectOffering
UpdateOfferingSelectionBeforeCommitment
ProvideRequestData
AdvanceRequest
CompleteRequest
```

### Pricing

```text
DeterminePrice
RecordExternalPriceDetermination
OverridePrice
```

### Reservations

```text
SearchAvailability                  [query, not command]
CreateCapacityHold
ReleaseCapacityHold
ConfirmReservation
RescheduleReservation
CancelReservation
CloseReservation
CheckInParticipant
MarkAdmissionNoShow
JoinQueue
LeaveQueue
OpenReservationDisruption
RecoverReservationDisruption
ReplaceResourceAllocation
ReleaseResourceAllocation
```

### Dispatch/service

```text
CreateDispatch
BindDispatchResources
MarkDispatchEnRoute
UpdateDispatchEta
MarkDispatchArrived
CancelDispatch
ChangeDestination
StartServiceSession
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

No command `SetPaid`.

No command `SetReservationStatus` genérico.

No command `UpdateAnything` genérico.

---

## 26. Queries

```text
GetRequest
ListOpenRequests
GetRequestParticipants
ListOfferingSelections
ListOfferings
GetPriceDetermination
GetLocation
GetLocationCurrentHours
SearchAvailability
GetReservation
GetReservationOperationalStatus
GetQueueState
GetReservationDisruption
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

## 27. Transaction template

Authoritative command:

```text
BEGIN
  resolve tenant + principal
  validate authorization/current revision
  lock authoritative rows/buckets
  revalidate policy/capacity/financial invariants
  mutate domain state
  append audit/domain event
  append outbox if needed
COMMIT
```

No network calls dentro de authoritative transaction.

---

## 28. Concurrency strategy

### Optimistic versioning

Mutable aggregate roots relevantes tendrán revision/version.

Lost update:

```text
UPDATE ... WHERE id=? AND revision=?
```

si affected rows = 0 → concurrency conflict/reload.

### Pessimistic locks

Usar cuando la invariante depende de totals/competing claims:

- capacity unit commitment;
- Hold confirm/expire;
- PaymentAllocation totals;
- refundability totals;
- reconciliation resolution.

### Exclusion constraints

Preferidas para exclusive temporal resources si el diseño físico permite range representation limpia.

### Unique constraints

Obligatorias para:

- tenant-scoped public IDs;
- idempotency scope/key;
- provider event identity;
- provider transaction identifiers when semantics guarantee uniqueness;
- other natural dedupe identities.

---

## 29. Explicit race handling

### Last capacity

Both transactions lock/conflict on same capacity authority. Only one can commit valid claim.

### Payment vs Hold expiry

PaymentTransaction may settle regardless. Hold confirmation checks locked current state. If expired first, payment enters revalidation/refund/reconciliation path.

### Cancellation vs CheckIn

Both compare Reservation/admission revisions and policy. One wins; loser reloads and reevaluates.

### Resource unavailable vs confirmation

Resource availability change and confirmation serialize around capacity authority/revision. If confirmation wins first, subsequent unavailability opens disruption. If unavailability wins, confirmation fails/recomputes.

### Refund vs reversal

Both lock financial value authority. No path may return/allocate more eligible value than exists.

### Two workers same outbox

`FOR UPDATE SKIP LOCKED` or equivalent claim; delivery remains at-least-once.

### Two reconciliations

Case/transaction revision lock prevents conflicting resolutions.

---

## 30. Idempotency design requirements

Persist at least conceptually:

```text
organization
operation
caller/principal scope where needed
idempotency key
canonical request hash
status
result reference/response snapshot
created/expires timestamps
```

Same key + different canonical hash → conflict.

Do not depend on in-memory cache for correctness.

---

## 31. External event ingestion

Persist provider event envelope/fingerprint before applying effects where practical.

Normalized flow:

```text
receive
→ authenticate
→ dedupe
→ persist raw/minimal reference safely
→ normalize
→ execute internal command
→ record processed outcome
```

Out-of-order events cannot blindly regress internal facts.

Adapters should favor event facts over copying provider state machines wholesale.

---

## 32. Transactional outbox

Outbox written in same transaction as domain mutation.

Worker supports:

```text
claim
attempt count
retry/backoff
next_attempt_at
failure/dead-letter state
idempotent consumer/delivery key
event version
```

External queue can be added later if measured need exists.

---

## 33. Audit vs domain events vs logs

### Audit

Security/business accountability.

### Domain event

Business fact for internal/external reaction.

### Log

Technical diagnosis.

No usar uno como sustituto de los otros.

Critical audit context:

```text
organization
principal
on_behalf_of subject when relevant
action
entity + revision
policy key/version
reason/override
correlation/causation
source channel/integration
```

---

## 34. Correlation and causality

Propagar cuando aplique:

```text
request_id
offering_selection_id
reservation_id
reservation_item_id
resource_requirement_id
resource_allocation_id
dispatch_id
payment_requirement_id
payment_attempt_id
payment_transaction_id
fulfillment_id
correlation_id
causation_id
principal_id
trace_id
```

Debe poder reconstruirse el camino completo sin depender de logs.

---

## 35. Agent tool design

Tools orientadas a objetivos:

```text
search_offerings
create_or_update_request
find_reservation_options
prepare_reservation
confirm_reservation
get_service_status
get_payment_options
start_payment
get_payment_status
submit_payment_evidence
cancel_reservation
reschedule_reservation
```

No exponer al LLM:

- raw relationship tables;
- locks;
- capacity buckets;
- provider secrets;
- bank internals;
- reconciliation internals;
- arbitrary status setters.

Cada mutating tool requiere idempotency token fuera del razonamiento libre del modelo y revalida current authoritative state.

---

## 36. Cross-channel continuation

Channel/session context es correlation, no authority.

```text
Website → req_123
WhatsApp → authenticate/resolve subject → req_123
Voice → independently authorize → req_123
Human → employee Principal → req_123
```

El sistema puede almacenar channel references/context metadata, pero no necesita un Conversation aggregate core.

---

## 37. Derived/projection states

No permitir writes directos a:

```text
operational_health
overdue
payment satisfied/partial if fully derivable
request progress percentage
reservation operational status
availability
```

Pueden materializarse por performance con rebuild/reconciliation strategy.

---

## 38. Boundary with external systems

### CRM

Request Engine conserva Contact/participant state necesario; CRM conserva relationship history broader.

### Accounting/invoicing

RE conserva PriceDetermination, obligations y operational payment facts; accounting conserva journals/invoices/tax compliance.

### Inventory

RE sólo conserva reservable capacity o external inventory reservation reference cuando sea necesario para fulfillment.

### Workforce/routing

RE necesita valid capacity/assignment and meaningful ETA; optimizer externo puede escoger plan óptimo.

### GPS

RE conserva meaningful latest state/reference, no telemetry stream.

### Communications

RE conserva correlation/provenance, no inbox universal.

---

## 39. Test matrix obligatoria antes del schema implementation freeze

El schema debe tener tests concurrentes/integración para:

```text
cross-tenant FK rejection
exclusive-resource overlap
unit-capacity oversell
concurrent CapacityHolds
Hold confirm-vs-expire
resource unavailable-vs-confirm
pool late-binding without double count
mixed participant attendance
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
agent unauthorized on-behalf-of mutation
```

---

## 40. Schema design gate

Antes de escribir el SQL definitivo, `docs/02-pre-sql-domain-contract.md` debe estar satisfecho.

El SQL design debe demostrar, para cada invariante:

```text
DB constraint
OR lock/transaction protocol
OR optimistic concurrency
OR application policy
```

Si una invariante crítica sólo puede expresarse como “el código normalmente lo comprobará antes”, el schema todavía no está listo.

---

## 41. Lo que NO construiremos todavía

```text
microservices por módulo
BPMN
Temporal clone
rules DSL
generic pricing engine
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
generic relationship graph
```

La siguiente etapa después de estos documentos es **diseñar el schema PostgreSQL a partir de invariantes, no traducir nouns mecánicamente a tablas**.
