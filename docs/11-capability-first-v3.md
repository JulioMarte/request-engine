# Request Engine — capability-first product architecture V3

> **Estado:** normativo para la dirección de producto y arquitectura V3 durante la transición pre-baseline.
>
> Este documento tiene precedencia sobre `00-product-definition.md`, `01-architecture-v2.md` y `02-pre-sql-domain-contract.md` cuando exista conflicto sobre **qué pertenece al producto, el significado de Request, qué capacidades forman el baseline y qué abstracciones deben posponerse**. Los invariantes de seguridad/concurrencia V2 siguen vigentes donde el concepto correspondiente siga formando parte del baseline.
>
> El design chain PostgreSQL V2.6→V2.10 es un artefacto de diseño provisional hasta que esta arquitectura sea reflejada en los contratos pre-SQL y en un nuevo baseline.

---

## 1. Product thesis

Request Engine no es un motor universal de workflows.

Request Engine es una **API headless, multi-tenant y agent-friendly de capacidades operacionales de negocio**. Permite que canales como WhatsApp, voz, formularios web, aplicaciones, n8n y agentes LLM consulten información estructurada y ejecuten operaciones reales del negocio a través de contratos estables.

```text
WhatsApp / Voice / Web / n8n / Apps / Agents
                    │
                    ▼
             Request Engine API
                    │
          capability-oriented surface
                    │
      ┌─────────────┼──────────────┐
      │             │              │
   queries       commands       requests
      │             │              │
      └─────────────┼──────────────┘
                    │
             domain modules
                    │
               PostgreSQL
                    │
              outbox/events
                    │
          adapters / n8n / providers
```

La API puede ser común para muchos tipos de negocio sin exigir que todos compartan un único modelo universal de workflow, fulfillment, payment, dispatch o capacity planning.

### 1.1 Core objective

El sistema debe hacer fácil y seguro que una máquina pueda responder:

```text
¿Qué sabe este negocio?
¿Qué puede hacer este negocio?
¿Qué operación puedo ejecutar ahora?
¿Qué información necesito para ejecutarla?
¿Qué ocurrió después?
```

La ventaja competitiva no es representar cualquier proceso imaginable. Es ofrecer una superficie operacional consistente para agentes y aplicaciones mientras las reglas autoritativas permanecen deterministas y auditables.

---

## 2. Product boundary

Request Engine puede poseer:

- identidad tenant-scoped mínima;
- catálogo estructurado del negocio;
- disponibilidad y reservas;
- turnos/colas operacionales;
- waitlists para capacidad futura;
- Requests durables para trabajo que no termina en una mutación síncrona;
- intake/form submissions;
- comunicaciones transaccionales y recordatorios;
- scheduling durable de acciones;
- idempotencia, outbox, audit y provider-event ingestion;
- contratos para integraciones y progressive hardening desde n8n.

Request Engine NO es:

- CRM completo;
- CMS universal;
- knowledge/RAG platform universal;
- BPMN/workflow engine;
- Temporal clone;
- ERP/accounting system;
- PSP;
- marketing automation suite;
- PBX;
- workforce optimizer;
- route optimizer;
- industrial scheduler;
- generic agent framework.

Puede integrarse con todos ellos.

---

## 3. Four interaction semantics

Toda capacidad expuesta debe clasificarse explícitamente como `Query`, `Command`, `Request` o `ScheduledAction`.

### 3.1 Query

Consulta estado sin producir una mutación autoritativa relevante.

Ejemplos:

```text
get_business_info
search_offerings
get_offering_details
find_appointment_slots
get_reservation_status
get_queue_status
get_request_status
```

Las queries pueden usar read models y caches, pero no conceden authority por sí mismas.

### 3.2 Command

Orden semántica que muta estado autoritativo existente o crea un compromiso inmediato dentro de una transacción definida.

Ejemplos:

```text
book_appointment
cancel_reservation
reschedule_reservation
join_queue
leave_queue
accept_slot_offer
confirm_attendance
```

Un Command debe tener:

- actor/Principal;
- tenant context;
- authorization/Representation cuando aplique;
- idempotency semantics;
- transaction boundary explícito;
- invariant validation;
- machine-readable failure semantics.

### 3.3 Request

`Request` es un **envelope durable de nueva demanda de negocio que necesita procesamiento y puede requerir respuesta posterior, trabajo humano, integración externa o proceso asíncrono**.

Ejemplos válidos:

```text
request_quote
request_callback
request_service
submit_intake_for_review
```

No usar Request como wrapper universal para cualquier mutación.

Normalmente NO son nuevos Requests:

```text
cancel_reservation
reschedule_reservation
confirm_attendance
leave_queue
```

Sólo se modelan como Request si el negocio realmente trata esa operación como una solicitud sujeta a aprobación/revisión independiente.

### 3.4 ScheduledAction

Acción durable que debe ejecutarse en un momento futuro o cuando una condición/evento interno la habilita.

Ejemplos:

```text
send appointment reminder at T-48h
request attendance confirmation at T-24h
retry a failed transactional message
expire a slot offer
send medication reminder at 08:00
```

Un ScheduledAction no es un Request y no implica un workflow engine general.

---

## 4. Capability-first public API

La API pública se diseña alrededor de **business capabilities**, no alrededor de tablas o entidades internas.

Preferido:

```text
business.get_info
catalog.search_offerings
appointments.find_slots
appointments.book
appointments.cancel
appointments.reschedule
appointments.confirm_attendance
queue.join
queue.status
queue.leave
waitlist.join
waitlist.status
quotes.request
requests.status
```

No exponer como herramientas agent-facing:

```text
create_capacity_claim
create_resource_allocation
set_request_status
insert_outbox_message
set_payment_status
```

### 4.1 Capability discovery

Request Engine debe poder evolucionar hacia un catálogo machine-readable de capacidades habilitadas para un tenant:

```json
{
  "capabilities": [
    "business.get_info",
    "catalog.search_offerings",
    "appointments.find_slots",
    "appointments.book",
    "appointments.cancel",
    "appointments.reschedule",
    "queue.join",
    "queue.status",
    "waitlist.join",
    "quotes.request"
  ]
}
```

Esa descripción puede alimentar REST/OpenAPI, tool definitions para LLMs, MCP, SDKs y nodos n8n sin cambiar el dominio interno.

---

## 5. Structured business information vs knowledge

Request Engine puede ser autoridad de información estructurada necesaria para operar:

```text
Organization profile
Locations
Opening/service hours
Offerings
Offering versions
basic operational policies
contact endpoints
```

No debe convertirse en un CMS/RAG universal.

Un agent runtime puede combinar:

```text
structured operational truth from Request Engine
+
external knowledge provider / CMS / RAG / website index
```

La knowledge source externa nunca obtiene authority implícita para mutar estado transaccional.

---

## 6. Baseline business capabilities

El primer baseline debe demostrar utilidad real sin anticipar industrias hipotéticas.

### 6.1 Business information and catalog

Soportar datos estructurados suficientes para que un bot pueda responder preguntas operacionales comunes y descubrir servicios.

### 6.2 Appointment booking

Soportar:

```text
find availability
acquire temporary capacity when necessary
confirm reservation
cancel
reschedule
read status
```

Capacity V1 debe centrarse en:

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityClaim
CapacityHold
Reservation
```

Modelos iniciales:

```text
exclusive
units
```

No introducir pools, late-binding optimization ni field-service planning salvo caso productivo concreto.

### 6.3 Service Queue

Representa personas/items esperando servicio **ahora**.

Semántica inicial:

```text
FIFO by admitted_at
```

Estados iniciales:

```text
waiting
called
serving
completed
cancelled
no_show
```

Priority/triage/manual override pueden añadirse posteriormente como policy explícita; no construir optimizer V1.

### 6.4 Waitlist / standby

Waitlist es distinta de ServiceQueue.

Representa demanda dispuesta a consumir capacidad que pueda aparecer en el futuro.

Debe poder expresar inicialmente:

```text
subject/Party
Offering/service scope
acceptable date/time window
location/resource preference when relevant
created_at
status
```

Cuando se libera capacidad, Request Engine puede crear un `SlotOffer` temporal para un candidato elegible.

`SlotOffer` debe expirar y aceptar idempotentemente; aceptar requiere revalidar capacidad bajo el mismo protocolo de booking.

### 6.5 Generic Request and Intake

Nuevos procesos no estabilizados pueden entrar mediante:

```text
Request
IntakeDefinition
IntakeSubmission
```

`IntakeSubmission.payload` puede usar JSONB porque es un boundary de ingestión versionado, no el modelo autoritativo de cada dominio futuro.

Un handler puede:

```text
process natively
OR
emit event/outbox → n8n
```

### 6.6 Transactional Communications

Request Engine debe poseer la **intención durable de comunicación**, no el transporte específico.

Ejemplos:

```text
appointment confirmation
appointment reminder
reservation changed
reservation cancelled
queue turn approaching
slot became available
quote ready
request completed
medication reminder
```

Conceptos mínimos:

```text
CommunicationTask
CommunicationDelivery
CommunicationTemplate/TemplateRef
CommunicationPreference
ContactEndpoint
```

La business transaction crea el hecho/evento que origina la comunicación; la entrega ocurre después de commit.

### 6.7 Durable Scheduling

Request Engine requiere un scheduler durable para acciones futuras.

Concepto mínimo:

```text
ScheduledAction
  id
  organization_id
  action_type
  execute_at
  subject/reference
  status
  dedupe_key
  attempt_count
  lease/fencing metadata
```

Los workers deben reclamar trabajo con leases/fencing y `FOR UPDATE SKIP LOCKED` o mecanismo equivalente probado.

No mantener transacciones DB abiertas durante I/O externo.

---

## 7. Reservation confirmation vs attendance confirmation

No colapsar:

```text
Reservation is confirmed
≠
Customer/patient has confirmed attendance
```

Una Reservation puede existir y consumir capacidad mientras la respuesta de asistencia sigue pendiente.

Concepto inicial:

```text
AttendanceResponse
  pending
  accepted
  declined
```

El comportamiento ante `pending` después de un deadline es policy tenant/Offering-specific.

Ejemplos válidos:

```text
on_no_response = keep_reservation
on_no_response = escalate_communication
on_no_response = cancel_after_deadline
```

No asumir que ausencia de respuesta equivale a cancelación.

---

## 8. Cancellation recovery and slot filling

Cancelación/release puede producir nueva capacidad.

Proceso inicial:

```text
Reservation cancelled
      ↓
capacity released
      ↓
slot/capacity opportunity detected
      ↓
eligible WaitlistEntry selected by deterministic policy
      ↓
SlotOffer created with expires_at
      ↓
transactional communication sent
      ↓
accept → revalidate capacity → create Reservation
expire/decline → next eligible candidate
```

FIFO puede ser la policy V1 de selección entre candidatos igualmente elegibles.

No convertir esto en optimization/auction engine.

---

## 9. Reminder plans

Recordatorios no ligados a Reservation requieren un concepto separado de recurring intent, por ejemplo `ReminderPlan`.

Uso inicial:

```text
subject
purpose
schedule/timezone
start/end
channel preference
acknowledgement mode
```

`ReminderPlan` genera ScheduledActions/CommunicationTasks. Request Engine puede registrar acknowledgement, pero no infiere ni modifica por sí mismo contenido clínico, dosis o instrucciones médicas.

El dominio operationaliza un plan autorizado; no practica medicina.

---

## 10. Communications execution boundary

Correcto:

```text
BEGIN business transaction
  mutate authoritative state
  append domain/outbox fact
COMMIT

worker
  derive/claim CommunicationTask
  call provider
  persist delivery result
```

Incorrecto:

```text
BEGIN
  reserve capacity
  call WhatsApp/Twilio/LiveKit
  wait on network
COMMIT
```

Adapters iniciales pueden ser:

```text
n8n webhook
Evolution/Meta WhatsApp
SMS provider
email provider
LiveKit/voice provider
```

Provider-specific IDs y delivery facts se conservan para idempotency, correlation y audit.

---

## 11. n8n as extension layer — progressive hardening

Principio:

> **Experiment outside; harden inside.**

Un flujo empieza fuera del core cuando es:

- nuevo o cambiante;
- integration-heavy;
- poco frecuente;
- tenant-specific;
- no crítico para consistencia transaccional.

Un flujo se promueve a implementación nativa cuando requiere:

- atomicidad;
- fuerte idempotencia;
- race safety;
- baja latencia;
- alto volumen;
- shared domain rules;
- stable semantics;
- garantías que n8n no debe poseer.

Ejemplo:

```text
quotes.request
  → Request Engine Request
  → outbox
  → n8n workflow
  → external systems/human approval
  → semantic callback command into Request Engine
```

Posteriormente puede convertirse en un módulo `quotes` sin cambiar la capability pública.

n8n nunca debe ser la autoridad final de double-booking, reservation state, tenant authority o idempotency de commands críticos.

---

## 12. Target bounded contexts / modules

### Active baseline modules

```text
tenancy
catalog
requests
booking
queue
communications
```

### Platform capabilities

```text
platform/db
platform/idempotency
platform/outbox
platform/audit
platform/events
platform/scheduling
platform/observability
platform/security
```

`platform/scheduling` posee infraestructura de lease/claim/clock/retry para ScheduledAction execution. La policy de por qué existe una acción programada pertenece al módulo de negocio que la crea.

### Incubating/deferred modules

No forman parte del baseline obligatorio mientras no exista un vertical productivo que los necesite:

```text
payments
dispatch
advanced delivery/fulfillment
capacity pools
external capacity planning
```

Código/documentación preexistente puede conservarse temporalmente durante la transición, pero no debe forzar el nuevo baseline.

---

## 13. Workflow decision

No existe `Workflow` como universal domain aggregate en V3 baseline.

La orquestación se representa mediante:

```text
application command/query handlers
Request state + explicit domain facts
ScheduledAction
outbox/events
provider callbacks
n8n extension workflows
```

Versionar handler/policy cuando su semántica histórica deba ser explicable.

Introducir un workflow engine sólo después de demostrar repetición real de patrones que no puedan resolverse limpiamente con estas primitivas.

---

## 14. Outcome/Fulfillment decision

`OutcomeScope` deja de ser requisito universal del baseline.

No introducir `RequestedOutcome` u otra abstracción equivalente hasta demostrar un caso donde una selección produzca múltiples outcomes independientes con lifecycle/concurrency propios.

Para V3 baseline:

```text
Request + RequestItem/OfferingSelection
Reservation
QueueEntry
Communication/Delivery facts
```

son suficientes para los verticals iniciales.

Execution/Fulfillment puede regresar como módulo cuando un vertical real necesite demostrar prestación de servicio más allá de reservation/queue completion.

---

## 15. Payment decision

Payments no desaparece del producto futuro, pero deja de ser un prerequisito de arquitectura para el baseline inicial.

Cuando se reincorpore, debe hacerlo alrededor de casos concretos:

```text
no payment prerequisite
pay/deposit before confirm
reserve now / pay before deadline
```

El dominio financiero avanzado no debe bloquear la entrega de información, appointments, queue, communications, waitlist y generic Requests.

---

## 16. Capacity simplification

V3 conserva el principio fuerte de PostgreSQL como serialization authority para capacidad local, pero reduce el alcance.

Baseline:

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
```

Explorar antes del baseline si `ResourceAllocation` añade verdad independiente o duplica `CapacityClaim` para reservation consumption. Evitar pares 1:1 que existan sólo por separación conceptual si una sola fila puede expresar la truth requerida.

### 16.1 Reschedule rule

Reschedule sobre el mismo conflict space no debe requerir adquirir primero un replacement Hold que colisione contra la propia Reservation antigua.

El protocolo objetivo es:

```text
lock Reservation
lock old/new capacity authorities in canonical order
validate final desired capacity state excluding claims replaced by this operation
atomically replace old claims with new claims
commit
```

Failure conserva la Reservation original.

External commitments, si se añaden en el futuro, se coordinan mediante idempotency/compensation; no distributed transaction fantasy.

---

## 17. API and agent safety contract

Todos los writes agent-facing deben usar:

- stable opaque/public identifiers;
- `Idempotency-Key` o equivalente;
- explicit actor/tenant context;
- schema validation;
- expected revision/version cuando sea útil para optimistic coordination;
- typed machine-readable errors;
- no generic `PATCH entity` para lifecycle crítico.

Error shape debe poder comunicar al agent:

```text
code
human-safe message
retryable
invariant/constraint category
current revision/state when safe
suggested next capability/action when deterministic
```

Simulation/preview puede existir para availability, reschedule o cancellation consequences, pero execute siempre revalida authoritative state.

---

## 18. Tenant and security rule

Capas:

```text
authentication
→ Principal
→ Organization context
→ Representation/capability authorization
→ domain invariant
→ PostgreSQL structural isolation
```

Composite tenant FKs siguen siendo obligatorios para lineage crítica.

Antes de production baseline debe decidirse el runtime DB isolation model; RLS es candidato fuerte como defense-in-depth para roles request-facing, con workers/admin usando roles explícitos y mínimos.

Public IDs/correlation IDs nunca conceden authority.

---

## 19. Reliability baseline

Outbox/scheduler/communications workers deben definir:

```text
lease/fencing
attempt count
retry classification
next_attempt_at
max attempts
terminal/dead-letter state
manual replay
provider idempotency/correlation
backpressure/rate limiting strategy
```

No infinite poison retries.

---

## 20. Observability baseline

Antes de declarar production-ready, instrumentar OpenTelemetry o equivalente para:

```text
HTTP/API request
application command/query
DB transaction
lock wait/deadlock
capacity conflict
scheduled action lag
outbox age/attempts
communication provider latency/failure
waitlist offer conversion/expiry
queue wait time
```

Audit/domain history y technical telemetry son conceptos distintos.

---

## 21. First proof verticals

El baseline no se congela hasta implementar y probar de extremo a extremo:

1. **Business information** — agent/query obtiene profile/location/hours/offering data.
2. **Appointment booking** — availability → book → cancel → reschedule con race tests reales.
3. **Appointment communications** — confirmation + reminder + attendance response usando scheduler/outbox.
4. **FIFO service queue** — join → status → call/start → complete/leave.
5. **Cancellation waitlist** — released capacity → SlotOffer → accept/expire → rebooking race-safe.
6. **Generic Request → n8n** — ejemplo inicial: quote/intake enviado por outbox y callback semántico idempotente.

Estos verticals prueban la tesis del producto sin convertir el core en plataforma universal.

---

## 22. Baseline freeze gate

No crear/squash `0001_initial` hasta que:

- los conceptos V2 fuera del V3 baseline estén eliminados o explícitamente aislados;
- Request semantics se hayan corregido;
- Queue y Waitlist sean distintos;
- communications/scheduling tengan transaction/retry contracts;
- reschedule protocol sea self-overlap safe;
- capacity scope V1 esté reducido y race-tested;
- tenant runtime isolation esté decidido;
- los seis proof verticals tengan contratos y al menos los críticos tengan implementación/race tests PostgreSQL;
- la invariant matrix refleje únicamente promises reales del baseline.

---

## 23. Architectural north star

Request Engine debe crecer añadiendo capacidades independientes, no expandiendo una abstracción universal.

```text
one public operational API
        ≠
one universal domain model
```

La arquitectura correcta hace simple el camino común y mantiene un escape hatch explícito para lo desconocido:

```text
stable capability → native module
new/volatile process → Request + outbox + n8n
proven repeated process → promote into native module
```

Ese mecanismo de promoción es parte del diseño, no una deuda técnica accidental.
