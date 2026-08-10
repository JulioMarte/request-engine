# Request Engine V2 — arquitectura de referencia

> **Estado:** arquitectura objetivo para la reimplementación de Request Engine.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> Este documento traduce la esencia del producto a decisiones técnicas. Si una decisión técnica entra en conflicto con la definición del producto, **gana la definición del producto**.

---

## 1. Punto de partida

La arquitectura existe para servir esta idea:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Request Engine es un **motor headless, multiempresa, API-first y transaccional de orquestación de solicitudes**.

Su trabajo es:

1. recibir o normalizar una intención;
2. convertirla en un `Request` estructurado;
3. resolver un `Offering` y políticas aplicables cuando corresponda;
4. determinar un workflow válido y versionado;
5. ejecutar capabilities deterministas;
6. persistir estado y decisiones importantes;
7. coordinar capacity holds, reservations, payments, callbacks, confirmaciones o intervención humana;
8. producir un `Fulfillment` verificable;
9. mantener trazabilidad completa.

No es un chatbot, CRM, ERP, PBX, plataforma de WhatsApp, calendario tradicional ni framework universal de agentes. Es la capa de negocio que esos sistemas consumen.

---

## 2. Decisiones de arquitectura adoptadas

### Source of truth: PostgreSQL

PostgreSQL será la fuente de verdad transaccional de Request Engine V2.

El dominio es crecientemente relacional y transaccional:

- organizations y tenancy;
- contacts;
- offerings;
- request types;
- requests y lifecycle;
- workflow runs;
- resources;
- resource requirements;
- availability;
- capacity holds;
- reservations;
- check-ins;
- queue entries;
- service sessions;
- idempotency;
- audit;
- domain events;
- reporting operacional.

PostgreSQL permite expresar invariantes mediante constraints, índices, transacciones, locking explícito, queries temporales, range types, JSONB disciplinado y capacidades avanzadas de SQL.

No se adopta PostgreSQL porque Convex haya sido un error. Convex fue útil para descubrir el dominio. V2 optimiza ahora alrededor de integridad, relaciones, consultas y control transaccional.

### Lenguaje del backend: Python

El backend de V2 se implementará en Python.

Python se elige por el buen fit con:

- API transaccional;
- workflow orchestration;
- background workers;
- integrations;
- AI-assisted classification/extraction;
- agent tooling;
- document/data processing.

La elección no autoriza a mezclar IA con reglas críticas del dominio. Las mutaciones autoritativas permanecen tipadas, validadas y deterministas.

### API framework: FastAPI

FastAPI será la capa HTTP inicial.

Motivos:

- Pydantic para contratos y validación;
- OpenAPI generado desde implementación real;
- async I/O;
- dependency injection suficiente;
- buen fit para SDKs generados y adapters de agentes.

FastAPI es **transporte**, no dominio.

### Persistencia: SQLAlchemy + Alembic

SQLAlchemy será la abstracción principal de persistencia y Alembic administrará migraciones.

Se prefiere SQLAlchemy para conservar acceso a:

- queries complejas;
- PostgreSQL-specific types;
- locking;
- exclusion constraints;
- índices parciales;
- reporting;
- tuning.

Pydantic representa contratos/API. SQLAlchemy representa persistencia.

---

## 3. Principio estructural: modular monolith

V2 comienza como un **modular monolith**, no como microservicios.

```text
request-engine
│
├── API
│
├── Core
│   ├── organizations
│   ├── principals
│   ├── contacts
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
│   ├── forms
│   └── payments
│
├── Infrastructure
│   ├── postgres
│   ├── webhooks
│   ├── integrations
│   └── observability
│
└── Workers
```

Los boundaries son primero de dominio y código.

Un módulo se convierte en servicio independiente sólo ante una razón concreta:

- scaling diferente;
- failure isolation;
- ownership independiente;
- deployment cadence diferente;
- requirements de seguridad o infraestructura distintos.

“Podría ser un microservicio” no es razón suficiente.

---

## 4. Estructura propuesta del repositorio

```text
request-engine/
│
├── src/
│   └── request_engine/
│       │
│       ├── api/
│       │   ├── routes/
│       │   ├── dependencies/
│       │   ├── middleware/
│       │   └── errors.py
│       │
│       ├── domain/
│       │   ├── organizations/
│       │   ├── principals/
│       │   ├── contacts/
│       │   ├── offerings/
│       │   ├── requests/
│       │   ├── workflows/
│       │   ├── fulfillments/
│       │   ├── reservations/
│       │   ├── forms/
│       │   └── payments/
│       │
│       ├── application/
│       │   ├── commands/
│       │   ├── queries/
│       │   └── services/
│       │
│       ├── infrastructure/
│       │   ├── postgres/
│       │   ├── webhooks/
│       │   ├── integrations/
│       │   └── observability/
│       │
│       └── workers/
│
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
│
├── docs/
├── pyproject.toml
└── README.md
```

Guía, no religión. No crear capas vacías sólo para satisfacer el diagrama.

---

## 5. Regla de dependencia

Dirección deseada:

```text
API / Worker / Integrations / Agent adapters
                  ↓
           Application layer
                  ↓
              Domain rules
                  ↓
        Infrastructure adapters
```

- routes HTTP traducen requests externos a commands/queries;
- agent adapters traducen tools/MCP a commands/queries;
- application services coordinan casos de uso;
- domain code expresa invariantes y state transitions;
- repositories/adapters resuelven persistencia y sistemas externos;
- workers consumen outbox/jobs y llaman application services.

Evitar:

1. fat routes;
2. fat MCP tools;
3. Clean Architecture ceremonial con interfaces sin valor.

---

## 6. Contratos: Pydantic → OpenAPI → SDK / Agent schemas

V2 no mantiene OpenAPI manualmente separado.

```text
Pydantic request/response schemas
              ↓
           FastAPI
              ↓
            OpenAPI
              ↓
      generated client SDKs
```

La superficie para agentes no necesita ser 1:1 con REST.

```text
Application commands/queries
        │
        ├── REST endpoints
        ├── public/widget endpoints
        └── MCP / agent tools
```

Todos ejecutan las mismas invariantes autoritativas.

REST favorece composición de software. Agent tools favorecen objetivos de negocio, schemas pequeños y scopes mínimos.

---

## 7. PostgreSQL: relacional primero, JSONB con disciplina

No convertir PostgreSQL en document store accidental.

Campos usados en identidad, relaciones, lifecycle, búsqueda, constraints o reporting son columnas tipadas.

Ejemplo conceptual de `requests`:

```text
id
public_id
organization_id
contact_id
request_type_id
offering_id nullable
status
workflow_key
workflow_version
current_step
input_data JSONB
output_data JSONB
metadata JSONB
created_at
updated_at
completed_at
```

Ejemplo conceptual de `reservations`:

```text
id
public_id
organization_id
request_id nullable
status
admission_policy_id
planned_start nullable
planned_end nullable
window_start nullable
window_end nullable
commercial_snapshot JSONB
metadata JSONB
created_at
updated_at
```

La existencia exacta de columnas depende del modelo final. La regla es que JSONB no sustituye foreign keys, estados fundamentales ni campos regularmente consultados.

---

## 8. `Offering`: fachada estable + especialización por composición

`Offering` es identidad de lo que una organización ofrece.

No crear árboles de herencia o tablas paralelas incompatibles para `Product`, `Service`, `Package`, etc. como fachada pública principal.

Conceptualmente:

```text
Offering
├── common identity
├── kind
├── pricing configuration/reference
├── intake configuration/reference
├── reservation configuration/reference
├── payment policy/reference
└── module extensions
```

Los datos que requieren invariantes, joins o consultas frecuentes deben modelarse relacionalmente. La composición no implica guardar toda la semántica en un JSON arbitrario.

`kind` sirve como clasificación útil, no como switch gigante en toda la aplicación.

---

## 9. `RequestType` y resolución de workflow

Los RequestTypes son relativamente genéricos:

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

La resolución conceptual es:

```text
RequestType
    +
Offering
    +
Organization policy
    +
Request context
    ↓
workflow_key + workflow_version
```

No crear `book_haircut`, `book_beard_trim`, `book_cleaning` como tipos universales sólo porque existen Offerings diferentes.

Un Offering puede seleccionar/configurar un workflow especializado cuando su comportamiento realmente lo exige.

---

## 10. Multi-tenancy

Toda operación tenant-owned ejecuta dentro de organización resuelta desde credencial/principal.

```text
credential
    ↓
authenticate
    ↓
resolve principal + organization + scopes
    ↓
application command/query
```

Reglas:

- `organization_id` en entidades tenant-owned relevantes;
- FKs y unique constraints incluyen tenant scope cuando corresponde;
- no aceptar ciegamente tenant enviado por browser;
- public/browser credentials y secret/server credentials son clases distintas;
- tests de cross-tenant leakage obligatorios.

PostgreSQL RLS puede evaluarse como defensa adicional mediante ADR; no sustituye authorization correcto en application code.

---

## 11. IDs

Distinción:

```text
internal primary key → database concern
public_id            → API/domain reference
external_id          → integration mapping
```

Ejemplos:

```text
org_...
cnt_...
off_...
req_...
res_...
ful_...
evt_...
```

No usar IDs de Chatwoot, Twilio, LiveKit, Stripe, Evolution u otros providers como identidad primaria.

---

## 12. Commands y Queries

Separar reads de operaciones que cambian estado, sin CQRS distribuido.

### Commands

Ejemplos:

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
StartServiceSession
CompleteServiceSession
CompleteRequest
```

Commands:

- validan authorization;
- ejecutan invariantes;
- participan en una transacción;
- pueden producir domain events;
- soportan idempotencia cuando retries son posibles.

### Queries

```text
GetRequest
ListOpenRequests
ListOfferings
SearchAvailability
GetReservation
ListReservations
GetQueueState
```

Queries no producen side effects de negocio.

En particular, `SearchAvailability` no crea holds ni reservations.

---

## 13. Transacciones

Transacciones cortas con trabajo autoritativo interno.

Correcto:

```text
BEGIN
  validate current state
  lock/revalidate capacity
  mutate domain state
  insert domain event/outbox record
COMMIT
```

Incorrecto:

```text
BEGIN
  mutate
  call payment provider
  call WhatsApp
  call LiveKit
  call n8n
  wait for remote provider
COMMIT
```

Ningún sistema remoto mantiene abierta una transacción de negocio.

---

## 14. Outbox: PostgreSQL primero

V2 usa transactional outbox.

Inicialmente no se requiere Kafka, RabbitMQ ni plataforma distribuida de eventos.

```text
domain state
+
outbox event
```

mismo commit.

Worker conceptual:

```sql
SELECT ...
FROM outbox_events
WHERE status = 'pending'
  AND available_at <= now()
ORDER BY available_at
FOR UPDATE SKIP LOCKED
LIMIT ...;
```

Debe soportar:

- ownership/leases cuando sea necesario;
- retries con backoff;
- dead-letter/failure state;
- idempotent delivery;
- observabilidad;
- event versioning.

Queue externa sólo cuando requisitos medidos lo exijan.

---

## 15. Domain events, audit y logs

### Domain events

Ejemplos:

```text
request.created
request.classified
request.ready
capacity_hold.created
capacity_hold.expired
reservation.confirmed
reservation.checked_in
reservation.enqueued
reservation.cancelled
service_session.started
service_session.completed
request.fulfilled
```

Alimentan webhooks, notifications, analytics, projections e integrations.

### Audit

Responde quién hizo qué y por qué:

```text
principal
operation
target
before/after or change summary
reason
correlation_id
occurred_at
```

### Logs

Diagnóstico técnico.

No mezclar los tres conceptos.

---

## 16. Correlation y causality

Toda operación importante rastreable mediante valores conceptuales:

```text
request_id
reservation_id
correlation_id
causation_id
principal_id
trace_id
```

Objetivo:

```text
conversation/input
      ↓
request
      ↓
workflow decision
      ↓
capability/tool call
      ↓
transaction
      ↓
domain event
      ↓
outbox
      ↓
external callback
```

Debe reconstruirse sin memoria humana, especialmente cuando agentes de IA son clientes.

---

## 17. Workflow engine: pequeño y explícito

No construir Temporal, BPMN o workflow designer universal como parte del MVP.

Workflows versionados como state machines/código tipado.

Un request puede persistir:

```text
workflow_key
workflow_version
workflow_state
current_step
status
next_action_at
```

Resultados:

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

Plataforma durable especializada se evalúa por ADR sólo si aparecen timers extensos, sagas multi-servicio, fan-out o workflows de días/semanas que lo justifiquen.

---

## 18. Reservations: módulo de capacidad, no calendario tradicional

El módulo canónico es `reservations`.

No usar `booking` como vocabulario de dominio o API.

Boundary conceptual:

```text
Request workflow
      ↓
reservations.search_availability
      ↓
reservations.create_hold        [cuando corresponde]
      ↓
payment/confirmation            [cuando corresponde]
      ↓
reservations.confirm
      ↓
admission/check-in/queue
      ↓
service session
      ↓
Fulfillment references Reservation
```

`Reservation` representa **compromiso de capacidad**, no necesariamente exact-time appointment.

---

## 19. Availability

Availability es lectura de capacidad potencial.

Debe soportar diferentes modelos operacionales:

- exact slots;
- arrival windows;
- queue capacity/estimated wait;
- hybrid capacity.

La respuesta de availability puede ser heterogénea según policy, pero debe exponerse mediante contratos tipados/discriminated unions, no JSON indefinido.

Ejemplo conceptual:

```text
ScheduledOption
WindowOption
QueueOption
HybridOption
```

`SearchAvailability` nunca garantiza commit futuro.

---

## 20. `CapacityHold`

`CapacityHold` es una reclamación temporal de capacidad durante una operación con intención real de continuar.

Casos:

- checkout;
- depósito;
- confirmación humana;
- coordinación multi-step corta.

Invariantes:

- expiración explícita;
- idempotencia;
- scope organizacional;
- referencia a capacidad/oferta relevante;
- no tratarlo como Reservation confirmada;
- proceso de expiración observable y seguro.

No crear holds por cada lectura de disponibilidad.

---

## 21. Admission policies

`AdmissionPolicy` describe cómo una reservation entra al servicio.

Modos iniciales:

```text
scheduled
queue
window
hybrid
```

Preferir estrategia/configuración tipada sobre subclases totalmente independientes que dupliquen identidad, tenancy, audit y lifecycle.

### scheduled

Puede configurar:

```text
check_in_required
early_check_in_window
grace_period
no_show_after
```

### queue

Puede configurar:

```text
ordering_strategy
priority_rules
remote_join_allowed
presence_confirmation
estimated_service_duration
```

No asumir FIFO absoluto. El motor debe poder implementar una política estable de `priority + ordering`.

### window

Puede representar:

```text
window_start
window_end
capacity
```

sin prometer un instante exacto.

### hybrid

Compone comportamiento scheduled + queue, por ejemplo:

```text
scheduled slot
+ grace period
+ late_behavior = enqueue
```

También soporta coexistencia controlada de scheduled reservations y walk-ins sobre recursos compartidos.

---

## 22. Check-in, queue y ejecución

Separar:

```text
Reservation = committed/planned capacity
CheckIn     = presence/readiness event/state
QueueEntry  = dynamic operational queue position/priority
ServiceSession = actual execution
```

No sobrescribir datos planificados con tiempos reales.

Ejemplo:

```text
Reservation:
planned 10:00–10:30

CheckIn:
10:07

ServiceSession:
10:14–10:52
```

`QueueEntry` referencia Reservation y mantiene datos operacionales dinámicos como queue, priority, join/check-in time y state.

En queue-only/walk-in, se crea una Reservation de compromiso queue-based y su correspondiente QueueEntry. Esto mantiene una vista uniforme de toda demanda comprometida.

---

## 23. Resources

Separar `ResourceRequirement` y `ResourceAllocation`.

```text
Offering
      ↓
ResourceRequirement[]
      ↓
availability/resource matching
      ↓
Reservation
      ↓
ResourceAllocation[]
```

Un resource puede representar, según el módulo:

```text
person
chair
room
vehicle
equipment
capacity pool
```

No introducir semántica vertical al core. Roles/capabilities determinan compatibilidad.

PostgreSQL puede usar range types, exclusion constraints, row locks o advisory locks cuando simplifiquen garantías de exclusión/capacidad y exista razón documentada.

---

## 24. Reservation concurrency e invariantes

La confirmación debe revalidar capacidad dentro de la transacción.

Invariantes mínimas:

1. tenant correcto;
2. hold válido si es requerido;
3. Offering/policy activos;
4. resources compatibles;
5. capacidad disponible;
6. no overlaps inválidos para recursos exclusivos;
7. capacidad agregada respetada para pools/windows/queues cuando corresponda;
8. idempotency key coherente;
9. snapshots comerciales/políticas persistidos;
10. event/outbox creado en el mismo commit.

No duplicar en Python una garantía que PostgreSQL puede imponer mejor mediante constraints.

---

## 25. Payment coordination

Payments es módulo de coordinación, no accounting.

Policies iniciales pueden representar:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Providers externos se implementan como adapters.

Flujo típico:

```text
CreateCapacityHold
      ↓
create external payment session
      ↓
commit internal pending state/outbox
      ↓
external payment
      ↓
signed callback
      ↓
idempotent application command
      ↓
ConfirmReservation
```

Nunca mantener una DB transaction abierta mientras se espera un PSP.

---

## 26. Forms / public intake

Primitivas iniciales:

```text
FormDefinition
FormSubmission
```

Schemas de intake deben poder reutilizarse por website, agent, human UI y API.

El submit puede:

```text
upsert contact
      ↓
create/provide request data
      ↓
emit event
      ↓
resume workflow
```

No construir inicialmente drag-and-drop builder avanzado, cientos de field types, theme engine ni conditional logic universal.

---

## 27. Agent boundary

Python facilita IA, pero incrementa riesgo de contaminación del core.

```text
AI interprets / proposes
        ↓
structured candidate
        ↓
Request Engine validates
        ↓
deterministic workflow/policy
        ↓
typed capability
        ↓
authoritative transaction
```

El modelo puede sugerir:

```text
intent = reserve_offering
offering = off_...
fields = {...}
```

No puede ejecutar writes arbitrarios.

Agent tools deben ser goal-oriented, tipadas y scoped. Ejemplos:

```text
search_offerings
find_reservation_options
prepare_reservation
confirm_reservation
cancel_reservation
reschedule_reservation
```

No exponer tablas o repositorios directamente a modelos.

---

## 28. Integraciones son adapters

Chatwoot, WhatsApp, LiveKit, Twilio, n8n y similares viven alrededor de Request Engine.

```text
Chatwoot event
     ↓
Chatwoot adapter
     ↓
Request Engine API
     ↓
Request/workflow
```

n8n puede orquestar integraciones externas y prototipos, pero no es workflow engine autoritativo.

LiveKit puede exponer voice agents, pero no es owner de request/reservation state.

Chatwoot puede guardar conversaciones, pero no es owner del trabajo estructurado.

---

## 29. Security baseline

Desde el principio:

- secret credentials nunca en frontend;
- API keys secretas almacenadas hashed;
- scopes explícitos;
- expiración/revocación;
- rate limits para superficies públicas;
- webhook signatures + anti-replay;
- encrypted secrets mediante secrets manager/environment seguro;
- PII sensible cifrada adicionalmente cuando threat model/regulación lo justifique;
- audit para operaciones privilegiadas;
- cross-tenant tests.

No diseñar seguridad alrededor de URLs difíciles de adivinar.

---

## 30. Observabilidad

Mínimo:

- structured logs;
- correlation IDs;
- metrics básicas;
- traces OpenTelemetry cuando aporten valor;
- health/readiness endpoints;
- DB pool metrics;
- outbox lag;
- capacity-hold expiry metrics;
- reservation conflict/error classification;
- queue wait/lag metrics cuando aplique;
- sanitized request context.

Nunca loggear secrets o PII completa.

---

## 31. Testing strategy

### Unit tests

- request transitions;
- workflow decisions;
- Offering policy resolution;
- admission policies;
- queue ordering/priority;
- temporal calculations;
- validation.

### Integration tests con PostgreSQL real

- transactions;
- constraints;
- idempotency;
- concurrency;
- capacity conflicts;
- exclusion constraints cuando se usen;
- hold expiry/confirmation races;
- cross-tenant isolation;
- queue/hybrid transitions;
- outbox claiming/retry.

SQLite no sustituye PostgreSQL para invariantes PostgreSQL-specific.

### Contract tests

- REST schemas;
- generated OpenAPI;
- agent tool schemas;
- webhook signatures;
- backwards compatibility relevante.

### End-to-end vertical slices

No se considera V2 viable hasta demostrar los vertical slices de `00-product-definition.md`.

---

## 32. Performance philosophy

Primero integridad y observabilidad; después optimización medida.

Evitar:

- cargar historial completo para detectar overlaps;
- N+1 por candidate slot;
- scans sin límites;
- JSONB para todo;
- synchronous remote calls dentro de transactions;
- generar registros persistentes por cada lectura de availability;
- recalcular colas completas innecesariamente si una estrategia incremental segura es posible.

Usar PostgreSQL para set-based queries y constraints cuando corresponda.

Caches sólo tras medir necesidad real.

---

## 33. Deployment inicial

Topología mínima:

```text
                  ┌─────────────┐
Clients ─────────►│ FastAPI API │
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │ PostgreSQL  │
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │   Worker    │
                  └──────┬──────┘
                         │
                 external systems
```

API y Worker usan misma codebase/dominio, con procesos separados.

No Redis obligatorio.
No RabbitMQ obligatorio.
No Kafka obligatorio.
No workflow platform obligatoria.

Se agregan cuando exista un requisito que PostgreSQL + worker no resuelva bien.

---

## 34. Definition of Done para la foundation

Antes de construir features verticales adicionales:

```text
[ ] Python/FastAPI service bootstrapped
[ ] PostgreSQL migrations reproducibles
[ ] organizations/principals tenancy
[ ] contacts
[ ] offerings
[ ] request_types
[ ] requests + lifecycle
[ ] versioned workflow interface
[ ] resource model
[ ] resource requirements
[ ] availability contracts for scheduled/window/queue/hybrid
[ ] capacity holds + expiry
[ ] reservations + concurrency protection
[ ] admission policies
[ ] check-in
[ ] queue entries
[ ] service sessions
[ ] payment policy + provider adapter proof
[ ] fulfillment linked to request/reservation
[ ] domain events
[ ] transactional outbox
[ ] worker retry/idempotency
[ ] audit trail
[ ] secret + public credential model
[ ] OpenAPI generated from real schemas
[ ] TypeScript SDK generation proof
[ ] agent/MCP tool adapter proof
[ ] structured logs/correlation IDs
[ ] integration tests using PostgreSQL
[ ] Demo Barbershop vertical slice
[ ] Demo Plumbing vertical slice
```

Hasta entonces, insurance, advanced CRM, omnichannel provisioning, generic workflow builder o AI runtime no compiten por prioridad.

---

## 35. Regla arquitectónica final

Ante una nueva feature:

```text
Does it help represent what can be obtained (Offering)?
          │
          ├─ no ─┐
          ▼ yes  │
Does it help represent/process an intention (Request)?
          │      │
          ├─ no ─┤
          ▼ yes  │
Does it help determine/execute the workflow?
          │      │
          ├─ no ─┤
          ▼ yes  │
Does it require authoritative Request Engine state?
          │      │
          ├─ no ─┴─► likely edge/integration
          ▼ yes
Core, module, or integration?
```

Para capacidad:

```text
Availability = what could be used
CapacityHold = what is temporarily claimed
Reservation  = what capacity is committed
Admission    = how access to service occurs
ServiceSession = what actually ran
Fulfillment  = what outcome was produced
```

La arquitectura permanece subordinada a la esencia:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Todo lo demás es implementación.
