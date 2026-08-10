# Request Engine — definición de producto y norte arquitectónico

> **Estado:** documento fundacional para Request Engine V2.
>
> Este documento define **qué es Request Engine, qué no es, cuáles son sus primitivas de dominio y qué límites deben guiar su evolución**. Las decisiones concretas de infraestructura pertenecen a ADRs y a `docs/01-architecture-v2.md`; no deben redefinir el producto.

---

## 1. La idea original

Request Engine es deliberadamente más general que un sistema de agenda, un CRM, un chatbot, un agente de IA o una plataforma de formularios.

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Formulación del producto:

> **Una persona, sistema o agente solicita un resultado a una organización. Request Engine convierte esa intención en trabajo estructurado, determina el workflow permitido, coordina capabilities deterministas y mantiene estado autoritativo hasta producir un resultado verificable.**

Request Engine no existe para “tener conversaciones”. Existe para **convertir intención en trabajo estructurado, trazable y ejecutable**.

---

## 2. Producto headless y developer-first

La primera fase de Request Engine es **API-first y headless**.

El primer consumidor es un desarrollador que combina Request Engine con otras herramientas para construir soluciones específicas para negocios. La interfaz que vea el usuario final puede ser un portal, website, mensaje, llamada, dashboard, widget o cualquier otra experiencia apropiada para el problema.

Principio:

```text
End user sees
result + action + state
        │
        ▼
Product-specific experience
        │
        ├── Request Engine
        ├── telephony
        ├── analytics
        ├── CRM
        └── other systems
```

El usuario final **no necesita conocer las tuberías**.

A futuro Request Engine puede convertirse en SaaS para terceros, pero el dominio y los contratos deben ser correctos antes de construir una experiencia de configuración universal.

Una developer console interna para inspeccionar organizaciones, credenciales, offerings, requests, reservations, eventos y webhooks es compatible con esta definición; no convierte a la UI en el centro del producto.

---

## 3. Qué problema resuelve

Los negocios reciben necesidades desde muchos canales:

- websites;
- formularios;
- teléfono;
- WhatsApp;
- chat;
- redes sociales;
- agentes de IA;
- empleados;
- APIs de terceros.

Aunque el canal cambia, el negocio necesita resolver preguntas similares:

1. ¿Quién está pidiendo algo?
2. ¿Qué quiere conseguir?
3. ¿Qué ofrece la organización que puede satisfacer esa intención?
4. ¿Qué información falta?
5. ¿Qué reglas y políticas aplican?
6. ¿Qué workflow debe ejecutarse?
7. ¿Qué capacidad o recursos deben reservarse?
8. ¿Qué acciones pueden ejecutarse automáticamente?
9. ¿Qué requiere confirmación, pago o intervención humana?
10. ¿Cuál fue el resultado final?

Request Engine proporciona una capa común para resolver esas preguntas sin duplicar lógica de negocio en cada website, bot, flujo de n8n, portal o agente de voz.

---

## 4. La unidad fundamental: `Request`

Un `Request` representa **una intención concreta y procesable que una organización debe atender**.

Ejemplos:

```text
"Quiero una limpieza dental"
"Necesito que un técnico revise una fuga hoy"
"Quiero una cotización"
"Necesito que me llamen"
"Quiero una evaluación de QuisqueyaTech"
"Quiero cambiar mi reservación"
```

`Request` no significa “cualquier dato del sistema”. No representa un pago, una métrica web, un producto ni una persona.

La regla es:

> **Request puede representar cualquier necesidad procesable, no cualquier cosa existente.**

Una conversación puede producir cero, uno o varios requests. Un request puede sobrevivir al canal que lo originó.

---

## 5. `Offering`: qué ofrece la organización

`Offering` es la fachada canónica para representar **algo que una organización ofrece y que otra persona o sistema puede intentar obtener**.

Ejemplos:

```text
Haircut
Dental Cleaning
Emergency Plumbing Visit
Technology Assessment
Business Website
Router + Installation
```

No crear una API fragmentada basada en `Product`, `Service`, `Package`, `AppointmentType`, etc. como identidades incompatibles.

La estrategia adoptada es:

> **Una fachada `Offering` estable con comportamiento interno especializado por composición.**

Conceptualmente:

```text
Offering
├── identity / description
├── kind
├── pricing behavior
├── intake requirements
├── resource requirements
├── reservation behavior
├── payment policy
└── module-specific configuration
```

`kind` puede distinguir categorías útiles como:

```text
service
product
package
custom
```

pero `kind` no debe producir una mega-entidad con cientos de campos nullable.

Los comportamientos especializados pertenecen a módulos/capabilities relacionados.

Ejemplo:

```text
Offering: Haircut

pricing:
  fixed: 800 DOP

reservation:
  nominal_duration: 30m

resource_requirements:
  barber: 1
  chair: 1

payment_policy:
  pay_after_service
```

Otro:

```text
Offering: Business Website

pricing:
  quote_required: true

reservation:
  none

fulfillment:
  project/deliverable
```

El API y los agentes pueden hablar consistentemente en términos de `offering_id` sin perder especialización interna.

---

## 6. `RequestType`: qué quiere lograr el solicitante

`Offering` y `RequestType` no representan lo mismo.

```text
Offering   = what the organization provides
RequestType = what the requester wants to accomplish
```

Ejemplo:

```text
Offering: Haircut

RequestType: reserve_offering
RequestType: request_quote
RequestType: request_information
```

Para actuar sobre una reservación existente:

```text
reschedule_reservation
cancel_reservation
```

Se adoptan **RequestTypes relativamente genéricos**, evitando crear un tipo diferente para cada offering:

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

La especialización del comportamiento surge de:

```text
RequestType
    +
Offering
    +
Organization policies
    ↓
Workflow version
```

Así, `reserve_offering + Haircut` puede usar un workflow estándar mientras `reserve_offering + Dental Surgery` puede resolver a un workflow especializado sin inventar cientos de RequestTypes.

Un `RequestType` puede describir conceptualmente:

```text
id
organizationId
name
inputSchema
workflowKey/defaultWorkflowKey
policies
status
version
```

---

## 7. Modelo mental del sistema

```text
                               CHANNELS

       Website       WhatsApp       Voice AI       Human UI       API
          │              │              │              │            │
          └──────────────┴──────────────┴──────────────┴────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │       INTAKE        │
                              │ normalize / identify│
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │       REQUEST       │
                              │ canonical intention │
                              └──────────┬──────────┘
                                         │
                               type + offering + policy
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │      WORKFLOW       │
                              │ deterministic rules │
                              └──────────┬──────────┘
                                         │
                         ┌───────────────┼────────────────┐
                         ▼               ▼                ▼
                    Reservations       Quotes          Handoff
                    / Capacity        / Pricing        / Tasks
                         │               │                │
                         └───────────────┼────────────────┘
                                         ▼
                              ┌─────────────────────┐
                              │     FULFILLMENT     │
                              │ outcome + evidence  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                                    EVENTS / AUDIT
```

Los canales son **adaptadores**. No deben poseer la lógica autoritativa del negocio.

---

## 8. Ciclo de vida conceptual de `Request`

El lifecycle exacto puede evolucionar, pero el core debe poder representar como mínimo:

```text
received
   ↓
understanding
   ↓
collecting_information
   ↓
ready
   ↓
executing
   ↓
waiting_external | waiting_confirmation | waiting_human
   ↓
completed | failed | cancelled | handoff
```

Reglas:

- una conversación puede producir cero, uno o varios requests;
- cambiar de WhatsApp a teléfono no crea necesariamente un request nuevo;
- el estado del request no depende del estado de Chatwoot, LiveKit, Twilio o n8n;
- cada transición importante es auditable;
- completar un request exige un resultado verificable o una razón explícita de terminación.

---

## 9. Workflow: decisión y ejecución

Request Engine debe responder:

> Dado este `Request`, su `Offering`, la organización, sus políticas y el contexto actual, ¿qué debe ocurrir ahora?

Un workflow puede:

1. pedir información faltante;
2. consultar una capability;
3. ofrecer opciones;
4. crear un `CapacityHold`;
5. ejecutar una operación;
6. solicitar confirmación o pago;
7. esperar un callback;
8. crear una tarea humana;
9. completar la solicitud;
10. fallar de forma recuperable;
11. hacer handoff.

No construir inicialmente BPMN, un editor visual universal ni un clon de n8n/Temporal. La primera versión favorece workflows tipados, versionados y testeables en código/configuración.

---

## 10. Capabilities y módulos

Request Engine es extensible mediante **capabilities deterministas**.

Ejemplos:

```text
reservations.searchAvailability
reservations.createHold
reservations.confirm
reservations.reschedule
reservations.cancel
reservations.checkIn
reservations.joinQueue

quotes.createDraft
quotes.send

contacts.upsert
notifications.send
handoff.createTask
```

Un workflow consume capabilities. Los canales y agentes consumen Request Engine.

Dependencia correcta:

```text
LiveKit ───────┐
WhatsApp ──────┤
Website ───────┼──► Request Engine ───► capability modules
Admin UI ──────┤
External API ──┘
```

No:

```text
Request Engine core
   ├── knows LiveKit internals
   ├── provisions Chatwoot
   ├── depends on n8n
   └── contains vertical-specific models
```

---

## 11. `Reservation`: compromiso de capacidad

`Reservation` es la primitiva canónica para representar **un compromiso de capacidad de una organización para atender una necesidad**.

No significa necesariamente una cita con hora exacta.

Una reservation puede representar:

```text
exact time slot
arrival window
queue-based commitment
hybrid scheduled + queue behavior
```

Principio:

> **Availability pregunta qué capacidad podría utilizarse. Reservation expresa qué capacidad ya fue comprometida. Admission determina cómo el solicitante entra efectivamente al servicio.**

`Reservation` puede referenciar uno o más Offerings y consumir uno o más Resources.

Conceptualmente:

```text
Reservation
├── organization
├── request
├── offering(s)
├── status
├── mode / policy references
├── planned temporal data
├── resource allocations
├── commercial snapshot
├── payment state/reference
└── audit/correlation
```

No se usa `booking` como vocabulario canónico del dominio o API. La primitiva es `Reservation`.

---

## 12. Availability, `CapacityHold` y confirmación

Separar tres conceptos:

```text
availability.search
       ↓
possible capacity

reservation.createHold
       ↓
temporary claim

reservation.confirm
       ↓
authoritative capacity commitment
```

### Availability

Es una lectura. No debe crear filas persistentes por cada exploración.

### `CapacityHold`

Es una reclamación temporal de capacidad cuando existe intención real de continuar, por ejemplo durante confirmación o pago.

Debe tener expiración explícita y no convertirse en una reservation confirmada hasta que se satisfagan sus condiciones.

### Confirmation

Debe revalidar capacidad transaccionalmente. Una respuesta previa de availability nunca garantiza que la capacidad siga disponible.

---

## 13. `AdmissionPolicy`: cómo se entra al servicio

`AdmissionPolicy` define las reglas mediante las cuales una persona obtiene acceso efectivo a la capacidad reservada.

Se adoptan inicialmente cuatro modos:

### `scheduled`

Capacidad asociada a un período preciso.

Ejemplo:

```text
10:00–10:30
check_in_required = true
grace_period = 15m
no_show_after = 20m
```

### `queue`

La atención depende principalmente de cola/orden operacional.

No asumir FIFO absoluto. Una `QueuePolicy` puede expresar ordering y prioridades explícitas.

```text
priority
+
arrival/order
```

### `window`

Capacidad comprometida dentro de una ventana, sin prometer un instante exacto.

```text
09:00–11:00
13:00–16:00
```

Útil para técnicos, delivery, visitas, laboratorios y operaciones variables.

### `hybrid`

Combina capacidad programada y reglas de cola.

Ejemplos:

```text
scheduled reservation
+ grace period
+ late_behavior = enqueue
```

También puede permitir coexistencia de reservations programadas y walk-ins sobre recursos compartidos.

Este modo es deliberadamente importante para negocios que necesitan formalizar gradualmente operaciones hoy basadas en orden de llegada o puntualidad imperfecta.

---

## 14. `CheckIn`, `QueueEntry` y presencia

Una reservation no implica que el solicitante ya esté presente o listo para consumir capacidad.

Separar:

```text
Reservation = capacity commitment
CheckIn     = requester is present/ready
QueueEntry  = operational position/priority in a queue
```

En un flujo híbrido:

```text
Reservation
    ↓
CheckIn
    ↓
QueueEntry [when applicable]
    ↓
ServiceSession
```

`QueueEntry` representa estado operacional dinámico; no sustituye la identidad durable de la reservation.

Una reservation de tipo queue puede crearse para un walk-in en el momento de llegada, permitiendo que toda demanda comprometida se consulte de forma uniforme mediante reservations.

---

## 15. Resources, requirements y allocations

No modelar una reservation únicamente con un `provider_id`.

Un Offering puede requerir múltiples recursos:

```text
Haircut
  barber: 1
  chair: 1

Dental Cleaning
  hygienist: 1
  treatment_chair: 1

Plumbing Visit
  technician: 1
  vehicle: 1
```

Separar conceptualmente:

```text
ResourceRequirement = what the Offering needs
ResourceAllocation  = what a Reservation actually consumes
```

El solicitante puede expresar preferencias o constraints, por ejemplo un profesional específico, mientras el engine puede seleccionar recursos compatibles cuando no existe preferencia.

---

## 16. `ServiceSession`: plan versus ejecución real

Una reservation representa capacidad **planificada/comprometida**. No debe sobrescribirse con la ejecución real.

Ejemplo:

```text
Reservation planned:
10:00–10:30

ServiceSession actual:
10:12–10:46
```

`ServiceSession` representa la ejecución real cuando el dominio la necesita.

Esto conserva hechos operacionales y permite calcular posteriormente duración real, espera, puntualidad, utilización y precisión de estimaciones sin convertir Request Engine en una plataforma genérica de analytics.

---

## 17. Estados de `Reservation`

El lifecycle de Reservation es independiente del lifecycle de Request.

Conjunto conceptual inicial:

```text
pending
held
confirmed
checked_in
admitted
in_service
completed
cancelled
expired
no_show
```

La implementación puede derivar algunos estados de `CheckIn`, `QueueEntry` o `ServiceSession`, pero el API debe poder ofrecer una vista operacional coherente.

Invariantes principales:

1. una Reservation pertenece exactamente a una organización;
2. normalmente deriva de un Request, aunque puede existir creación administrativa directa;
3. reserva capacidad relacionada con uno o más Offerings;
4. puede consumir uno o más Resources;
5. no implica necesariamente una hora exacta;
6. la confirmación revalida capacidad transaccionalmente;
7. conserva snapshots comerciales/políticas relevantes;
8. side effects externos ocurren después del commit;
9. cancelación y reprogramación son idempotentes cuando corresponda;
10. debe ser posible explicar por qué se asignó esa capacidad/prioridad.

---

## 18. Payments

Request Engine puede coordinar pagos necesarios para cumplir un workflow, pero no debe convertirse en un procesador de pagos ni sistema contable.

Un Offering o policy puede declarar:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Flujo conceptual:

```text
Availability
    ↓
CapacityHold
    ↓
Payment requirement
    ↓
External payment provider
    ↓
Signed/idempotent callback
    ↓
Reservation confirmation
```

IDs del proveedor son referencias externas, nunca identidad primaria del dominio.

El core puede conservar el estado mínimo necesario para coordinar la operación; ledger, contabilidad, conciliación financiera completa y facturación general pertenecen a otros dominios/módulos.

---

## 19. Forms / Intake como contrato reutilizable

Request Engine no debe construir inicialmente un competidor de Typeform o Jotform.

Primitivas suficientes:

```text
FormDefinition
FormSubmission
```

Los schemas de intake deben poder reutilizarse entre superficies.

Un mismo requerimiento estructurado puede alimentar:

```text
website form
voice agent questions
WhatsApp conversation
human UI
REST API
MCP/tool schema
```

La presentación cambia; el contrato de negocio permanece.

Una submission puede:

```text
identify/create Contact
        ↓
create/update Request
        ↓
emit Event
        ↓
resume Workflow
```

---

## 20. API para software y tools para agentes

Request Engine mantiene **una sola lógica autoritativa de aplicación**, pero no necesita exponer la misma superficie literal a todos los consumidores.

```text
                  Application layer
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       REST API      Public API      Agent tools
          │              │              │
       portals         widgets        MCP/LLM
```

El software tradicional necesita APIs composables. Un LLM se beneficia de tools orientadas a objetivos, schemas explícitos y scopes mínimos.

Ejemplo:

```text
REST:
GET  /v1/offerings
GET  /v1/availability
POST /v1/reservations/holds
POST /v1/reservations

Agent tools:
search_offerings
find_reservation_options
prepare_reservation
confirm_reservation
cancel_reservation
reschedule_reservation
```

Ambas superficies terminan ejecutando los mismos commands/invariantes del application layer.

La capa para agentes es un **adapter**, no un segundo dominio.

---

## 21. IA no es la autoridad del sistema

Request Engine debe funcionar aunque no exista un LLM.

La IA puede:

- interpretar lenguaje natural;
- clasificar intención;
- seleccionar un Offering candidato;
- extraer campos;
- explicar opciones;
- elegir una tool dentro de límites explícitos.

Pero:

```text
LLM interprets / proposes
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

Texto libre o una transcripción nunca modifica por sí solos reservations, pagos, identidad u otro estado crítico.

---

## 22. Workflow interno versus n8n y automatización externa

Request Engine no debe competir con n8n como plataforma universal de automatización.

Regla práctica:

> **Si eliminar una secuencia de pasos podría dejar inconsistente el estado autoritativo del negocio, esa lógica pertenece al workflow/capabilities de Request Engine.**

Ejemplo interno:

```text
validate offering
collect required data
check capacity
apply payment policy
confirm reservation
```

Ejemplo externo:

```text
reservation.confirmed
      ↓
add row to spreadsheet
send Slack message
add contact to campaign
```

Eso puede vivir en n8n, Zapier, Make o un consumer propio.

n8n puede servir como laboratorio rápido de integraciones. Cuando una capability demuestra ser repetible, crítica y común, puede promoverse a implementación nativa.

---

## 23. CRM, ERP, analytics y otros límites

Separación conceptual:

```text
CRM
Who is this person and what is our relationship?

Request Engine
What does this person/system need and what must happen now?

ERP/accounting
What resources, money, inventory and internal financial operations exist?
```

Request Engine necesita `Contact`, pero no tiene que convertirse en plataforma de campañas, lead scoring o marketing automation.

Puede coordinar payment state, pero no necesita general ledger, payroll o accounts payable.

Puede producir hechos operacionales y consumir analytics como capability, pero no debe convertirse en almacén universal de page views, Core Web Vitals, logs o series temporales de observabilidad.

Ejemplo válido:

```text
Request: generate_site_performance_report
        ↓
analytics capability
        ↓
Fulfillment: report reference
```

El sistema especializado de analytics sigue siendo dueño de sus métricas.

---

## 24. Qué pertenece al core

El núcleo debe permanecer pequeño.

### Tenancy e identidad operacional

- organizations;
- principals / credentials;
- contacts;
- organization-scoped configuration.

### Intent and work

- offerings como identidad/fachada de lo ofrecido;
- request types;
- requests;
- request lifecycle;
- workflow selection/execution state;
- fulfillments.

### Platform primitives

- events;
- audit;
- idempotency;
- webhooks/outbox;
- API authentication and scopes;
- versioned contracts.

### Módulos iniciales fuera del core puro

- reservations / scheduling;
- forms / intake;
- payments coordination.

“Fuera del core” significa **boundary de dominio**, no microservicio obligatorio.

---

## 25. Qué NO pertenece al core

Estas funcionalidades pueden existir como módulos o integraciones, pero no deben contaminar las abstracciones base:

- seguros / ARS;
- expedientes clínicos;
- licencias profesionales específicas;
- conceptos `patient`, `guardian`, `provider` específicos de healthcare;
- Chatwoot provisioning;
- Evolution provisioning;
- Meta WhatsApp provisioning;
- n8n workflows externos;
- LiveKit workers;
- Gemini / LLM provider details;
- SIP / PBX implementation;
- prompts específicos de agentes;
- lógica específica de una sola industria;
- inventario completo;
- accounting/ERP;
- un CRM completo;
- plataforma universal de analytics/telemetry;
- editor universal de workflows.

---

## 26. Multi-tenancy desde el primer día

Toda entidad tenant-owned debe estar claramente scoped a una organización.

```text
credential
    ↓
resolve organization + principal + scopes
    ↓
all domain operations execute inside that scope
```

No confiar en un `organizationId` arbitrario enviado por browser cuando la identidad de la credencial ya determina el tenant.

Deben existir al menos dos clases de acceso:

### Public/browser access

Para widgets, forms y websites. Permisos limitados, orígenes permitidos y operaciones explícitamente públicas.

### Secret/server access

Para workers, agents, backends e integraciones. API keys privadas, scopes y rotación.

Nunca colocar una secret API key organizacional dentro de JavaScript público.

---

## 27. Eventos, outbox, idempotencia y trazabilidad

Principio:

> **Una transacción interna no depende de que un sistema externo responda correctamente.**

```text
transaction commits
      ↓
domain event / outbox entry
      ↓
async delivery
      ↓
external provider
      ↓
idempotent callback
      ↓
state reconciliation
```

Requisitos:

- event IDs únicos;
- versionado de eventos;
- retries explícitos;
- deduplicación;
- callbacks firmados cuando corresponda;
- external IDs como referencias;
- idempotency en create request, holds, reservation confirmation, reschedule, cancel y callbacks cuando exista riesgo de retry;
- misma idempotency key con payload diferente produce conflicto explícito.

Cada request/reservation debe permitir reconstruir:

```text
Who initiated this?
What was understood?
Which Offering was selected?
What information was collected?
Which workflow/version handled it?
What capacity was considered/held/committed?
Which principal/tool performed each mutation?
What external events occurred?
What was the final outcome?
```

Logs sirven para diagnóstico técnico. Events/audit sirven para historia operacional.

---

## 28. Tiempo y scheduling

Invariantes temporales:

- timestamps persistidos como instantes UTC;
- zonas IANA donde se interpreta tiempo local;
- availability no equivale a reservation;
- confirmación de reservation revalida capacidad transaccionalmente;
- idempotency en confirmación/reprogramación/cancelación;
- buffers y recursos forman parte del conflicto real;
- snapshots protegen historial frente a cambios futuros del Offering/políticas;
- external side effects no ocurren dentro de la transacción;
- queues, windows y hybrid admission son ciudadanos de primera clase, no hacks sobre exact-time slots.

---

## 29. Public IDs e IDs externos

Conservar public IDs separados de IDs internos.

Ejemplos conceptuales:

```text
org_...
cnt_...
off_...
req_...
res_...
ful_...
evt_...
```

Integraciones externas se almacenan como mappings/references:

```text
provider
externalType
externalId
internalEntityType
internalPublicId
```

Un ID de Chatwoot, Twilio, LiveKit, Stripe o cualquier provider nunca se convierte en identidad primaria de dominio.

---

## 30. Conversations vs Requests

Distinción fundamental:

> **Conversation is context. Request is work.**

Chatwoot u otro sistema puede ser source of truth de una conversación. Request Engine es source of truth del trabajo estructurado que resulta de ella.

```text
Conversation #381
        │
        ├── Request req_A: request quote
        │
        └── Request req_B: reserve technician visit
```

La conversación puede cerrarse y ambos requests conservar lifecycle independiente.

---

## 31. Fulfillment

Un Request debe llegar a un resultado verificable, no solamente a un estado `completed` arbitrario.

Ejemplos:

```text
request_quote
    fulfillment → quoteId

reserve_offering
    fulfillment → reservationId

request_callback
    fulfillment → callbackTaskId

emergency_service
    fulfillment → reservationId / dispatchId
```

`Fulfillment` conecta intención con resultado real.

---

## 32. Vertical slice obligatorio de V2

Antes de añadir más módulos, V2 debe demostrar un camino completo:

```text
Organization
    ↓
Offering
    ↓
Contact
    ↓
RequestType
    ↓
Request
    ↓
Required Intake
    ↓
Workflow
    ↓
Resource Requirements
    ↓
Availability
    ↓
CapacityHold [when required]
    ↓
Reservation
    ↓
Admission / CheckIn / Queue [when applicable]
    ↓
ServiceSession [when applicable]
    ↓
Domain Event
    ↓
Webhook / Outbox
    ↓
Fulfillment linked back to Request
```

Debe probarse con dos organizaciones deliberadamente distintas:

### Demo Barbershop

Debe demostrar al menos:

```text
scheduled
queue
hybrid
walk-in
resource selection
payment policy
```

### Demo Plumbing

Debe demostrar al menos:

```text
intake
arrival windows
technician/vehicle resources
variable-duration service
optional deposit/payment
```

El objetivo no es demostrar muchas features. Es demostrar que las abstracciones sobreviven a dos modelos operacionales diferentes sin condiciones verticales en el core.

QuisqueyaTech puede ser el siguiente caso real para validar una organización de servicios profesionales.

---

## 33. Lo que se preserva de V1

Aprendizajes validados:

1. multi-tenancy explícito;
2. public IDs separados de IDs internos;
3. UTC + IANA timezones;
4. idempotency keys;
5. revalidación transaccional antes de comprometer capacidad;
6. snapshots comerciales relevantes;
7. outbox / asynchronous side effects;
8. callbacks idempotentes y tipados;
9. audit trail separado de logs;
10. API keys con scopes, expiración y revocación;
11. external IDs como referencias;
12. PII cifrada/blind-indexed cuando realmente sea necesaria;
13. agentes reciben tools deterministas en lugar de acceso libre a tablas;
14. el system of record interno no depende de Chatwoot, Evolution, n8n o LiveKit.

---

## 34. Lo que V2 debe evitar

No repetir:

1. modelar healthcare directamente en el core;
2. mezclar scheduling, insurance, provisioning, AI runtime y omnichannel en un solo dominio;
3. hacer de n8n una dependencia arquitectónica del engine;
4. hacer que Request Engine aprovisione sistemas externos como responsabilidad principal;
5. permitir un único archivo HTTP con routing, auth, parsing, crypto, callbacks y orchestration;
6. mantener OpenAPI manualmente separado de schemas reales;
7. generar writes de availability para cada exploración;
8. crear decenas de tablas/endpoints antes de demostrar un vertical slice;
9. confundir “reutilizable” con “soporta todas las industrias desde el día uno”;
10. convertir `Request`, `Offering` o `Reservation` en blobs genéricos que “pueden significar cualquier cosa”;
11. construir un editor universal de workflows;
12. usar exact-time appointments como única representación válida de capacidad.

---

## 35. Criterio para añadir una feature

Antes de añadir algo al core:

1. ¿Ayuda a representar una intención procesable?
2. ¿Ayuda a describir qué ofrece la organización?
3. ¿Ayuda a determinar/ejecutar el workflow?
4. ¿Necesita estado autoritativo dentro de Request Engine?
5. ¿Es común a múltiples industrias?
6. ¿Puede vivir mejor como módulo o integración?
7. ¿Tenemos un caso real que la necesita ahora?

Si no se justifica como core, permanece fuera.

---

## 36. North Star

Request Engine debe evolucionar hacia:

> **A headless, multi-tenant transactional request engine that turns customer or system intent into deterministic workflows, capacity commitments and verifiable outcomes, independent of channel, AI provider or vertical software.**

En español:

> **Un motor transaccional headless y multiempresa que transforma la intención de una persona o sistema en workflows deterministas, compromisos de capacidad y resultados verificables, independientemente del canal, proveedor de IA o software vertical.**

Frase operativa:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Y para evaluar boundaries:

```text
Offering     = what can be obtained
Request      = what is wanted now
Workflow     = what must happen
Reservation  = what capacity is committed
Admission    = how service access happens
Fulfillment  = what outcome actually happened
```

Si una feature no ayuda a representar esas responsabilidades o a mantener su trazabilidad e invariantes, probablemente no pertenece al núcleo de Request Engine.
