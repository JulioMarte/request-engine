# Request Engine V2 — arquitectura de referencia

> **Estado:** arquitectura objetivo para la reimplementación de Request Engine.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> Este documento traduce la esencia del producto a decisiones técnicas. Si una decisión técnica entra en conflicto con la definición del producto, **gana la definición del producto**.

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
2. convertirla en `Request`;
3. resolver `Offering`, Location/Destination y policies cuando corresponda;
4. determinar workflow versionado;
5. ejecutar capabilities deterministas;
6. calcular y comprometer capacidad válida;
7. coordinar reservations, admission, dispatch, payments, callbacks o intervención humana;
8. producir `Fulfillment` verificable;
9. mantener trazabilidad completa.

No es CRM, ERP, PBX, calendario tradicional, GPS telemetry store, shipping platform, PSP, banco, accounting ledger ni framework universal de agentes.

---

## 2. Stack adoptado

### PostgreSQL

Source of truth transaccional.

El dominio incluye relaciones e invariantes fuertes alrededor de:

- organizations/tenancy;
- contacts;
- locations;
- schedules/exceptions/holidays;
- offerings;
- request types/requests/workflows;
- resources/capabilities/requirements;
- capacity holds/reservations/allocations;
- check-ins/queues/service sessions;
- destinations/service areas/dispatches;
- payment policies/requirements/attempts/transactions/allocations/reconciliation/refunds;
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

---

## 7. Persistencia relacional primero

No convertir PostgreSQL en document store accidental.

Campos de identidad, relaciones, lifecycle, constraints, scheduling, pagos y reporting operacional deben ser columnas/tables tipadas.

JSONB queda para metadata dinámica, snapshots o payloads cuyo schema varía de forma legítima.

Public IDs separados de PKs internas:

```text
org_...
cnt_...
loc_...
off_...
req_...
res_...
dsp_...
prq_...   payment requirement
pat_...   payment attempt
ptx_...   payment transaction
rfd_...   refund
ful_...
evt_...
```

External provider IDs permanecen mappings/references.

---

## 8. Offering y RequestType

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
 + Offering
 + Organization policy
 + Request context
 ↓
workflow_key + workflow_version
```

---

## 9. Commands y Queries

### Commands

```text
CreateRequest
ProvideRequestData
AdvanceRequest
CreateCapacityHold
ConfirmReservation
RescheduleReservation
CancelReservation
CheckInReservation
JoinReservationQueue
AssignReservationResources
CreateDispatch
AssignDispatch
MarkDispatchEnRoute
UpdateDispatchEta
MarkDispatchArrived
StartServiceSession
CompleteServiceSession

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
```

`VerifyBankTransferManually`, `RecordCashReceived`, refund commands y reconciliation overrides requieren scopes privilegiados y audit explícito.

### Queries

```text
GetRequest
ListOpenRequests
ListOfferings
GetLocation
GetLocationCurrentHours
SearchAvailability
GetReservation
ListReservations
GetQueueState
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

Queries no producen side effects. `SearchAvailability` no crea holds/reservations. `GetPaymentStatus` no verifica ni cambia dinero.

---

## 10. Transacciones

```text
BEGIN
  validate current state
  resolve authoritative policy
  lock/revalidate capacity or financial allocation where needed
  mutate internal state
  insert domain event/outbox
COMMIT
```

Nunca mantener transacción abierta mientras se llama payment provider, bank API, maps/routing provider, WhatsApp, LiveKit, n8n u otro sistema remoto.

Callbacks externos se validan primero y luego ejecutan commands transaccionales cortos.

---

## 11. Outbox

PostgreSQL transactional outbox inicialmente.

Worker con claiming seguro (`FOR UPDATE SKIP LOCKED` u otra estrategia justificada), retry/backoff, dead-letter/failure state, idempotent delivery y event versioning.

Queue externa sólo por necesidad medida.

Payments usa el mismo principio: crear una payment session externa, enviar notifications o solicitar reconciliation bancaria no debe mantener una business transaction abierta.

---

## 12. Domain events, audit y logs

Eventos representativos:

```text
request.created
request.ready
capacity_hold.created
capacity_hold.expired
reservation.confirmed
reservation.checked_in
reservation.enqueued
reservation.cancelled
resource.assigned
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

En payments, audit debe poder distinguir `provider_webhook`, `provider_api`, `bank_feed`, `bank_api`, `manual_bank_verification`, `cash_verification` y `external_system` como source de una mutación financiera.

---

## 13. Correlation y causality

Propagar cuando corresponda:

```text
request_id
reservation_id
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
 → Request
 → workflow decision
 → reservation/resource decision
 → PaymentRequirement / payment attempt
 → provider/bank/manual financial verification
 → PaymentAllocation
 → dispatch/tool action
 → transaction
 → event/outbox
 → callback
 → Fulfillment
```

---

## 14. Workflow engine pequeño y explícito

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
wait_payment
wait_payment_verification
wait_external
wait_human
complete
fail_recoverable
fail_terminal
```

No construir Temporal/BPMN clone.

---

## 15. Reservations como módulo de capacidad

Boundary:

```text
Request workflow
      ↓
reservations.search_availability
      ↓
ReservationOption
      ↓
reservations.create_hold [optional]
      ↓
payment/confirmation [optional]
      ↓
reservations.confirm
      ↓
admission/check-in/queue
      ↓
ServiceSession or Dispatch
      ↓
Fulfillment
```

`Reservation` significa capacity commitment, no exact-time appointment.

---

## 16. Availability y `ReservationOption`

Availability puede producir contratos discriminados:

```text
ScheduledOption
WindowOption
QueueOption
HybridOption
```

Una opción puede ser efímera/opaca. Nunca garantiza commit futuro.

El consumidor no necesita conocer el grafo interno completo de Resources. El engine puede devolver una opción utilizable y revalidar al confirmar.

---

## 17. `CapacityHold`

Reclamación temporal únicamente cuando existe intención de continuar.

Invariantes:

- explicit expiry;
- tenant scope;
- idempotency;
- referencia a la capacidad relevante;
- observable expiration;
- no tratar como Reservation confirmada.

No crear holds durante browsing normal.

Un pago que llega después de expiry **no revive** el hold. El dinero y la capacidad siguen lifecycles separados.

---

## 18. Admission policies

Modos:

```text
scheduled
queue
window
hybrid
```

`scheduled`: check-in, grace/no-show policies.

`queue`: `priority + ordering`, remote join/presence rules, estimated wait.

`window`: rango sin instante prometido.

`hybrid`: scheduled + queue semantics, incluyendo late-to-queue y coexistencia de walk-ins.

---

## 19. Check-in, queue y ejecución

```text
Reservation    = planned/committed capacity
CheckIn        = presence/readiness
QueueEntry     = dynamic queue state
ServiceSession = actual execution
```

No sobrescribir tiempos planificados con ejecución real.

---

## 20. Resource model

### `Resource`

Algo cuya disponibilidad/capacidad limita autoritativamente una Reservation.

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

Kind ayuda a UX/metadata; la compatibilidad se basa principalmente en capabilities/requirements.

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

## 21. Capacity models

V2 limita capacity a dos modelos iniciales:

```text
exclusive
units
```

### exclusive

El Resource sólo puede ser consumido por una Reservation conflictiva a la vez en el intervalo relevante.

### units

El Resource ofrece N unidades y reservations consumen unidades.

Campos conceptuales:

```text
capacity_model
capacity_units
```

No usarlo como inventario comercial general ni como multidimensional compute/workforce solver.

---

## 22. Resource requirements

`ResourceRequirement` expresa demanda del Offering, no selección concreta.

Conceptualmente:

```text
id
offering_id
capability_id
units
selection_policy
resource_group_id nullable
fixed_resource_id nullable
constraints limited/typed
```

Selection policy inicial:

```text
any
customer_selectable
fixed
```

Constraints deben ser limitados y tipados. No arbitrary SQL/JavaScript/DSL.

Ejemplos razonables:

```text
specific resource preference
capability
location compatibility
resource group
simple attribute equality
service-area compatibility
```

---

## 23. Allocation y assignment

`ResourceAllocation` representa capacidad comprometida por una Reservation.

Conceptualmente:

```text
reservation_id
requirement_id
resource_id or pool_resource_id
units
planned_from/planned_to when applicable
status
snapshot
```

Preservar conceptualmente:

```text
Allocation = committed capacity
Assignment = concrete execution resource
```

En barbería ambos pueden ocurrir simultáneamente. En field service una Reservation puede reservar pool capacity y asignar persona/vehículo más tarde.

La implementación inicial puede representar assignment mediante allocations especializadas/statuses sin introducir una entidad adicional hasta que el dominio lo exija.

---

## 24. ResourceGroup vs pool

```text
ResourceGroup
= grouping/filtering/discovery

Resource(kind=pool)
= reservable aggregate capacity
```

No son equivalentes.

Pool permite late binding seguro de capacidad agregada.

---

## 25. Availability matching

El scheduler debe resolver:

```text
Offering
    ↓
ResourceRequirement[]
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

Objetivo: garantizar capacidad válida, no optimización global.

No implementar inicialmente route optimization, labor-cost optimizer, skill scoring complejo o workforce scheduling global.

---

## 26. Schedules: dos significados distintos

### `BusinessHours`

Cuándo una organization/Location está normalmente abierta/presentable al público.

### `AvailabilitySchedule`

Cuándo un Offering/Resource/pool puede ser reservado.

Pueden diferir.

```text
Office BusinessHours: Mon–Fri 09:00–17:00
Emergency Offering AvailabilitySchedule: 24/7
```

---

## 27. Schedule representation

Schedule recurrente con timezone IANA y múltiples intervals por weekday.

Conceptualmente:

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

Un día cerrado simplemente no tiene intervalos efectivos.

Soportar:

```text
Mon–Fri 09:00–18:00
Saturday 09:00–12:00
Sunday closed
```

así como split shifts.

---

## 28. Schedule hierarchy

Scopes potenciales:

```text
Organization
Location
Offering
Resource / Pool
```

Effective availability se calcula por composición/intersección de restricciones aplicables, luego exceptions y capacidad ya comprometida.

> Un child schedule puede restringir un parent scope, pero no abrir silenciosamente un parent cerrado.

Apertura extraordinaria debe ser explícita en el scope apropiado.

---

## 29. `ScheduleException`

Tipos iniciales:

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

No diseñar un rules engine universal para excepciones.

---

## 30. `HolidayCalendar`

```text
HolidayCalendar
HolidayDate
HolidayPolicy/reference
```

No hardcodear “feriado = cerrado”.

Policies pueden resolver:

```text
closed_by_default
normal_schedule
special_hours
```

Permitir calendars oficiales importados/configurados y custom dates del negocio.

La fuente/actualización de calendarios externos puede ser integración; el estado efectivo aplicado debe ser auditable.

---

## 31. Location model

`Location` representa lugar operativo de la organización.

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

No hacer `google_place_id` ni coordenadas la identidad primaria de Location.

---

## 32. Location information for humans

La API debe exponer una vista útil para productos/agents:

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

Raw lat/lon son opcionales para interoperabilidad. La representación humana compartible (por ejemplo Google Maps URL/pin) es first-class desde la perspectiva de producto.

---

## 33. `LocationMedia`

PostgreSQL conserva metadata/references; blobs viven en object/media storage.

Conceptualmente:

```text
id
location_id
media_type
purpose
asset_url / asset_reference
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

No servir video/blob pesado directamente desde la DB.

---

## 34. `Destination`

Destination pertenece al trabajo concreto, no al catálogo de Locations.

Conceptualmente snapshot-based:

```text
id / embedded snapshot according to aggregate decision
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

La decisión table vs owned value object debe tomarse según reutilización real; semánticamente es distinta de `Location`.

---

## 35. `ServiceArea`

Validación inicial simple:

```text
named_zone
city/province
postal_code
radius
```

Puede asociarse a organization, Location, Offering o Resource/pool cuando exista necesidad concreta.

No empezar con polygons/routing-time solver. PostgreSQL/PostGIS puede evaluarse mediante ADR si los casos reales lo requieren.

---

## 36. Dispatch module

`Dispatch` modela movimiento/coordinación de capacidad asignada hacia Destination para field service.

Conceptualmente:

```text
id
public_id
organization_id
request_id nullable
reservation_id
status
destination_snapshot
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

Estados iniciales:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

Resource assignments/allocations se relacionan al Dispatch o Reservation según responsibility final del modelo.

---

## 37. Dispatch tracking boundary

Guardar **estado operacional útil**, no raw telemetry history.

Permitido/útil:

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

Si existe tracking continuo:

```text
GPS/mobile provider
    ↓
telemetry/tracking system
    ↓
current operational projection/event
    ↓
Request Engine
```

No loggear coordenadas innecesarias ni exponerlas públicamente sin policy/scopes apropiados.

---

## 38. Dispatch events and customer updates

Eventos:

```text
dispatch.assigned
dispatch.en_route
dispatch.eta_updated
dispatch.arrived
```

Adapters pueden convertirlos en:

```text
WhatsApp/SMS update
voice response
client portal tracker
push notification
webhook
```

El domain event expresa el hecho; no decide el canal/presentación.

---

## 39. Delivery boundary

No generalizar `Dispatch` inmediatamente a e-commerce logistics.

V2:

```text
Dispatch = operational resource movement for service execution
```

Un futuro `Delivery` puede reutilizar Destination, windows, tracking refs y events, pero shipment/packages/courier/proof-of-delivery sólo entran cuando exista un caso real.

---

## 40. Reservation concurrency

Confirmación revalida dentro de la transacción:

1. tenant;
2. Offering/policy activos;
3. effective schedule válido;
4. holiday/exception resolution;
5. Location/Destination/service-area compatibility;
6. ResourceRequirements satisfechos;
7. hold válido cuando requerido;
8. no overlaps para exclusive resources;
9. remaining units para capacity resources/pools;
10. payment gate satisfecho cuando la policy lo exige;
11. idempotency key coherente;
12. snapshots persistidos;
13. outbox/event en mismo commit.

Usar PostgreSQL constraints/ranges/locking donde simplifiquen garantías.

La comprobación de payment gate usa estado interno ya reconciliado; **no llama al PSP/banco dentro de esta transacción**.

---

## 41. Payments: arquitectura provider-agnostic y verificable

Payments es un módulo de coordinación financiera para workflows, **no accounting, PSP ni card vault**.

Separación:

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
```

### 41.1 `PaymentPolicy`

Configuration reusable asociada al Offering/workflow/organization según el caso.

Conceptualmente:

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

Modes iniciales:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Capacity strategies iniciales:

```text
hold_until_payment
revalidate_after_payment
confirm_then_collect
```

Policy version/snapshot relevante debe persistirse cuando una operación la consume.

### 41.2 `Money`

Value object obligatorio para toda cantidad:

```text
amount
currency
```

Nunca float binario.

Persistencia debe ser exacta. La representación concreta (`amount_minor BIGINT` + currency ISO o `NUMERIC` + currency) debe fijarse una vez mediante ADR/implementation convention y ser uniforme en todo el módulo.

No FX implícito. Distinta currency requiere policy/conversion explícita.

### 41.3 `PaymentRequirement`

Obligación concreta.

Campos conceptuales:

```text
id
public_id
organization_id
request_id nullable
reservation_id nullable
purpose
amount
currency
status
due_at nullable
policy_snapshot
created_at
updated_at
satisfied_at nullable
metadata
```

Estados:

```text
open
partially_satisfied
satisfied
waived
cancelled
```

`overdue` derivado de `due_at`.

La cantidad satisfied debe derivarse de allocations válidas, no de un boolean mutable aislado.

### 41.4 `PaymentMethodConfiguration`

Configuración tenant-scoped de métodos aceptados.

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

`method_family` no es provider. Stripe/Azul/PayPal/Bank API/manual son adapters/configurations.

Sensitive provider configuration no se almacena como JSON público; references a secrets/config segura.

### 41.5 `PaymentProviderConnection`

Representa conexión/configuración operacional hacia PSP/banco/external payment system.

Conceptualmente:

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

No guardar secretos legibles en rows/API responses.

Providers implementan adapters; el dominio no hace switches por marca.

### 41.6 Adapter contract

Contrato conceptual, no necesariamente una sola interfaz gigante:

```text
create_attempt / create_session
get_customer_action
query_status
handle_webhook
cancel_or_void
refund
fetch_or_receive_transactions [when supported]
```

Un adapter sólo traduce provider semantics a commands/events internos. No decide business policy.

### 41.7 `PaymentAttempt`

Un intento de satisfacer un Requirement.

```text
id
public_id
organization_id
payment_requirement_id
payment_method_configuration_id
status
provider_connection_id nullable
external_attempt_id nullable
instruction_snapshot nullable
created_at
expires_at nullable
completed_at nullable
metadata
```

Estados conceptuales:

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

`Attempt.succeeded` significa que el intento produjo/identificó un resultado financiero válido según el adapter/reconciliation; satisfaction final del Requirement sigue derivándose de Transactions + Allocations.

### 41.8 `PaymentInstruction`

Puede modelarse como owned snapshot/versioned payload del Attempt o entidad separada si reutilización/lifecycle lo exige.

Debe tener contratos discriminados, no JSON indefinido:

```text
BankTransferInstruction
RedirectInstruction
QrInstruction
CashInstruction
ExternalInstruction
```

Bank transfer snapshot puede contener:

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

Datos sensibles no necesarios para presentación no se exponen.

Cambio futuro de cuenta bancaria no altera instrucciones históricas.

### 41.9 `PaymentEvidence`

Evidencia customer-supplied.

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

Nunca puede, por sí sola, crear `PaymentTransaction.settled` ni satisfacer Requirement.

Blobs en private object storage, no DB/public bucket. File hash sirve como señal de duplicate/reuse, no sentencia automática de fraude.

### 41.10 `PaymentTransaction`

Representa movimiento financiero autoritativamente observado/confirmado.

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

Estados financieros conceptuales:

```text
pending
authorized
settled
failed
reversed
```

`authorized` y `settled` son distintos. Default: sólo `settled` puede satisfacer requirements salvo policy futura explícita que acepte authorization como gate.

No borrar transacciones tras reversal/refund/dispute. Registrar el hecho posterior.

Unique/idempotency constraints deben impedir duplicar el mismo external transaction/webhook dentro del mismo provider/tenant.

### 41.11 Bank transfer reconciliation

#### Con bank integration

```text
bank feed/webhook/API
      ↓
validated external event
      ↓
RecordBankTransaction
      ↓
PaymentTransaction
      ↓
match/reconciliation
      ↓
PaymentAllocation
```

#### Sin bank integration

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

Manual verification debe capturar:

```text
principal
verified_at
receiving account/config reference
bank/external reference when available
amount/currency
reason/note when needed
```

No existe command “accept screenshot as payment”.

### 41.12 `PaymentAllocation`

Join/ledger-like application table entre dinero observado y requirement, sin convertirse en accounting ledger general.

```text
id
organization_id
payment_transaction_id
payment_requirement_id
amount
currency
status
created_at
created_by / source
reversed_at nullable
metadata
```

Debe garantizar:

- currency compatible o conversion explícita;
- suma de allocations activas no excede monto aplicable de Transaction salvo modelo documentado;
- satisfaction del Requirement deriva de suma de allocations válidas;
- allocation es idempotente/reconcilable;
- reversal/refund puede requerir ajuste/reversal de allocation sin borrar historia.

Soporta partial payments, multiple transactions, one transaction across requirements y overpayment/unallocated funds.

### 41.13 `ReconciliationCase`

Entidad/aggregate operacional cuando no existe matching seguro.

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

Reasons iniciales:

```text
missing_reference
ambiguous_match
unknown_attempt
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
```

No auto-asignar si el matching es ambiguo.

### 41.14 Pago tardío versus Reservation

Caso:

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

`revalidate_after_payment` puede volver a ejecutar availability/capacity selection.

Nunca confirmar el slot viejo sin revalidar.

### 41.15 Cash

Cash usa el mismo modelo financiero:

```text
PaymentAttempt(method_family=cash)
      ↓
authorized principal receives cash
      ↓
RecordCashReceived
      ↓
PaymentTransaction(source=cash_verification)
      ↓
PaymentAllocation
```

No crear special boolean `cash_paid` fuera del modelo.

### 41.16 Provider redirects y webhooks

Una success/cancel URL de browser es UX, no autoridad.

Authority:

```text
signed provider webhook
server-to-server provider API
bank API/feed
manual independent verification
```

Webhook handling:

1. authenticate/signature validation;
2. anti-replay/provider event dedupe;
3. normalize to internal command;
4. idempotent transaction;
5. event/outbox;
6. acknowledge provider.

Nunca ejecutar business mutation autoritativa sólo porque el browser afirma `success=true`.

### 41.17 Refund

Refund lifecycle separado:

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

Partial refund permitido.

Void/cancel de autorización no capturada no es Refund.

Refund/reversal debe reconciliar impacto sobre PaymentAllocations/Requirements según policy, sin borrar historia.

### 41.18 Provider-independent state mapping

Cada adapter mantiene mapping explícito desde provider states a estados canónicos.

No permitir que provider-specific states aparezcan como condición de workflow en domain code:

```text
if stripe_status == ...  # no
```

Workflow consulta:

```text
PaymentAttempt.status
PaymentTransaction.status
PaymentRequirement.status
```

Raw provider payloads pueden conservarse sólo cuando sean necesarios para audit/debug y con retention/security apropiados; no deben ser la fuente primaria de queries de negocio.

### 41.19 Idempotency y duplicates

Idempotency es crítica para:

```text
CreatePaymentRequirement
CreatePaymentAttempt
provider webhooks
bank transaction ingestion
manual verification
PaymentAllocation
refund creation/callbacks
```

Same idempotency key + materially different payload = explicit conflict.

Provider event ID / external transaction ID debe deduplicarse bajo provider + tenant scope cuando sea estable.

### 41.20 Payment evidence/storage security

- PAN/CVV nunca en Request Engine;
- provider token/reference en su lugar;
- bank/PSP secrets en secret manager/config segura;
- PaymentEvidence privado;
- signed short-lived URLs para acceso cuando corresponda;
- audit de acceso/verification sensible;
- scopes separados `payments.read`, `payments.create`, `payments.verify`, `payments.refund`, `payments.reconcile` según surface;
- no PII financiera completa en logs;
- agent tools no exponen datos bancarios internos innecesarios;
- instrucciones públicas exponen sólo lo necesario para ejecutar el método.

---

## 42. Forms / public intake

`FormDefinition` + `FormSubmission` inicialmente.

Schemas reutilizables por website, agent, human UI y API.

No construir form-builder universal inicialmente.

---

## 43. Agent boundary

Tools goal-oriented:

```text
search_offerings
get_business_locations
get_location_details
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

El modelo no recibe access a tables, resource graph internals, raw telemetry, PSP internals, bank feeds ni arbitrary writes.

En particular, no se expone al modelo una tool genérica `mark_payment_paid`. Verification/refund/reconciliation requieren deterministic commands + scopes y, cuando corresponde, principal humano o trusted provider callback.

---

## 44. Integraciones

Chatwoot, LiveKit, WhatsApp, Twilio, n8n, maps providers, media storage, tracking providers, banks y PSPs son adapters.

n8n puede experimentar con integrations pero no controla request/reservation/payment state autoritativo.

Payment provider adapters traducen provider semantics; no contienen PaymentPolicy de negocio.

---

## 45. Security baseline

- secret keys hashed/stored securely;
- explicit scopes;
- expiry/revocation;
- public surface rate limits;
- signed webhooks + anti-replay;
- PII encryption when threat model requires;
- audit privileged changes;
- cross-tenant tests;
- location/tracking data scoped appropriately;
- public tracking tokens expose only minimum necessary data;
- no raw secrets/PII/GPS trails in logs;
- PAN/CVV never stored;
- PaymentEvidence private;
- bank/PSP credentials never exposed to browser/agents;
- manual payment verification requires privileged principal;
- refunds/reconciliation have distinct scopes from normal payment initiation.

---

## 46. Observabilidad

Mínimo:

- structured logs;
- correlation IDs;
- metrics;
- health/readiness;
- DB pool metrics;
- outbox lag;
- hold expiry;
- reservation conflict classifications;
- queue wait metrics;
- dispatch state/ETA update failures;
- external provider error classification;
- payment webhook validation/dedupe failures;
- payment reconciliation queue depth/age;
- payment verification latency;
- unallocated funds count/amount metrics without leaking PII;
- refund failures;
- sanitized context.

Telemetry técnica no sustituye domain events/audit.

---

## 47. Testing strategy

### Unit

- workflow decisions;
- Request transitions;
- Offering policy resolution;
- schedule composition;
- exception precedence;
- holiday policies;
- admission policies;
- queue priority;
- ResourceRequirement matching;
- service-area validation;
- Dispatch transitions;
- PaymentPolicy resolution;
- PaymentRequirement state derivation;
- PaymentAttempt transitions;
- PaymentAllocation math;
- partial/overpayment behavior;
- late-payment capacity strategy;
- refund lifecycle.

### PostgreSQL integration

- constraints;
- idempotency;
- reservation races;
- exclusive overlap prevention;
- capacity-units oversell prevention;
- hold expiry/confirmation races;
- schedule/exception edge cases;
- cross-tenant isolation;
- pool allocations/late assignment;
- outbox claiming/retry;
- duplicate provider webhook ingestion;
- duplicate bank transaction ingestion;
- concurrent PaymentAllocations cannot overspend transaction;
- concurrent allocations cannot incorrectly oversatisfy requirement;
- manual verification audit/scopes;
- payment arrives after CapacityHold expiry;
- refund/allocation reconciliation.

### Contract

- REST/OpenAPI;
- agent schemas;
- webhook signatures;
- provider adapter normalization contracts;
- public location/tracking projections;
- payment instruction discriminated schemas;
- backwards compatibility where relevant.

### End-to-end

Demo Barbershop + Demo Plumbing vertical slices are mandatory.

Payments E2E must include at least:

```text
card/provider success path
cash/manual verification path
bank-transfer instructions + evidence + independent verification
bank transfer not found / verification_failed
partial payment or allocation proof
late payment after hold expiry
refund proof
```

---

## 48. Performance philosophy

Primero integridad/observabilidad, luego optimización medida.

Evitar:

- N+1 por slot/resource;
- cargar historial completo para overlap;
- writes por availability read;
- recalcular colas completas innecesariamente;
- almacenar raw GPS stream;
- consultar remote routing/maps dentro de reservation transaction;
- consultar PSP/bank synchronously dentro de reservation/payment allocation transaction cuando un callback/projection es suficiente;
- full scans para matching de bank transactions;
- JSONB para relaciones centrales;
- guardar full provider payloads indefinidamente sin necesidad.

Usar set-based SQL, indices y constraints.

---

## 49. Deployment inicial

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

Media blobs, PaymentEvidence y tracking telemetry usan storage/sistemas especializados; Request Engine conserva references/projections relevantes.

PSP/bank callbacks entran por endpoints/adapters dedicados y ejecutan application commands idempotentes.

---

## 50. Definition of Done de foundation

```text
[ ] Python/FastAPI bootstrapped
[ ] PostgreSQL migrations reproducibles
[ ] organizations/principals tenancy
[ ] contacts
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
[ ] ResourceGroups/pool proof
[ ] availability for scheduled/window/queue/hybrid
[ ] ReservationOption contract
[ ] CapacityHolds + expiry
[ ] Reservations + concurrency protection
[ ] ResourceAllocations + late assignment proof
[ ] AdmissionPolicies
[ ] CheckIn
[ ] QueueEntries
[ ] ServiceSessions
[ ] Destination snapshot
[ ] ServiceArea validation
[ ] Dispatch lifecycle
[ ] dispatch status/ETA/tracking-reference projection

[ ] PaymentPolicy
[ ] exact Money representation convention
[ ] PaymentMethodConfiguration
[ ] PaymentProviderConnection/adapter boundary
[ ] PaymentRequirement
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
[ ] Refund lifecycle
[ ] provider webhook signature + dedupe + idempotency proof
[ ] payment privileged scopes

[ ] Fulfillment linked to Request/Reservation
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

La foundation se considera conceptualmente madura cuando estos elementos demuestran que capacity y money pueden coordinarse sin convertir Request Engine en scheduler universal, PSP o ERP.

---

## 51. Regla arquitectónica final

Para intención:

```text
Offering      = what can be obtained
Request       = what is wanted now
Workflow      = what must happen
```

Para capacidad:

```text
Resource      = what can provide capacity
Capacity      = how much it can provide
Requirement   = what capacity an Offering needs
Allocation    = what capacity a Reservation committed
Assignment    = which concrete Resource executes
Schedule      = when capacity may exist
Reservation   = committed capacity
Admission     = how access to service occurs
```

Para lugar/ejecución:

```text
Location       = where the organization operates/receives
Destination    = where this specific work must occur
Dispatch       = movement/coordination toward Destination
ServiceSession = actual execution
Fulfillment    = verified outcome
```

Para pagos:

```text
PaymentPolicy      = how/when payment is required
PaymentRequirement = concrete money obligation
PaymentAttempt     = one method-specific attempt
PaymentInstruction = what the payer was told to do
PaymentEvidence    = supporting evidence, never money by itself
PaymentTransaction = authoritative observed financial movement
PaymentAllocation  = how verified money satisfies requirements
ReconciliationCase = ambiguity requiring explicit resolution
Refund             = explicit return-of-funds lifecycle
```

Request Engine debe saber **qué necesita ocurrir, si puede ocurrir válidamente, qué capacidad fue comprometida, qué obligación financiera existe, qué dinero fue realmente verificado/aplicado y cuál fue el resultado**. No debe convertirse en todos los sistemas especializados que participan alrededor de ese proceso.
