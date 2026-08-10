# Request Engine V2 — arquitectura de referencia

> **Estado:** arquitectura objetivo para la reimplementación de Request Engine.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> Este documento traduce la definición de producto y el stress test de dominio a decisiones técnicas. Si una decisión técnica entra en conflicto con la definición del producto, **gana la definición del producto**.

---

## 1. Punto de partida

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Request Engine es un **motor headless, multiempresa, API-first y transaccional de orquestación de solicitudes**.

Su trabajo es:

1. recibir/normalizar intención;
2. resolver Contacts/participant roles y convertirla en `Request`;
3. resolver una o varias `OfferingSelection` y Location/Destination cuando corresponda;
4. determinar workflow y policies versionadas;
5. ejecutar capabilities deterministas;
6. calcular y comprometer capacity válida;
7. mantener Reservations y recuperar disruptions sin borrar historia;
8. coordinar admission, dispatch, payments, callbacks o intervención humana;
9. producir uno o varios `Fulfillment` verificables;
10. mantener trazabilidad completa.

No es CRM, ERP, PBX, calendario tradicional, GPS telemetry store, shipping platform, PSP, banco, accounting ledger, rules engine universal ni framework universal de agentes.

---

## 2. Stack adoptado

### PostgreSQL

Source of truth transaccional.

El dominio incluye relaciones e invariantes fuertes alrededor de:

- organizations/tenancy;
- principals y contacts/participants;
- locations;
- schedules/exceptions/holidays;
- offerings y offering selections;
- request types/requests/workflows;
- resources/capabilities/requirements;
- capacity holds/reservations/reservation items/allocations;
- admission/check-ins/queues/waitlist boundary/service sessions;
- reservation policies/disruptions/recovery;
- destinations/service areas/dispatches;
- payment policies/requirements/attempts/transactions/allocations/reconciliation/refunds;
- fulfillments;
- idempotency/audit/events/outbox.

PostgreSQL aporta constraints, locking, range types, partial indexes, temporal queries y JSONB cuando realmente corresponde.

### Python + FastAPI

Python para domain/application/workers/integrations y FastAPI como transporte HTTP. La IA no recibe autoridad especial por compartir lenguaje con el backend.

### SQLAlchemy + Alembic

SQLAlchemy para persistencia y Alembic para migraciones. Pydantic para contratos/API; SQLAlchemy para persistencia. No mezclar responsabilidades.

---

## 3. Modular monolith

```text
request-engine
│
├── API
│
├── Core
│   ├── organizations
│   ├── principals
│   ├── contacts
│   ├── locations
│   ├── offerings
│   ├── requests
│   ├── workflows
│   ├── fulfillments
│   ├── events
│   ├── idempotency
│   └── audit
│
├── Modules
│   ├── reservations
│   ├── schedules
│   ├── forms
│   ├── dispatch
│   └── payments
│
├── Infrastructure
│   ├── postgres
│   ├── webhooks
│   ├── integrations
│   ├── media references
│   └── observability
│
└── Workers
```

`RequestParticipant`, `OfferingSelection` y sus associations pertenecen al dominio de requests/offerings; no justifican microservicios.

`ReservationPolicy`, `ReservationDisruption`, `ReservationItem`, admission y capacity pertenecen al módulo reservations.

Boundary de dominio antes que boundary de red. Separar servicio sólo por scaling, isolation, ownership, security o deployment requirements reales.

---

## 4. Estructura propuesta

```text
src/request_engine/
├── api/
│   ├── routes/
│   ├── dependencies/
│   ├── middleware/
│   └── errors.py
├── domain/
│   ├── organizations/
│   ├── principals/
│   ├── contacts/
│   ├── locations/
│   ├── offerings/
│   ├── requests/
│   ├── workflows/
│   ├── fulfillments/
│   ├── reservations/
│   ├── schedules/
│   ├── forms/
│   ├── dispatch/
│   └── payments/
├── application/
│   ├── commands/
│   ├── queries/
│   └── services/
├── infrastructure/
│   ├── postgres/
│   ├── webhooks/
│   ├── integrations/
│   │   ├── payments/
│   │   ├── banking/
│   │   ├── maps/
│   │   └── tracking/
│   ├── media/
│   └── observability/
└── workers/
```

No crear capas vacías por ceremonia.

---

## 5. Regla de dependencia

```text
API / Worker / Integrations / Agent adapters
                  ↓
           Application layer
                  ↓
              Domain rules
                  ↓
        Infrastructure adapters
```

Routes y agent tools traducen hacia commands/queries; no contienen lógica de negocio autoritativa.

Domain policies no llaman providers remotos.

---

## 6. Contratos

```text
Pydantic schemas
      ↓
FastAPI
      ↓
OpenAPI
      ↓
generated SDKs
```

La superficie de agentes no debe ser 1:1 con REST:

```text
Application commands/queries
        ├── REST endpoints
        ├── public/widget endpoints
        └── MCP / agent tools
```

REST favorece composición. Agent tools favorecen objetivos de negocio, inputs pequeños y scopes mínimos.

Schemas de participants, OfferingSelections, ReservationOptions y payment instructions deben ser tipados/discriminados, no blobs arbitrarios.

---

## 7. Persistencia relacional primero

No convertir PostgreSQL en document store accidental.

Campos de identidad, participant roles, relationships, lifecycle, constraints, scheduling, pagos y reporting operacional deben ser columns/tables tipadas.

JSONB queda para metadata dinámica, policy snapshots tipados/versionados, Offering snapshots o payloads cuyo schema varía legítimamente.

Public IDs separados de PKs internas:

```text
org_...
cnt_...
loc_...
off_...
sel_...   OfferingSelection
req_...
res_...
dsp_...
prd_...   ReservationDisruption cuando se exponga públicamente
prq_...   PaymentRequirement
pat_...   PaymentAttempt
ptx_...   PaymentTransaction
rfd_...   Refund
ful_...
evt_...
```

No todo join table necesita public ID.

External provider IDs permanecen mappings/references.

---

## 8. `Principal`, `Contact` y participant roles

No usar un único `contact_id` para asumir requester = recipient = payer.

Separar:

```text
Principal
= authenticated/system actor that performed mutation

Contact
= business identity

RequestParticipant / ReservationParticipant
= role of Contact in specific work
```

Modelo relacional conceptual:

```text
request_participants
  organization_id
  request_id
  contact_id
  role
  metadata/snapshot where justified

reservation_participants
  organization_id
  reservation_id
  contact_id
  role
  metadata/snapshot where justified
```

Roles iniciales:

```text
requester
recipient
payer
guardian
authorized_contact
```

Una estrategia simple es una row por `(request_id, contact_id, role)` para permitir múltiples roles sin array mutable.

`initiated_by_principal_id`/audit permanece separado: un AI agent puede ser Principal mientras María es requester y José recipient.

Todas las relaciones deben estar tenant-scoped y no permitir Contact de otra organization.

---

## 9. `OfferingSelection` y cardinalidad del Request

Un Request puede tener 0..N OfferingSelections.

Modelo conceptual:

```text
offering_selections
  id / public_id
  organization_id
  request_id
  offering_id
  quantity
  status
  configuration / validated_input
  offering_snapshot/reference
  created_at
```

Recipients pueden resolverse mediante association tipada a RequestParticipants cuando haga falta:

```text
offering_selection_participants
  offering_selection_id
  request_participant_id
  role = recipient/beneficiary where supported
```

No asumir que `requests.offering_id` singular es suficiente.

Un RequestType como `request_callback` puede tener cero selections.

Quantity debe ser positiva y validada según la unidad/semántica del Offering; no asumir que todos los Offerings usan el mismo tipo lógico de unidad.

---

## 10. `ReservationItem`: qué selections están bajo commitment

No conectar Reservation a un único Offering o Request mediante una relación obligatoria 1:1.

Modelo conceptual:

```text
reservation_items
  id
  organization_id
  reservation_id
  offering_id
  offering_selection_id nullable
  quantity
  offering_snapshot
  policy_snapshot/reference
  metadata
```

`offering_selection_id` puede ser nullable para Reservation administrativa directa, pero `offering_id`/snapshot suficiente sigue siendo obligatorio para explicar qué fue reservado.

Una Reservation puede cubrir varios ReservationItems.

Un Request puede producir varias Reservations.

Una Reservation puede cubrir varias selections; no crear combinatorial Offerings sólo para poder reservarlas juntas.

Si una Reservation reúne selections originadas por más de un Request, la relación se deriva de ReservationItems; un `request_id` singular en Reservation no puede ser source of truth de ownership. Puede existir un `created_from_request_id` nullable exclusivamente para provenance/correlation, no como cardinalidad del dominio.

---

## 11. Offering y RequestType

`Offering` es fachada estable; especialización por composición.

`RequestType` permanece relativamente genérico:

```text
reserve_offering
purchase_offering
request_quote
request_information
request_callback
reschedule_reservation
cancel_reservation
submit_intake
```

Resolución:

```text
RequestType
 + OfferingSelections
 + Participants
 + Organization policy
 + Request context
 ↓
workflow_key + workflow_version
```

---

## 12. Commands y Queries

### Commands

```text
CreateRequest
AddRequestParticipant
SelectOffering
UpdateOfferingSelection
ProvideRequestData
AdvanceRequest

CreateCapacityHold
ConfirmReservation
AddReservationParticipant
RescheduleReservation
CancelReservation
MarkReservationNoShow
CheckInReservation
JoinReservationQueue
AssignReservationResources
ReleaseResourceAllocation
ReplaceResourceAllocation
OpenReservationDisruption
RecoverReservationDisruption
ResolveReservationDisruption

CreateWaitlistEntry          [when waitlist implementation enters scope]
OfferWaitlistCapacity        [when waitlist implementation enters scope]

CreateDispatch
AssignDispatch
MarkDispatchEnRoute
UpdateDispatchEta
MarkDispatchArrived
StartServiceSession
CompleteServiceSession
ChangeDestination

CreatePaymentRequirement
CreatePaymentAttempt
SubmitPaymentEvidence
RecordProviderPaymentEvent
RecordBankTransaction
VerifyBankTransferManually
RecordCashReceived
AllocatePaymentTransaction
OpenPaymentReconciliationCase
ResolvePaymentReconciliationCase
RequestRefund
RecordRefundProviderEvent

CompleteRequest
RecordFulfillment
```

Privileged operations require explicit scopes/audit:

```text
reservations.override_policy
reservations.force_recovery
payments.verify
payments.refund
payments.reconcile
```

### Queries

```text
GetRequest
ListOpenRequests
GetRequestParticipants
ListOfferingSelections
ListOfferings
GetLocation
GetLocationCurrentHours
SearchAvailability
GetReservation
ListReservations
GetReservationOperationalStatus
GetQueueState
GetWaitlistStatus            [when implemented]
GetReservationDisruption
GetDispatch
GetServiceStatus

GetPaymentRequirement
ListPaymentRequirements
GetPaymentOptions
GetPaymentAttempt
GetPaymentStatus
ListUnallocatedTransactions
GetReconciliationCase
```

Queries no producen side effects. `SearchAvailability` no crea holds/reservations. `GetPaymentStatus` no verifica/cambia dinero. `GetReservationOperationalStatus` es una projection/read model; no inventa domain transitions.

---

## 13. Transacciones

```text
BEGIN
  validate tenant + current state
  resolve authoritative/versioned policy
  lock/revalidate capacity or financial allocation where needed
  mutate internal state
  insert domain event/outbox
COMMIT
```

Nunca mantener transacción abierta mientras se llama payment provider, bank API, maps/routing provider, WhatsApp, LiveKit, n8n u otro sistema remoto.

Callbacks externos se validan primero y luego ejecutan commands transaccionales cortos.

Recovery de disruption puede abarcar varios commands/events; no mantener una DB transaction abierta mientras se busca una solución externa.

---

## 14. Outbox

PostgreSQL transactional outbox inicialmente.

Worker con claiming seguro (`FOR UPDATE SKIP LOCKED` u otra estrategia justificada), retry/backoff, dead-letter/failure state, idempotent delivery y event versioning.

Queue externa sólo por necesidad medida.

Usos importantes:

- notifications;
- provider callbacks/reconciliation;
- disruption recovery jobs;
- detection/re-evaluation de Reservations afectadas por cambios masivos de Resource/Schedule;
- integrations externas.

---

## 15. Domain events, audit y logs

Eventos representativos:

```text
request.created
request.participant_added
request.offering_selected
request.ready

capacity_hold.created
capacity_hold.expired
reservation.confirmed
reservation.rescheduled
reservation.cancelled
reservation.no_show
reservation.checked_in
reservation.enqueued
reservation.capacity_disrupted
reservation.capacity_recovered
resource.assigned
resource_allocation.released
resource_allocation.replaced
waitlist.matched

dispatch.created
dispatch.assigned
dispatch.en_route
dispatch.eta_updated
dispatch.arrived
service_session.started
service_session.completed

payment_requirement.created
payment_attempt.created
payment.instructions_ready
payment.evidence_submitted
payment.processing
payment.authorized
payment.transaction_received
payment.partial_received
payment.received
payment.verification_failed
payment.failed
payment.expired
payment.unallocated_funds_detected
payment_requirement.partially_satisfied
payment_requirement.satisfied
payment.reconciliation_required
payment.refund_requested
payment.refund_processing
payment.refunded
payment.refund_failed

request.fulfilled
```

Audit responde quién hizo qué y por qué. Logs son diagnóstico técnico. No confundirlos.

Policy decisions críticos deben registrar:

```text
policy key/version
relevant inputs
initiator/source
reason code
decision/consequence
principal/override when applicable
```

En payments, audit distingue `provider_webhook`, `provider_api`, `bank_feed`, `bank_api`, `manual_bank_verification`, `cash_verification` y `external_system`.

---

## 16. Correlation y causality

Propagar cuando corresponda:

```text
request_id
offering_selection_id
reservation_id
reservation_disruption_id
dispatch_id
payment_requirement_id
payment_attempt_id
payment_transaction_id
correlation_id
causation_id
principal_id
trace_id
```

Debe poder reconstruirse:

```text
input/conversation
 → Contact roles / Request / OfferingSelections
 → workflow + policy decisions
 → reservation items / resource decisions
 → disruption/recovery if any
 → PaymentRequirement / payment attempt
 → provider/bank/manual financial verification
 → PaymentAllocation
 → Dispatch / ServiceSession
 → Fulfillment(s)
 → event/outbox/callbacks
```

---

## 17. Workflow engine pequeño y explícito

Persistencia conceptual:

```text
workflow_key
workflow_version
workflow_state
current_step
status
next_action_at
```

Resultados posibles:

```text
need_input
execute_capability
create_capacity_hold
create_payment_requirement
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

No construir Temporal/BPMN clone.

Waitlist puede mantener Request/workflow en `wait_capacity`; no falsificar una Reservation inexistente.

---

## 18. Reservations como módulo de capacity

Boundary:

```text
Request + OfferingSelections + Participants
      ↓
reservations.search_availability
      ↓
ReservationOption
      ↓
reservations.create_hold [optional]
      ↓
payment/confirmation [optional]
      ↓
Reservation + ReservationItems
      ↓
admission/check-in/queue OR dispatch
      ↓
ServiceSession(s)
      ↓
Fulfillment(s)
```

`Reservation` significa capacity commitment, no exact-time appointment.

---

## 19. Reservation commitment lifecycle

No usar un status gigante que duplique otros aggregates.

Una Reservation nace cuando el commitment se confirma; la etapa temporal previa pertenece a `CapacityHold`.

Commitment statuses iniciales:

```text
confirmed
cancelled
completed
no_show
expired   [cuando una policy válida lo requiera]
```

No persistir como Reservation statuses:

```text
held
checked_in
waiting_in_queue
en_route
in_service
```

porque esos estados pertenecen a CapacityHold, CheckIn/QueueEntry, Dispatch y ServiceSession.

Reschedule debe preservar history. Puede mantener el mismo public Reservation identity o producir replacement según decisión de implementación/ADR, pero nunca debe borrar el commitment anterior sin event/audit/snapshot suficiente.

---

## 20. Operational health y read projection

Una Reservation confirmada puede dejar de ser operacionalmente cumplible sin dejar automáticamente de ser commitment.

Read projection:

```text
operational_health:
  valid
  at_risk
  blocked

current_operational_state:
  scheduled
  checked_in
  waiting_in_queue
  en_route
  in_service
  completed
  etc.
```

`current_operational_state` se compone de Reservation + CheckIn + QueueEntry + Dispatch + ServiceSession. No es un segundo source of truth.

`operational_health` deriva principalmente de active allocations + open ReservationDisruptions y puede persistirse como projection/cache si mejora queries, siempre reconciliable desde authoritative state.

---

## 21. Availability y `ReservationOption`

Availability puede producir contratos discriminados:

```text
ScheduledOption
WindowOption
QueueOption
HybridOption
```

Una opción puede ser efímera/opaca. Nunca garantiza commit futuro.

El consumidor no necesita conocer el resource graph completo. El engine revalida al confirmar.

Availability recibe/resuelve:

- ReservationItems candidate;
- participants/party size;
- quantities;
- resource preferences;
- Location/Destination/ServiceArea;
- schedules/policies.

---

## 22. `CapacityHold`

Reclamación temporal únicamente cuando existe intención real de continuar.

Invariantes:

- explicit expiry;
- tenant scope;
- idempotency;
- referencia a candidate ReservationItems/capacity relevante;
- observable expiration;
- no tratar como Reservation confirmada.

No crear holds durante browsing normal.

Un pago que llega después de expiry **no revive** el hold. Dinero y capacity siguen lifecycles separados.

---

## 23. Admission policies

Modos:

```text
scheduled
queue
window
hybrid
```

`scheduled`: check-in, grace/no-show detection rules.

`queue`: `priority + ordering`, remote join/presence rules, estimated wait.

`window`: rango sin instante prometido.

`hybrid`: scheduled + queue semantics, incluyendo late-to-queue y coexistencia de walk-ins.

AdmissionPolicy puede determinar `no_show_after` o cuándo un late arrival entra a queue; `NoShowPolicy` determina consecuencias de negocio/financieras.

---

## 24. Queue y Waitlist

```text
QueueEntry
= operational waiting associated with committed/admitted work

WaitlistEntry
= uncommitted interest in future capacity
```

`QueueEntry` referencia Reservation.

`WaitlistEntry` no consume capacity y no requiere Reservation.

Modelo conceptual futuro/opt-in:

```text
waitlist_entries
  organization_id
  request_id nullable
  offering_selection_id / offering refs
  participant/party-size refs
  location/date/window/resource preferences
  priority/order data
  status
  created_at
```

Cuando aparece capacity:

```text
WaitlistEntry
   ↓
matching policy
   ↓
short-lived CapacityHold/offer
   ↓
customer acceptance
   ↓
Reservation confirmation
```

No implementar un universal waitlist optimizer en foundation. La semántica queda fijada aunque implementation pueda esperar.

---

## 25. Check-in, QueueEntry y ServiceSession

```text
Reservation    = planned/committed capacity
CheckIn        = presence/readiness
QueueEntry     = dynamic queue state
ServiceSession = actual execution
```

No sobrescribir tiempos planificados con ejecución real.

Una Reservation puede tener 0..N ServiceSessions.

ServiceSession conceptual:

```text
id
organization_id
reservation_id nullable
status
actual_start
actual_end
resource references/snapshot when useful
metadata
```

Multiple ServiceSessions permiten procesos multietapa antes de justificar `ReservationSegment`.

---

## 26. Resource model

### `Resource`

Algo cuya disponibilidad/capacity limita autoritativamente una Reservation.

Kinds conceptuales:

```text
person
facility
room
chair
equipment
vehicle
pool
virtual
```

Kind ayuda UX/metadata; compatibilidad se basa principalmente en capabilities/requirements.

Resources referenciados históricamente no deben hard-delete/cascade de forma que destruya allocations/audit. `status`/deactivation preserva historia.

### `ResourceCapability`

Tenant-scoped:

```text
id
organization_id
key
name
status
metadata
```

Association many-to-many entre Resources y capabilities.

No enums verticales globales.

---

## 27. Capacity models

V2 limita capacity a:

```text
exclusive
units
```

### exclusive

Resource sólo puede ser consumido por una Reservation conflictiva a la vez en el intervalo relevante.

### units

Resource ofrece N unidades; Reservations consumen unidades.

```text
capacity_model
capacity_units
```

No usar capacity como inventory general ni multidimensional compute/workforce solver.

---

## 28. `ResourceRequirement` + quantity rules

`ResourceRequirement` expresa demanda del Offering, no selección concreta.

Conceptualmente:

```text
id
offering_id
capability_id
quantity_rule
base_units nullable
validated_input_key nullable
selection_policy
resource_group_id nullable
fixed_resource_id nullable
constraints limited/typed
version/status
```

Quantity rules iniciales:

```text
fixed
per_selection_unit
per_participant
from_validated_input
```

Semántica:

```text
fixed
  → base_units total

per_selection_unit
  → base_units × ReservationItem.quantity

per_participant
  → base_units × relevant participant count

from_validated_input
  → units read from a declared typed field in validated Request/selection input
```

`from_validated_input` sólo puede apuntar a un field permitido por schema/configuration; no arbitrary path/expression/SQL/JS.

Al confirmar Reservation, guardar quantity efectiva/requirement snapshot suficiente para que cambios futuros no reinterpreten historia.

Selection policies iniciales:

```text
any
customer_selectable
fixed
```

Constraints limitados/tipados:

```text
specific resource preference
capability
location compatibility
resource group
simple attribute equality
service-area compatibility
```

---

## 29. ResourceAllocation y Assignment

Modelo conceptual:

```text
resource_allocations
  organization_id
  reservation_id
  reservation_item_id nullable
  requirement_id/reference
  resource_id or pool_resource_id
  units
  planned_from nullable
  planned_to nullable
  status
  requirement/allocation snapshot
  created_at
  released_at nullable
  replaced_by_allocation_id nullable
```

Statuses mínimos:

```text
active
released
replaced
```

Preservar:

```text
Allocation = committed capacity
Assignment = concrete execution resource
```

En barbería ocurren juntos. En field service puede reservarse pool y asignar persona/vehículo después.

Allocations de una misma Reservation no necesitan compartir exactamente el mismo intervalo.

No overwrite histórico al sustituir Resource.

---

## 30. ResourceGroup vs pool

```text
ResourceGroup
= grouping/filtering/discovery

Resource(kind=pool)
= reservable aggregate capacity
```

Pool permite late binding seguro de capacity agregada.

---

## 31. Availability matching

Scheduler resuelve:

```text
OfferingSelections
    ↓
ReservationItems candidate
    ↓
ResourceRequirement[] + quantity rules
    ↓
Schedule constraints
    ↓
Location/ServiceArea compatibility
    ↓
compatible Resources/pools
    ↓
remaining capacity
    ↓
ReservationOption
```

Objetivo: garantizar capacity válida, no optimización global.

No implementar inicialmente route optimization, labor-cost optimizer, skill scoring complejo o workforce scheduling global.

---

## 32. `ReservationPolicy`

`ReservationPolicy` es distinto de `AdmissionPolicy` y `PaymentPolicy`.

Composición versionada:

```text
ReservationPolicy
├── CancellationPolicy
├── ReschedulePolicy
└── NoShowPolicy
```

Puede asociarse a Offering/organization/Location según reglas de precedence documentadas, con snapshot/version aplicado al confirmar Reservation.

Evaluation inputs mínimos:

```text
initiator_source: customer | business | system
reason_code/context
current time vs planned service
reservation commitment status
admission/check-in context
policy version
```

Output debe ser **typed policy decision**, no arbitrary executable rule:

```text
allowed / denied / requires_override
capacity consequence
rebooking/reschedule consequence
financial consequence directive
notification/handoff requirement when applicable
reason code
policy version
```

Financial consequence puede expresar una intención tipada como:

```text
no_financial_action
refund_full
refund_percentage
refund_fixed
forfeit_existing_amount
create_fee_requirement
```

pero Payments ejecuta la consecuencia mediante PaymentRequirement/Refund/reconciliation. ReservationPolicy nunca edita PaymentTransaction.

Overrides requieren scope `reservations.override_policy`, reason y audit.

No construir generic rules DSL. Implementar evaluators tipados/versionados.

---

## 33. `ReservationDisruption` y recovery

Cambios de Resource/Schedule/Location no cancelan silenciosamente commitments confirmados.

Modelo conceptual:

```text
reservation_disruptions
  id / public_id if exposed
  organization_id
  reservation_id
  reason
  source_entity_type
  source_entity_id nullable
  status
  detected_at
  recovery_started_at nullable
  resolved_at nullable
  resolution_type nullable
  resolution_summary/metadata
```

Reasons iniciales:

```text
resource_unavailable
location_unavailable
capacity_reduced
schedule_exception
assignment_failed
service_area_changed
other_operational
```

Statuses:

```text
open
recovering
resolved
escalated
```

Resolution types:

```text
reallocated
reassigned
rescheduled
cancelled
manual_override
```

Flow:

```text
Resource/Schedule/Location change
      ↓
find affected active allocations/reservations
      ↓
OpenReservationDisruption
      ↓
operational_health = at_risk
      ↓
try compatible reallocation within existing commitment
      │
      ├─ success → release/replace allocations + resolved
      │
      └─ no safe capacity → health = blocked
                         ↓
                policy-governed reschedule/cancel/handoff
```

Recovery dentro del mismo committed interval puede replace allocations sin cambiar commitment.

Si cambia time/window/Destination de forma material, usar commands/policies apropiados y revalidar capacity.

Bulk Resource/Schedule changes pueden emitir job/outbox para detectar affected Reservations; proceso idempotente.

---

## 34. Schedules: BusinessHours vs AvailabilitySchedule

### `BusinessHours`

Cuándo organization/Location está normalmente abierta/presentable al público.

### `AvailabilitySchedule`

Cuándo Offering/Resource/pool puede reservarse.

Pueden diferir.

```text
Office BusinessHours: Mon–Fri 09:00–17:00
Emergency Offering AvailabilitySchedule: 24/7
```

---

## 35. Schedule representation

Schedule recurrente con timezone IANA y múltiples intervals por weekday.

```text
Schedule
id
organization_id
timezone
purpose
status

ScheduleRule
schedule_id
weekday
local_start
local_end
```

Un día cerrado no tiene intervals efectivos.

Soportar:

```text
Mon–Fri 09:00–18:00
Saturday 09:00–12:00
Sunday closed
```

así como split shifts.

---

## 36. Schedule hierarchy

Scopes:

```text
Organization
Location
Offering
Resource / Pool
```

Effective availability se calcula por composición/intersección, exceptions y capacity comprometida.

> Un child schedule puede restringir un parent scope, pero no abrir silenciosamente un parent cerrado.

Apertura extraordinaria debe ser explícita.

---

## 37. `ScheduleException` y `HolidayCalendar`

Exception types iniciales:

```text
closed
replace_hours
open_special
capacity_override
```

Conceptualmente:

```text
id
organization_id
scope_type
scope_id
starts_on / ends_on
exception_type
replacement_intervals nullable
capacity_units nullable
reason
metadata
```

`HolidayCalendar` + `HolidayDate` + HolidayPolicy/reference.

No hardcodear “feriado = cerrado”. Policies:

```text
closed_by_default
normal_schedule
special_hours
```

Permitir calendars oficiales importados/configurados y custom dates.

La fuente/actualización externa puede ser integration; estado efectivo aplicado debe ser auditable.

Al crear una exception que afecta Reservations confirmadas, disparar disruption detection; no modificar/cancelar rows silenciosamente.

---

## 38. Location model

`Location` representa lugar operativo de la organization.

Campos conceptuales:

```text
id
public_id
organization_id
name
description
structured_address
timezone
business_hours_schedule_id nullable
status
map_url nullable
latitude nullable
longitude nullable
arrival_instructions nullable
parking_instructions nullable
accessibility_instructions nullable
metadata
```

`map_url` puede almacenar Google Maps share/place/pin URL u otra referencia compatible.

No hacer `google_place_id` ni coordinates identidad primaria.

---

## 39. Location information + `LocationMedia`

API presenta:

```text
open_now
today_hours
next_open_at
special/holiday state
human-readable address
map/share URL
arrival instructions
media
```

Raw lat/lon son opcionales para interoperabilidad; map/share URL es first-class desde producto.

`LocationMedia`:

```text
id
location_id
media_type
purpose
asset_reference
title
caption
alt_text
transcript nullable
sort_order
status
```

Purposes:

```text
hero
gallery
entrance
parking
arrival_instruction
accessibility
landmark
```

Blobs viven en object/media storage.

---

## 40. `Destination` y cambios controlados

Destination pertenece al trabajo concreto, no catálogo de Locations.

Conceptualmente snapshot-based:

```text
id / owned snapshot according to aggregate decision
reservation_id
contact/location reference nullable
label
structured_address
map_url nullable
latitude/longitude nullable
access_notes nullable
snapshot_version
```

Cambios futuros del Contact no alteran historial.

`ChangeDestination` debe:

1. authorization/policy;
2. validate ServiceArea;
3. re-evaluate pricing/payment requirement when applicable;
4. re-evaluate resource compatibility/capacity;
5. recalculate Dispatch ETA through adapter when needed;
6. persist new snapshot + audit old/new;
7. emit events/outbox.

No editar un Destination en-route como simple PATCH sin domain validation.

---

## 41. `ServiceArea`

Validación inicial:

```text
named_zone
city/province
postal_code
radius
```

Puede asociarse a organization, Location, Offering o Resource/pool.

No empezar con polygons/routing-time solver. PostgreSQL/PostGIS puede evaluarse mediante ADR si casos reales lo requieren.

---

## 42. Dispatch module

`Dispatch` modela movimiento/coordinación de capacity asignada hacia Destination para field service.

Conceptualmente:

```text
id
public_id
organization_id
reservation_id
status
destination_snapshot/reference
assigned_at nullable
en_route_at nullable
arrived_at nullable
estimated_arrival_at nullable
tracking_url nullable
latest_latitude nullable
latest_longitude nullable
last_location_at nullable
metadata
```

Estados:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No exigir 1 Dispatch por Reservation. Recovery puede producir redispatch/second attempt si el dominio lo necesita.

---

## 43. Dispatch tracking y customer updates

Guardar estado útil, no raw telemetry history.

Permitido:

```text
current status
ETA
tracking/share URL
latest meaningful coordinates
last update timestamp
assigned resource display data
```

Fuera del source of truth principal:

```text
GPS ping every 5 seconds
full movement polyline history
high-frequency telemetry
```

Tracking continuo:

```text
GPS/mobile provider
    ↓
telemetry/tracking system
    ↓
current operational projection/event
    ↓
Request Engine
```

Events:

```text
dispatch.assigned
dispatch.en_route
dispatch.eta_updated
dispatch.arrived
```

Adapters convierten hechos en WhatsApp/SMS/voice/portal/push/webhook.

---

## 44. Delivery boundary

No generalizar Dispatch inmediatamente a e-commerce logistics.

```text
Dispatch = operational resource movement for service execution
```

Futuro Delivery puede reutilizar Destination/windows/tracking refs/events, pero shipment/packages/courier/proof-of-delivery sólo con caso real.

---

## 45. Reservation concurrency e invariantes

Confirmation revalida en transaction:

1. tenant;
2. OfferingSelections/ReservationItems activos y consistentes;
3. participant/recipient quantities válidas;
4. effective schedules + holiday/exception resolution;
5. Location/Destination/ServiceArea compatibility;
6. ResourceRequirements + quantity rules resueltos;
7. hold válido cuando requerido;
8. no overlaps para exclusive resources;
9. remaining units para resources/pools;
10. ReservationPolicy/PaymentPolicy snapshot válido;
11. payment gate satisfecho cuando policy lo exige;
12. idempotency key coherente;
13. snapshots persistidos;
14. event/outbox en mismo commit.

Usar PostgreSQL constraints/ranges/locking donde simplifiquen garantías.

Payment gate consulta estado interno ya reconciliado; **no llama PSP/bank dentro de transaction**.

---

## 46. Payments: arquitectura provider-agnostic y verificable

Payments es coordinación financiera para workflows, **no accounting, PSP ni card vault**.

```text
Pricing
    ↓
PaymentPolicy
    ↓
PaymentRequirement
    ↓
PaymentAttempt
    ↓
PaymentInstruction / PaymentEvidence?
    ↓
PaymentTransaction
    ↓
PaymentAllocation
    ↓
Requirement state
    ↓
Workflow continues
```

Invariantes:

```text
PaymentEvidence ≠ money received
browser success ≠ authoritative confirmation
PaymentAttempt ≠ PaymentTransaction
PaymentTransaction ≠ PaymentAllocation
PaymentRequirement ≠ Invoice
Fulfillment ≠ financial settlement
```

### 46.1 `PaymentPolicy`

Configuration reusable asociada al Offering/workflow/organization.

```text
id
organization_id
name
mode
amount_rule
payment_timing
reservation_gate
capacity_strategy
accepted_method_configuration_ids
status
version
metadata
```

Modes:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Capacity strategies:

```text
hold_until_payment
revalidate_after_payment
confirm_then_collect
```

Policy version/snapshot relevante persiste al consumirla.

### 46.2 `Money`

```text
amount
currency
```

Nunca float binario. Persistencia exacta (`amount_minor BIGINT` + ISO currency o `NUMERIC` + currency) debe fijarse por ADR/convention.

No FX implícito.

### 46.3 `PaymentRequirement`

Obligación concreta.

```text
id
public_id
organization_id
request_id nullable
reservation_id nullable
payer_contact_id / participant reference nullable
purpose
amount
currency
status
due_at nullable
policy_snapshot
created_at
updated_at
satisfied_at nullable
metadata/source refs
```

Estados:

```text
open
partially_satisfied
satisfied
waived
cancelled
```

`overdue` derivado.

Satisfaction deriva de allocations válidas, no boolean aislado.

No exigir un único Offering/ReservationItem target; un Requirement puede cubrir una obligación agregada de Request/Reservation. Si line-level allocation comercial se vuelve necesaria, añadir `PaymentRequirementLine` mediante caso real, no metadata opaca obligatoria desde día uno.

### 46.4 `PaymentMethodConfiguration`

Tenant-scoped:

```text
id
organization_id
method_family
provider_connection_id nullable
display_name
supported_currencies
verification_mode
status
configuration/reference
```

Method families:

```text
card
bank_transfer
cash
wallet
external
custom
```

Provider no es method family. Sensitive config usa secret refs.

### 46.5 `PaymentProviderConnection`

```text
id
organization_id
provider_key
status
secret_reference
webhook_configuration/reference
capabilities
metadata_safe
```

No secretos legibles en rows/API responses.

Adapters traducen provider semantics; no deciden business policy.

### 46.6 Adapter contract

Conceptualmente:

```text
create_attempt / create_session
get_customer_action
query_status
handle_webhook
cancel_or_void
refund
fetch_or_receive_transactions [when supported]
```

No necesariamente una única mega-interface; separar capabilities si mejora diseño.

### 46.7 `PaymentAttempt`

```text
id
public_id
organization_id
payment_requirement_id
payment_method_configuration_id
payer_contact_id nullable
status
provider_connection_id nullable
external_attempt_id nullable
instruction_snapshot nullable
created_at
expires_at nullable
completed_at nullable
metadata
```

Estados:

```text
created
awaiting_customer_action
evidence_submitted
verification_pending
processing
authorized
succeeded
failed
cancelled
expired
```

Attempt success no sustituye Requirement satisfaction: Transactions + Allocations mandan.

### 46.8 `PaymentInstruction`

Owned snapshot/versioned payload o entidad separada si lifecycle lo exige.

Contratos discriminados:

```text
BankTransferInstruction
RedirectInstruction
QrInstruction
CashInstruction
ExternalInstruction
```

Bank transfer snapshot:

```text
bank_name
account_holder
masked/display account details
account_type
amount/currency
transfer_reference
expires_at
customer_message
```

Cambio de account config no altera instrucciones históricas.

### 46.9 `PaymentEvidence`

```text
id
organization_id
payment_attempt_id
kind
private_asset_reference nullable
claimed_amount nullable
claimed_currency nullable
claimed_reference nullable
claimed_at nullable
file_hash nullable
status
submitted_by
created_at
reviewed_at nullable
metadata
```

Estados:

```text
submitted
under_review
accepted_as_evidence
rejected
```

Nunca puede crear por sí sola `PaymentTransaction.settled` ni satisfy Requirement.

Blobs en private object storage. File hash es señal, no fraude automático.

### 46.10 `PaymentTransaction`

Movimiento financiero autoritativamente observado/confirmado.

```text
id
public_id
organization_id
provider_connection_id nullable
method_family
status
amount
currency
source
external_transaction_id nullable
occurred_at nullable
received_at nullable
verified_by_principal_id nullable
verification_metadata/reference
created_at
```

Sources:

```text
provider_webhook
provider_api
bank_feed
bank_api
manual_bank_verification
cash_verification
external_system
```

Estados:

```text
pending
authorized
settled
failed
reversed
```

Default: sólo settled satisface Requirements salvo explicit future policy.

No borrar transactions tras reversal/refund/dispute.

Unique/idempotency constraints impiden duplicar external transaction/webhook por provider/tenant.

### 46.11 Bank transfer reconciliation

Con integration:

```text
bank feed/webhook/API
      ↓
validated event
      ↓
RecordBankTransaction
      ↓
PaymentTransaction
      ↓
match/reconciliation
      ↓
PaymentAllocation
```

Sin integration:

```text
PaymentEvidence? [optional]
      ↓
verification_pending
      ↓
authorized principal independently checks bank account
      ↓
VerifyBankTransferManually
      ↓
PaymentTransaction(source=manual_bank_verification)
```

Manual verification captura principal, timestamp, receiving-account/config ref, external ref when available, amount/currency y reason/note cuando aplique.

No command “accept screenshot as payment”.

### 46.12 `PaymentAllocation`

```text
id
organization_id
payment_transaction_id
payment_requirement_id
amount
currency
status
created_at
created_by/source
reversed_at nullable
metadata
```

Garantías:

- compatible currency o conversion explícita;
- active allocations no exceden applicable Transaction amount;
- Requirement satisfaction deriva de active allocations;
- idempotent/reconcilable;
- reversal/refund ajusta/revierte allocations sin borrar historia.

Soporta partial payments, multiple transactions, one transaction across requirements y overpayment/unallocated funds.

### 46.13 `ReconciliationCase`

```text
id
public_id
organization_id
status
reason
payment_transaction_id nullable
payment_attempt_id nullable
candidate_requirement_ids/reference
resolution
resolved_by nullable
resolved_at nullable
created_at
metadata
```

Reasons:

```text
missing_reference
ambiguous_match
unknown_attempt
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
```

No auto-asignar matching ambiguo.

### 46.14 Pago tardío versus Reservation

```text
CapacityHold expired
PaymentTransaction settled later
```

Resultado:

```text
money remains real/recorded
Reservation remains unconfirmed
workflow enters reconciliation/revalidation
```

Nunca confirmar slot viejo sin revalidar.

### 46.15 Cash

```text
PaymentAttempt(cash)
      ↓
authorized principal receives cash
      ↓
RecordCashReceived
      ↓
PaymentTransaction(cash_verification)
      ↓
PaymentAllocation
```

No special boolean `cash_paid`.

### 46.16 Provider redirects/webhooks

Browser success/cancel URL es UX, no authority.

Authority:

```text
signed provider webhook
server-to-server provider API
bank API/feed
manual independent verification
```

Webhook handling:

1. signature/auth validation;
2. anti-replay/event dedupe;
3. normalize to internal command;
4. idempotent transaction;
5. event/outbox;
6. acknowledge provider.

### 46.17 Refund

```text
id
public_id
organization_id
payment_transaction_id
amount
currency
status
provider_connection_id nullable
external_refund_id nullable
requested_by
reason nullable
created_at
completed_at nullable
```

Estados:

```text
requested
processing
succeeded
failed
cancelled
```

Partial refund permitido. Void authorization != Refund.

Refund/reversal reconcilia allocations/requirements según policy sin borrar historia.

### 46.18 ReservationPolicy ↔ Payments boundary

ReservationPolicy produce una **financial consequence directive**. Application layer traduce esa decisión a commands de Payments.

Ejemplo:

```text
CancelReservation(customer, <2h)
      ↓
CancellationPolicy decision
  allow
  release capacity
  forfeit deposit
      ↓
Payments keeps existing allocation / no refund
```

Otro:

```text
CancelReservation(business)
      ↓
CancellationPolicy decision
  allow
  release capacity
  refund_full
      ↓
RequestRefund
```

Nunca permitir que ReservationPolicy mutile PaymentTransaction directamente.

### 46.19 Fulfillment vs financial settlement

Chargeback/reversal después de servicio:

```text
ServiceSession remains fact
Fulfillment remains fact
PaymentTransaction becomes reversed/new reversal fact
PaymentAllocation reconciles
PaymentRequirement may become open/partially satisfied again
```

Puede abrir ReconciliationCase o nuevo Request de balance; no reescribir historial operacional.

### 46.20 Provider-independent states + idempotency

Adapters mapean provider states a estados canónicos. Domain code nunca hace `if stripe_status`.

Idempotency crítica para:

```text
CreatePaymentRequirement
CreatePaymentAttempt
provider webhooks
bank transaction ingestion
manual verification
PaymentAllocation
refund creation/callbacks
```

Same idempotency key + materially different payload = conflict.

### 46.21 Payment security

- PAN/CVV nunca en Request Engine;
- provider token/reference en su lugar;
- bank/PSP secrets en secret manager/config segura;
- PaymentEvidence privado;
- signed short-lived asset URLs;
- audit de access/verification sensible;
- scopes `payments.read/create/verify/refund/reconcile`;
- no financial PII completa en logs;
- agent tools no exponen internals innecesarios.

---

## 47. Forms / public intake

`FormDefinition` + `FormSubmission` inicialmente.

Schemas reutilizables por website, agent, human UI y API.

Intake puede construir/actualizar:

- Contacts;
- participant roles;
- OfferingSelections;
- validated quantity inputs;
- Request data.

No construir form-builder universal inicialmente.

---

## 48. Agent boundary

Tools goal-oriented:

```text
search_offerings
get_business_locations
get_location_details
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

El modelo no recibe access a tables, relationship graph internals, resource graph internals, raw telemetry, PSP internals, bank feeds ni arbitrary writes.

Participant roles/OfferingSelections enviados por agent pasan validación de schemas y authorization.

No tool genérica `mark_payment_paid`.

Policy overrides, payment verification/refund/reconciliation y force recovery requieren deterministic commands + scopes y, cuando corresponde, Principal humano/trusted callback.

---

## 49. Integraciones

Chatwoot, LiveKit, WhatsApp, Twilio, n8n, maps providers, media storage, tracking providers, banks y PSPs son adapters.

n8n puede experimentar con integrations pero no controla Request/Reservation/payment state autoritativo.

Provider adapters traducen semantics; no contienen ReservationPolicy o PaymentPolicy de negocio.

---

## 50. Security baseline

- secret keys hashed/stored securely;
- explicit scopes;
- expiry/revocation;
- public surface rate limits;
- signed webhooks + anti-replay;
- PII encryption when threat model requires;
- audit privileged changes;
- cross-tenant tests para participants/selections/reservations/payments;
- location/tracking data scoped appropriately;
- public tracking tokens expose only minimum necessary data;
- no raw secrets/PII/GPS trails in logs;
- PAN/CVV never stored;
- PaymentEvidence private;
- bank/PSP credentials never exposed to browser/agents;
- manual payment verification requires privileged Principal;
- policy overrides/recovery overrides auditable;
- refunds/reconciliation distinct scopes from payment initiation.

---

## 51. Observabilidad

Mínimo:

- structured logs;
- correlation IDs;
- metrics;
- health/readiness;
- DB pool metrics;
- outbox lag;
- hold expiry;
- reservation conflict classifications;
- operational-health counts (`valid/at_risk/blocked`);
- open disruption count/age/recovery failures;
- queue wait metrics;
- dispatch state/ETA update failures;
- external provider errors;
- payment webhook validation/dedupe failures;
- reconciliation queue depth/age;
- payment verification latency;
- unallocated funds aggregate metrics without PII;
- refund failures;
- sanitized context.

Telemetry técnica no sustituye domain events/audit.

---

## 52. Testing strategy

### Unit

- Request transitions;
- participant-role validation;
- OfferingSelection validation;
- multi-offering workflow resolution;
- ReservationPolicy decisions by initiator/time/reason;
- ResourceRequirement quantity rules;
- schedule composition/exception precedence/holiday policies;
- admission policies;
- queue priority;
- Waitlist vs Queue semantics;
- ResourceRequirement matching;
- operational-health derivation;
- disruption/recovery decisions;
- allocation release/replacement;
- service-area validation;
- controlled Destination changes;
- Dispatch transitions;
- PaymentPolicy resolution;
- PaymentRequirement derivation;
- PaymentAttempt transitions;
- PaymentAllocation math;
- partial/overpayment;
- late-payment capacity strategy;
- refund lifecycle;
- Fulfillment cardinality/partial selection behavior.

### PostgreSQL integration

- tenant constraints across participants/selections/items;
- idempotency;
- reservation races;
- exclusive overlap prevention;
- capacity-units oversell prevention;
- dynamic quantity oversell prevention;
- hold expiry/confirmation races;
- schedule/exception edge cases;
- schedule/resource change opens disruption instead of silently altering Reservation;
- concurrent disruption recovery/reallocation;
- historical allocation preservation;
- cross-tenant isolation;
- pool allocations/late assignment;
- one Request → multiple Reservations;
- one Reservation → multiple ReservationItems;
- one Reservation → multiple ServiceSessions;
- outbox claiming/retry;
- duplicate provider webhook ingestion;
- duplicate bank transaction ingestion;
- concurrent PaymentAllocations cannot overspend Transaction;
- concurrent allocations cannot incorrectly oversatisfy Requirement;
- manual verification audit/scopes;
- payment after CapacityHold expiry;
- refund/allocation reconciliation.

### Contract

- REST/OpenAPI;
- agent schemas;
- participant/selection payloads;
- ReservationOption discriminated schemas;
- policy-decision/error contracts where public;
- webhook signatures;
- provider adapter normalization contracts;
- public location/tracking projections;
- payment instruction discriminated schemas;
- backwards compatibility where relevant.

### End-to-end

Demo Barbershop + Demo Plumbing mandatory.

Cross-scenario E2E:

```text
mother/requester reserves for child/recipient; different payer
multiple OfferingSelections in one Request
one Request creates multiple Reservations
one Reservation contains multiple ReservationItems
party-size changes capacity through per_participant rule
resource becomes unavailable after confirmation → disruption → reallocation
resource disruption cannot recover → policy-governed reschedule/cancel
customer vs business cancellation produce different consequences
no-show consequence triggers correct payment/refund behavior
one Reservation produces multiple ServiceSessions
one ServiceSession supports multiple Fulfillment records
Waitlist does not consume capacity
payment reversal after Fulfillment does not rewrite service history
```

Payments E2E:

```text
card/provider success
cash/manual verification
bank-transfer instructions + evidence + independent verification
bank transfer not found / verification_failed
partial payment/allocation
overpayment/unallocated funds
late payment after hold expiry
refund
```

---

## 53. Performance philosophy

Primero integridad/observabilidad, luego optimización medida.

Evitar:

- N+1 por slot/resource/participant;
- cargar historial completo para overlaps;
- writes por availability read;
- recalcular colas completas innecesariamente;
- scan global síncrono de todas Reservations cuando cambia un Resource;
- almacenar raw GPS stream;
- consultar routing/maps dentro de reservation transaction;
- consultar PSP/bank synchronously dentro de authoritative transaction cuando callback/projection basta;
- full scans para bank matching;
- JSONB para relaciones centrales;
- guardar full provider payloads indefinidamente.

Usar set-based SQL, índices, constraints y bounded/background recovery jobs.

---

## 54. Deployment inicial

```text
Clients
   ↓
FastAPI API
   ↓
PostgreSQL
   ↓
Worker
   ↓
External systems
```

API y Worker comparten codebase/dominio con procesos separados.

No Redis/RabbitMQ/Kafka/Temporal obligatorios.

Media blobs, PaymentEvidence y tracking telemetry usan systems/storage especializados; Request Engine conserva references/projections relevantes.

PSP/bank callbacks entran por endpoints/adapters dedicados y ejecutan commands idempotentes.

Disruption detection/recovery que no deba ser síncrono puede ejecutarse por Worker desde events/outbox.

---

## 55. Definition of Done de foundation

```text
[ ] Python/FastAPI bootstrapped
[ ] PostgreSQL migrations reproducibles
[ ] organizations/principals tenancy
[ ] contacts
[ ] RequestParticipant roles + Principal distinction
[ ] OfferingSelection + multi-selection Request proof
[ ] OfferingSelection recipient/participant association proof
[ ] locations
[ ] LocationMedia references
[ ] BusinessHours schedules
[ ] AvailabilitySchedules
[ ] ScheduleExceptions
[ ] HolidayCalendar/policy proof
[ ] offerings
[ ] request_types
[ ] requests + lifecycle
[ ] versioned workflows

[ ] Resource model
[ ] ResourceCapabilities
[ ] exclusive + units capacity
[ ] ResourceRequirements
[ ] quantity rules: fixed/per_selection_unit/per_participant/from_validated_input
[ ] ResourceGroups/pool proof
[ ] availability for scheduled/window/queue/hybrid
[ ] ReservationOption contract
[ ] CapacityHolds + expiry
[ ] ReservationItems
[ ] Reservations + concurrency protection
[ ] commitment status separated from operational projection
[ ] ResourceAllocations + release/replacement history
[ ] late assignment proof
[ ] ReservationParticipants
[ ] ReservationPolicy: cancel/reschedule/no-show
[ ] customer/business/system initiator policy proof
[ ] ReservationDisruption + operational health + recovery proof
[ ] AdmissionPolicies
[ ] CheckIn
[ ] QueueEntries
[ ] Waitlist boundary contract/proof (full implementation optional for first slice)
[ ] multiple ServiceSessions per Reservation proof
[ ] Destination snapshot + controlled change proof
[ ] ServiceArea validation
[ ] Dispatch lifecycle
[ ] dispatch status/ETA/tracking-reference projection

[ ] PaymentPolicy
[ ] exact Money representation convention
[ ] PaymentMethodConfiguration
[ ] PaymentProviderConnection/adapter boundary
[ ] PaymentRequirement + payer reference
[ ] PaymentAttempt lifecycle
[ ] typed PaymentInstruction snapshots
[ ] private PaymentEvidence references
[ ] PaymentTransaction authority/source model
[ ] PaymentAllocation + partial/multi/overpayment proof
[ ] bank-transfer reference/instructions flow
[ ] automated provider callback proof
[ ] manual independent bank verification flow + audit
[ ] cash verification flow
[ ] ReconciliationCase
[ ] late-payment after hold-expiry handling
[ ] ReservationPolicy → Refund/payment consequence boundary proof
[ ] Refund lifecycle
[ ] provider webhook signature + dedupe + idempotency proof
[ ] payment privileged scopes

[ ] Fulfillment 0..N per Request
[ ] OfferingSelection-specific/partial Fulfillment proof
[ ] one ServiceSession supporting multiple Fulfillments proof
[ ] Fulfillment/financial lifecycle independence proof
[ ] domain events
[ ] transactional outbox
[ ] worker retry/idempotency
[ ] audit trail
[ ] public + secret credentials
[ ] OpenAPI generated from schemas
[ ] TypeScript SDK generation proof
[ ] agent/MCP adapter proof
[ ] structured logs/correlation IDs
[ ] PostgreSQL integration tests
[ ] Demo Barbershop vertical slice
[ ] Demo Plumbing vertical slice
```

Foundation se considera conceptualmente madura cuando capacity, participants, selections, operational recovery y money pueden coordinarse sin convertir Request Engine en scheduler universal, CRM, PSP o ERP.

---

## 56. Deliberadamente fuera de foundation inmediata

No implementar todavía sin caso real:

```text
ReservationSegment
ReservationSeries
Subscription
Agreement
Delivery logistics platform
WorkforceOptimizer
generic rules DSL
```

### Multi-stage

Multiple ResourceAllocations con intervals distintos + multiple ServiceSessions cubren el caso inicial. Sólo introducir `ReservationSegment` si necesitamos lifecycle/state independiente por etapa.

### Recurrence/subscription

Reservations individuales pueden existir hoy. Si después necesitamos una regla generadora recurrente, un futuro `Agreement`/`ReservationSeries` puede generar Requests, Reservations y PaymentRequirements.

No agregar recurrence flags ambiguos a Reservation.

---

## 57. Regla arquitectónica final

Para identidad/intención:

```text
Principal          = actor that performed mutation
Contact            = business identity
Participant        = Contact role in this work
Offering           = what can be obtained
OfferingSelection  = selected Offering/quantity/recipient
Request            = what is wanted now
Workflow           = what must happen
```

Para capacity:

```text
ReservationItem      = selected Offering quantity under commitment
Resource             = what can provide capacity
Capacity             = how much it can provide
ResourceRequirement  = what capacity ReservationItem needs
ResourceAllocation   = what capacity Reservation committed
Assignment           = which concrete Resource executes
Schedule             = when capacity may exist
Reservation          = committed capacity
OperationalHealth    = whether commitment is currently fulfillable
ReservationDisruption = durable recovery case
Admission             = how access to service occurs
QueueEntry            = committed operational waiting
WaitlistEntry         = uncommitted interest in future capacity
```

Para lugar/ejecución:

```text
Location       = where organization operates/receives
Destination    = where this specific work must occur
Dispatch       = movement/coordination toward Destination
ServiceSession = actual execution
Fulfillment    = verified outcome
```

Para policy:

```text
ReservationPolicy = cancellation/reschedule/no-show consequences
PaymentPolicy     = how/when money is required
```

Para payments:

```text
PaymentRequirement = concrete money obligation
PaymentAttempt     = one method-specific attempt
PaymentInstruction = what payer was told to do
PaymentEvidence    = supporting evidence, never money by itself
PaymentTransaction = authoritative observed financial movement
PaymentAllocation  = how verified money satisfies requirements
ReconciliationCase = ambiguity requiring explicit resolution
Refund             = explicit return-of-funds lifecycle
```

Request Engine debe saber **qué necesita ocurrir, para quién, qué Offering(s) están involucrados, si puede ocurrir válidamente, qué capacity fue comprometida, si ese commitment sigue operacionalmente cumplible, qué obligación financiera existe, qué dinero fue realmente verificado/aplicado y qué outcome ocurrió**.

No debe convertirse en todos los sistemas especializados que participan alrededor de ese proceso.
