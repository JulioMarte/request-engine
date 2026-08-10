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

No es CRM, ERP, PBX, calendario tradicional, GPS telemetry store, shipping platform ni framework universal de agentes.

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
- payment coordination;
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

Campos de identidad, relaciones, lifecycle, constraints, scheduling y reporting operacional deben ser columnas/tables tipadas.

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
ful_...
evt_...
```

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
CompleteRequest
```

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
```

Queries no producen side effects. `SearchAvailability` no crea holds/reservations.

---

## 10. Transacciones

```text
BEGIN
  validate current state
  resolve authoritative policy
  lock/revalidate capacity where needed
  mutate internal state
  insert domain event/outbox
COMMIT
```

Nunca mantener transacción abierta mientras se llama payment provider, maps/routing provider, WhatsApp, LiveKit, n8n u otro sistema remoto.

---

## 11. Outbox

PostgreSQL transactional outbox inicialmente.

Worker con claiming seguro (`FOR UPDATE SKIP LOCKED` u otra estrategia justificada), retry/backoff, dead-letter/failure state, idempotent delivery y event versioning.

Queue externa sólo por necesidad medida.

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
request.fulfilled
```

Audit responde quién hizo qué y por qué. Logs son diagnóstico técnico. No confundirlos.

---

## 13. Correlation y causality

Propagar cuando corresponda:

```text
request_id
reservation_id
dispatch_id
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
 → dispatch/payment/tool action
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
wait_confirmation
wait_payment
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

Ejemplo:

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

Regla de seguridad semántica:

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
10. idempotency key coherente;
11. snapshots persistidos;
12. outbox/event en mismo commit.

Usar PostgreSQL constraints/ranges/locking donde simplifiquen garantías.

---

## 41. Payment coordination

Payments sigue siendo módulo de coordinación, no accounting.

Policies conceptuales:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Nunca esperar PSP dentro de una DB transaction.

El modelo definitivo de `PaymentRequirement`, payment session/intent y payment record queda explícitamente pendiente de la siguiente sesión de dominio antes de cerrar foundation.

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
cancel_reservation
reschedule_reservation
```

El modelo no recibe access a tables, resource graph internals, raw telemetry ni arbitrary writes.

---

## 44. Integraciones

Chatwoot, LiveKit, WhatsApp, Twilio, n8n, maps providers, media storage, tracking providers y PSPs son adapters.

n8n puede experimentar con integrations pero no controla request/reservation state autoritativo.

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
- no raw secrets/PII/GPS trails in logs.

---

## 46. Observability

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
- Dispatch transitions.

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
- outbox claiming/retry.

### Contract

- REST/OpenAPI;
- agent schemas;
- webhook signatures;
- public location/tracking projections;
- backwards compatibility where relevant.

### End-to-end

Demo Barbershop + Demo Plumbing vertical slices are mandatory.

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
- JSONB para relaciones centrales.

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

Media blobs y tracking telemetry, cuando existan, usan sistemas especializados externos; Request Engine conserva references/projections relevantes.

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
[ ] payment policy + provider adapter proof
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

Payments domain remains the last major model to mature before freezing this foundation.

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
Location      = where the organization operates/receives
Destination   = where this specific work must occur
Dispatch      = movement/coordination toward Destination
ServiceSession = actual execution
Fulfillment   = verified outcome
```

Request Engine debe saber **qué necesita ocurrir, si puede ocurrir válidamente, qué capacidad fue comprometida y cuál fue el resultado**. No debe convertirse en todos los sistemas especializados que participan alrededor de ese proceso.
