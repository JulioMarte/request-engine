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

La primera fase es **API-first y headless**.

El primer consumidor es un desarrollador que combina Request Engine con otras herramientas para construir soluciones específicas para negocios. La interfaz que vea el usuario final puede ser un portal, website, mensaje, llamada, dashboard, widget o cualquier otra experiencia apropiada.

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

El usuario final no necesita conocer las tuberías.

A futuro Request Engine puede convertirse en SaaS para terceros, pero el dominio y los contratos deben ser correctos antes de construir una experiencia de configuración universal.

Una developer console interna para inspeccionar organizations, credentials, offerings, requests, reservations, resources, locations, dispatches, events y webhooks es compatible con esta definición; no convierte a la UI en el centro del producto.

---

## 3. Qué problema resuelve

Los negocios reciben necesidades desde muchos canales:

- websites;
- forms;
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
5. ¿Dónde puede prestarse o recibirse el servicio?
6. ¿Cuándo existe capacidad real?
7. ¿Qué recursos son necesarios?
8. ¿Qué reglas y políticas aplican?
9. ¿Qué workflow debe ejecutarse?
10. ¿Qué requiere confirmación, pago o intervención humana?
11. Si el servicio ocurre fuera de una location, ¿qué debe desplazarse y hacia dónde?
12. ¿Cuál fue el resultado final?

Request Engine proporciona una capa común para responder esas preguntas sin duplicar lógica de negocio en cada website, bot, flujo de n8n, portal o agente de voz.

---

## 4. `Request`: la unidad de intención procesable

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
├── availability restrictions
├── location/service-area compatibility
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

pero no debe producir una mega-entidad con cientos de campos nullable. Los comportamientos especializados pertenecen a módulos/capabilities relacionados.

---

## 6. `RequestType`: qué quiere lograr el solicitante

```text
Offering    = what the organization provides
RequestType = what the requester wants to accomplish
```

RequestTypes relativamente genéricos:

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

La especialización surge de:

```text
RequestType
    +
Offering
    +
Organization policies
    +
Request context
    ↓
Workflow version
```

Así, `reserve_offering + Haircut` puede usar un workflow estándar mientras otro Offering puede resolver a un workflow especializado sin inventar cientos de RequestTypes.

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
                    ┌────────────────────┼─────────────────────┐
                    ▼                    ▼                     ▼
               Reservations           Quotes              Handoff
               / Capacity           / Pricing             / Tasks
                    │                    │                     │
                    └────────────────────┼─────────────────────┘
                                         ▼
                                   Dispatch?
                                         │
                                         ▼
                                ServiceSession?
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │     FULFILLMENT     │
                              │ outcome + evidence  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                                    EVENTS / AUDIT
```

Los canales son adapters. No poseen la lógica autoritativa del negocio.

---

## 8. Workflow

Request Engine responde:

> Dado este `Request`, su `Offering`, la organización, sus policies y el contexto actual, ¿qué debe ocurrir ahora?

Un workflow puede:

1. pedir información faltante;
2. consultar una capability;
3. ofrecer opciones;
4. crear un `CapacityHold`;
5. ejecutar una operación;
6. solicitar confirmación o pago;
7. esperar un callback;
8. crear una tarea humana;
9. crear/coordinar un Dispatch;
10. completar la solicitud;
11. fallar de forma recuperable;
12. hacer handoff.

No construir inicialmente BPMN, un editor universal ni un clon de n8n/Temporal. La primera versión favorece workflows tipados, versionados y testeables en código/configuración.

---

## 9. Capabilities

Ejemplos:

```text
reservations.searchAvailability
reservations.createHold
reservations.confirm
reservations.reschedule
reservations.cancel
reservations.checkIn
reservations.joinQueue

locations.getDetails
locations.getCurrentHours

dispatch.assign
dispatch.markEnRoute
dispatch.markArrived

quotes.createDraft
quotes.send
contacts.upsert
notifications.send
handoff.createTask
```

Un workflow consume capabilities. Los canales y agentes consumen Request Engine.

---

## 10. `Reservation`: compromiso de capacidad

`Reservation` es la primitiva canónica para representar **un compromiso de capacidad de una organización para atender una necesidad**.

No significa necesariamente una cita con hora exacta.

Puede representar:

```text
exact time slot
arrival window
queue-based commitment
hybrid scheduled + queue behavior
```

> **Availability pregunta qué capacidad podría utilizarse. Reservation expresa qué capacidad ya fue comprometida. Admission determina cómo el solicitante entra efectivamente al servicio.**

No se usa `booking` como vocabulario canónico del dominio o API.

---

## 11. Availability, `ReservationOption`, `CapacityHold` y confirmación

Separar:

```text
availability.search
       ↓
ReservationOption(s)
       ↓
reservation.createHold [when needed]
       ↓
reservation.confirm
```

### Availability

Es lectura de capacidad potencial. No crea writes por cada exploración.

### `ReservationOption`

Representa una opción calculada para el consumidor. Puede ser efímera/opaca y no debe asumirse como garantía futura.

### `CapacityHold`

Reclamación temporal cuando existe intención real de continuar, por ejemplo durante confirmación o pago. Tiene expiración explícita.

### Confirmation

Revalida capacidad transaccionalmente. Una respuesta previa de availability nunca garantiza que la capacidad siga disponible.

---

## 12. `AdmissionPolicy`

Define cómo una reservation entra al servicio.

Modos iniciales:

### `scheduled`

Capacidad asociada a un período preciso.

### `queue`

Orden operacional. No asumir FIFO absoluto; puede aplicar `priority + ordering`.

### `window`

Capacidad comprometida dentro de una ventana sin prometer un instante exacto.

### `hybrid`

Compone scheduled + queue, por ejemplo:

```text
scheduled reservation
+ grace period
+ late_behavior = enqueue
```

También permite coexistencia controlada de reservations programadas y walk-ins sobre capacidad compartida.

Este modo es importante para negocios que necesitan formalizar gradualmente operaciones basadas hoy en orden de llegada o puntualidad imperfecta.

---

## 13. `CheckIn`, `QueueEntry` y `ServiceSession`

Separar:

```text
Reservation   = committed/planned capacity
CheckIn       = requester is present/ready
QueueEntry    = dynamic operational queue position/priority
ServiceSession = actual execution
```

No sobrescribir lo planificado con tiempos reales.

```text
Reservation planned: 10:00–10:30
CheckIn:             10:07
ServiceSession:      10:14–10:52
```

Una reservation queue-based puede crearse para un walk-in en el momento de llegada, manteniendo una vista uniforme de toda demanda comprometida.

---

## 14. `Resource`: qué puede proveer capacidad

`Resource` representa algo cuya disponibilidad o capacidad limita materialmente si una Reservation puede cumplirse.

Ejemplos:

```text
person
facility
room
chair
equipment
vehicle
capacity pool
virtual resource
```

No todo dato del negocio es un Resource. Un customer, address, payment method u Offering normalmente no lo son.

Regla:

> **Algo es Resource cuando su disponibilidad/capacidad participa de forma autoritativa en la posibilidad de cumplir una Reservation.**

---

## 15. `ResourceCapability`

No conectar Offerings directamente a nombres concretos de recursos cuando no sea necesario.

```text
Carlos
capabilities:
  haircut
  beard_trim
  hair_color

Offering: Hair Coloring
requires capability: hair_color
```

`ResourceCapability` es tenant-scoped y configurable. No usar enums globales por industria.

Esto permite que el scheduler encuentre recursos compatibles sin condiciones como `if industry == ...`.

---

## 16. Capacity

Capacity responde:

> **¿Cuánto puede proveer un Resource simultáneamente o dentro del modelo operacional relevante?**

Para V2 se mantienen modelos deliberadamente pequeños:

```text
exclusive
units
```

### `exclusive`

Una Reservation consume el Resource de forma exclusiva en el período relevante.

Ejemplos:

```text
barber
dentist
chair
vehicle
machine
```

### `units`

El Resource expone N unidades reservables y una Reservation consume cierta cantidad.

Ejemplos:

```text
class seats
tour seats
shared support capacity
reservable equipment pool
```

No usar capacity como inventario comercial general. Request Engine debe garantizar capacidad reservable, no convertirse en inventory management ni en un scheduler multidimensional tipo cluster/workforce optimizer.

---

## 17. `ResourceRequirement`, `ResourceAllocation` y assignment

Separar tres ideas:

```text
Requirement
= what capacity an Offering needs

Allocation
= what capacity a Reservation committed

Assignment
= which concrete operational resource will execute
```

### Requirement

Ejemplo:

```text
Offering: Haircut
requires:
  capability barber x1
  capability barber_chair x1
```

### Allocation

Ejemplo:

```text
Reservation res_123
allocates:
  Carlos x1
  Chair 2 x1
```

### Late assignment

En field service la capacidad puede reservarse antes de conocer el recurso concreto:

```text
Reservation: tomorrow 1–4 PM
Allocation: North Technician Pool x1
Later assignment: Miguel + Vehicle 02
```

La distinción conceptual debe preservarse aunque la primera implementación pueda representar assignment dentro del modelo de allocation.

---

## 18. Resource pools y groups

No confundir:

```text
ResourceGroup
= organizational/query grouping

Resource(kind=pool)
= reservable aggregate capacity
```

Un grupo ayuda a descubrir recursos. Un pool puede comprometer capacidad agregada antes de asignar un miembro concreto.

Esto es especialmente útil para field service y operaciones donde la asignación final ocurre cerca de la ejecución.

---

## 19. Principio del scheduler

Availability no debe limitarse a “buscar citas libres”.

Debe responder conceptualmente:

> **¿Existe una combinación válida de tiempo/policy/capacidad que satisfaga todos los ResourceRequirements del Offering?**

```text
Offering
    ↓
ResourceRequirements
    ↓
Schedules + policies
    ↓
compatible Resources / pools
    ↓
remaining capacity
    ↓
ReservationOption
```

Request Engine garantiza capacidad válida y compromisos correctos. **No tiene que resolver el plan global óptimo de una fuerza laboral completa.** Routing global, optimización de costos y planificación avanzada pueden delegarse a sistemas especializados.

---

## 20. Tiempo: `BusinessHours` y `AvailabilitySchedule`

No reducir tiempo a una columna `opening_hours`.

Separar:

```text
BusinessHours
= cuándo una organización/location está normalmente abierta o disponible al público

AvailabilitySchedule
= cuándo una capacidad/Offering/Resource puede realmente reservarse
```

Pueden diferir.

Ejemplo:

```text
Office BusinessHours:
Mon–Fri 09:00–17:00

Emergency Plumbing AvailabilitySchedule:
24/7
```

Un schedule debe soportar múltiples intervalos por día y timezone IANA explícita.

Ejemplo:

```text
Mon–Fri: 09:00–18:00
Saturday: 09:00–12:00
Sunday: closed
```

Y también:

```text
Monday:
09:00–12:00
14:00–18:00
```

---

## 21. Jerarquía y composición de schedules

Availability efectiva puede depender de múltiples niveles:

```text
Organization schedule
        ∩
Location schedule
        ∩
Offering restrictions
        ∩
Resource schedule
        ↓
Date-specific exceptions
        ↓
remaining capacity after holds/reservations
```

Un Resource puede restringir el horario heredado, pero no debe expandir silenciosamente una location/organization cerrada.

Ejemplo:

```text
Organization: Sunday closed
Carlos: Sunday available
```

no abre automáticamente el negocio. Una apertura extraordinaria debe declararse explícitamente.

---

## 22. `ScheduleException`

Un schedule describe la normalidad. Una exception describe una fecha/rango donde la realidad cambia.

Tipos iniciales:

```text
closed
replace_hours
open_special
capacity_override
```

Ejemplos:

```text
Dec 25 → closed
Dec 24 → replace_hours 09:00–13:00
Special Sunday → open_special 10:00–16:00
Saturday pool → capacity_override 2
Carlos Aug 15–18 → closed/unavailable
```

Las exceptions pueden aplicarse al scope correcto: organization, location, Offering, Resource o pool según corresponda.

---

## 23. `HolidayCalendar`

Conservar la capacidad de V1 para feriados y cierres especiales, pero sin hardcodear calendarios mundiales dentro del core.

```text
HolidayCalendar
├── HolidayDate
├── name
├── date
├── observed_date?
└── metadata
```

Que una fecha sea feriado **no implica automáticamente que el negocio esté cerrado**.

Una policy define el comportamiento:

```text
closed_by_default
normal_schedule
special_hours
```

También deben permitirse fechas propias de la organización:

```text
staff training
company event
inventory day
private closure
```

---

## 24. `Location`: dónde opera o recibe la organización

`Location` es first-class y representa un lugar operativo controlado/presentado por la organización.

Puede incluir:

```text
name
description
structured address
timezone
BusinessHours / schedule references
phone/contact presentation
arrival instructions
parking/accessibility instructions
status
map reference
optional coordinates
```

Una organization puede tener múltiples locations, y Offerings/Resources pueden estar disponibles sólo en ciertas locations.

---

## 25. Ubicación pensada para usuarios reales

Request Engine debe almacenar y devolver la información que realmente sirve a humanos y agentes.

La representación práctica preferida para compartir una location puede ser:

```text
Google Maps URL
Google Maps place/share link
map pin URL
human-readable address
arrival instructions
landmark text
```

`latitude`/`longitude` pueden existir como datos interoperables opcionales para mapas, validación o integraciones, pero **no son la experiencia primaria que se presenta al usuario**.

Principio:

> **Store enough structured location data for machines, but expose/share the representation humans actually use.**

No acoplar la identidad de Location a Google Maps. El link externo es una referencia/presentation aid, no el primary key.

---

## 26. `LocationMedia`

Una Location puede exponer media/instrucciones útiles:

```text
image
video
text/instruction
external media reference
```

Purposes conceptuales:

```text
hero
gallery
entrance
parking
arrival_instruction
accessibility
landmark
```

Los binarios deben vivir en object/media storage; Request Engine conserva referencias, metadata, captions, alt text y orden de presentación.

Esto permite que un website muestre fotos/video y que un agente pueda explicar verbalmente cómo llegar usando la misma fuente de verdad.

---

## 27. `Destination`: dónde debe cumplirse una Reservation específica

No confundir Location con la dirección del cliente.

```text
Location
= lugar operativo de la organización

Destination
= lugar concreto donde debe cumplirse esta Reservation
```

Ejemplo:

```text
Reservation: Emergency Plumbing Visit
Destination:
  customer address snapshot
  map/share URL if provided
  optional coordinates
  access notes
```

El Destination debe conservar snapshot histórico suficiente. Si posteriormente el Contact cambia su dirección, la Reservation histórica sigue indicando dónde debía prestarse el servicio.

---

## 28. `ServiceArea`

Field service necesita poder responder si una Destination es atendible.

Un `ServiceArea` puede aplicarse a organization, location, Offering o Resource/pool según el caso.

V2 debe comenzar con mecanismos simples y explícitos:

```text
named zone
city/province
postal code
radius
```

Polygons, travel-time constraints y routing geoespacial avanzado sólo cuando exista necesidad real.

---

## 29. `Dispatch`: mover capacidad hacia un Destination

Para field service, `Reservation` y `Dispatch` son conceptos distintos.

```text
Reservation
= capacity was committed

Dispatch
= assigned operational capacity is now being coordinated/moved toward Destination
```

Ejemplo:

```text
Request: leaking pipe
    ↓
Offering: Emergency Plumbing Visit
    ↓
Reservation: arrival window 1–4 PM
    ↓
Allocation: Technician Pool x1
    ↓
Assignment: Miguel + Vehicle 02
    ↓
Dispatch
    ↓
en_route
    ↓
arrived
    ↓
ServiceSession
    ↓
Fulfillment
```

Estados conceptuales iniciales:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No meter todos estos estados dentro de Reservation.

---

## 30. Dispatch status y tracking

Request Engine debe conservar los hechos operacionales que el usuario realmente necesita:

```text
assigned resource display info
dispatch status
estimated_arrival_at
tracking/share URL when available
latest meaningful position/reference when policy allows
last_updated_at
```

Puede emitir:

```text
dispatch.assigned
dispatch.en_route
dispatch.eta_updated
dispatch.arrived
service_session.started
service_session.completed
```

Un website puede mostrar un tracker, WhatsApp puede enviar una actualización y un voice agent puede responder el estado usando los mismos hechos.

### Raw GPS boundary

Request Engine **no debe convertirse en un time-series store de cada GPS ping**.

Si existe tracking continuo:

```text
technician app / GPS provider
        ↓
tracking/telemetry system
        ↓
meaningful current state / ETA / reference
        ↓
Request Engine
```

Puede conservar coordenadas recientes cuando sean útiles, pero no necesita almacenar el historial crudo de alta frecuencia.

---

## 31. Dispatch no es todavía un sistema universal de delivery

Un plomero desplaza una persona/vehículo hacia una Destination. Un retailer puede necesitar shipment, courier, pickup, packages y proof-of-delivery.

No forzar ambos dominios dentro de la misma entidad prematuramente.

Para V2:

```text
Dispatch
= operational resource movement for service execution
```

Un futuro módulo `Delivery` puede reutilizar primitivas como Destination, ETA, tracking references y status events cuando existan casos reales de entrega de bienes.

---

## 32. Payments

Request Engine puede coordinar pagos necesarios para cumplir un workflow, pero no debe convertirse en un PSP ni sistema contable.

Policies conceptuales:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Flujo:

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

Los detalles finales de `PaymentRequirement`, payment session/intent y payment record deben cerrarse en la siguiente exploración del dominio antes de considerar completo el vertical slice.

---

## 33. Forms / Intake

Primitivas iniciales:

```text
FormDefinition
FormSubmission
```

Los schemas de intake deben poder reutilizarse por:

```text
website forms
voice agents
WhatsApp
human UI
REST API
MCP/tool schemas
```

La presentación cambia; el contrato de negocio permanece.

---

## 34. API para software y tools para agentes

Una sola lógica autoritativa con superficies apropiadas:

```text
                  Application layer
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       REST API      Public API      Agent tools
          │              │              │
       portals         widgets        MCP/LLM
```

Ejemplos REST:

```text
GET  /v1/offerings
GET  /v1/locations
GET  /v1/locations/{id}
POST /v1/reservations/options
POST /v1/reservations/holds
POST /v1/reservations
GET  /v1/dispatches/{id}
```

Ejemplos agent tools:

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

Los agentes no necesitan razonar sobre resource graphs, locks, pool internals o raw GPS.

---

## 35. IA no es autoridad

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

Texto libre o una transcripción nunca modifican por sí solos reservations, pagos, assignments u otro estado crítico.

---

## 36. Workflow interno versus n8n

Regla:

> **Si eliminar una secuencia de pasos podría dejar inconsistente el estado autoritativo del negocio, esa lógica pertenece a Request Engine.**

Ejemplo interno:

```text
validate Offering
resolve Destination/service area
collect required data
check capacity
apply payment policy
confirm Reservation
```

Ejemplo externo:

```text
reservation.confirmed
      ↓
add spreadsheet row
send Slack notification
create marketing action
```

n8n puede servir como laboratorio de integraciones, no como workflow engine autoritativo.

---

## 37. Límites con CRM, ERP, analytics y optimizers

```text
CRM
Who is this person and what is our relationship?

Request Engine
What is needed, what must happen, and what operational state is authoritative?

ERP/accounting
What resources, money, inventory and internal financial operations exist?
```

Request Engine puede consumir analytics o routing como capabilities, pero no se convierte en telemetry platform, accounting system, inventory system ni global workforce optimizer.

Debe saber si existe capacidad suficiente y comprometerla correctamente. No necesariamente debe calcular el plan globalmente óptimo para decenas de técnicos.

---

## 38. Qué pertenece al core

### Tenancy e identidad operacional

- organizations;
- principals / credentials;
- contacts;
- organization-scoped configuration;
- locations como identidad operacional/presentación de lugares del negocio.

### Intent and work

- offerings;
- request types;
- requests;
- workflow selection/execution state;
- fulfillments.

### Platform primitives

- events;
- audit;
- idempotency;
- webhooks/outbox;
- API authentication/scopes;
- versioned contracts.

### Módulos iniciales fuera del core puro

- reservations / capacity;
- schedules / availability;
- forms / intake;
- dispatch / field execution;
- payments coordination.

Boundary de dominio no implica microservicio.

---

## 39. Qué NO pertenece al core

- healthcare-specific records/models;
- Chatwoot/Evolution/Meta provisioning;
- n8n workflows externos;
- LiveKit workers;
- LLM provider internals/prompts;
- SIP/PBX implementation;
- inventory completo;
- accounting/ERP;
- CRM completo;
- universal analytics/telemetry store;
- raw high-frequency GPS history;
- global route/workforce optimizer;
- universal delivery/shipping platform;
- universal workflow editor.

---

## 40. Multi-tenancy

Toda entidad tenant-owned se ejecuta dentro de organización resuelta desde principal/credential.

```text
credential
    ↓
organization + principal + scopes
    ↓
domain operation
```

Public/browser credentials y secret/server credentials son clases distintas. Nunca colocar organization secret keys en frontend público.

---

## 41. Eventos, outbox, idempotencia y trazabilidad

Una transacción interna no depende de sistemas externos.

```text
transaction commits
      ↓
domain event / outbox
      ↓
async external action
      ↓
idempotent callback
      ↓
reconciliation
```

Cada request/reservation debe permitir reconstruir:

```text
Who initiated this?
What was understood?
Which Offering was selected?
Which Location/Destination applied?
Which schedule/policies applied?
What capacity was considered/held/committed?
Which resources/pools were allocated or assigned?
What dispatch/execution occurred?
Which principal/tool performed each mutation?
What external events occurred?
What was the final outcome?
```

---

## 42. Invariantes temporales y de capacidad

- timestamps persistidos como instantes UTC;
- timezone IANA en schedules/locations que interpretan tiempo local;
- availability no equivale a Reservation;
- confirmation revalida capacidad transaccionalmente;
- schedule exceptions/holidays forman parte del cálculo efectivo;
- BusinessHours y AvailabilitySchedule son conceptos distintos;
- buffers y resources forman parte del conflicto real;
- reservations pueden consumir exclusive resources o capacity units;
- queue/window/hybrid son ciudadanos de primera clase;
- snapshots conservan condiciones históricas relevantes;
- side effects externos ocurren post-commit.

---

## 43. Public IDs e IDs externos

Ejemplos:

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

Google Maps place/share URLs, Stripe IDs, Twilio IDs, LiveKit identifiers u otros IDs externos son referencias; nunca identidad primaria del dominio.

---

## 44. Conversations vs Requests

> **Conversation is context. Request is work.**

Una conversation puede originar múltiples Requests y cerrarse sin terminar sus lifecycles.

---

## 45. Fulfillment

`Fulfillment` conecta intención con resultado verificable.

```text
request_quote
    → quoteId

reserve_offering
    → reservationId

request_callback
    → callbackTaskId

emergency_service
    → reservationId + dispatch/service evidence
```

---

## 46. Vertical slice obligatorio de V2

### Demo Barbershop

Debe demostrar:

```text
Offering + ResourceRequirements
BusinessHours Mon–Fri / Saturday reduced / Sunday closed
holiday + special-hours exception
resource-specific availability
scheduled
queue
hybrid
walk-in
exclusive resources
capacity revalidation
Location with address + map link + arrival media/instructions
payment policy
```

### Demo Plumbing

Debe demostrar:

```text
Offering + intake
24/7 or Offering-specific availability independent from office BusinessHours
arrival window
ServiceArea validation
Destination snapshot
technician pool allocation
late concrete technician/vehicle assignment
Dispatch planned → en_route → arrived
ETA/status updates
map/share references where useful
ServiceSession
optional deposit/payment
```

El objetivo es probar que las abstracciones sobreviven a modelos operacionales diferentes sin lógica vertical en el core.

---

## 47. Lo que se preserva de V1

1. multi-tenancy explícito;
2. public IDs separados de IDs internos;
3. UTC + IANA timezones;
4. recurring schedules + exceptions/closures;
5. holiday-aware availability without hardcoded business closure semantics;
6. idempotency keys;
7. revalidación transaccional antes de comprometer capacidad;
8. snapshots históricos relevantes;
9. outbox / async side effects;
10. callbacks idempotentes y tipados;
11. audit separado de logs;
12. scoped/revocable API keys;
13. external IDs como referencias;
14. agentes reciben tools deterministas;
15. system of record independiente de Chatwoot, Evolution, n8n o LiveKit.

---

## 48. Lo que V2 debe evitar

1. vertical-specific models en el core;
2. convertir `Request`, `Offering`, `Resource` o `Reservation` en blobs que significan cualquier cosa;
3. exact-time appointments como única forma de capacity commitment;
4. una única `opening_hours` incapaz de modelar reality/overrides;
5. tratar un feriado como cierre universal obligatorio;
6. tratar Location y customer Destination como el mismo concepto;
7. almacenar raw GPS high-frequency data sin razón operacional;
8. convertir Dispatch en un universal logistics platform prematuramente;
9. construir un workforce optimizer global;
10. n8n como dependencia autoritativa;
11. OpenAPI manual separado de schemas reales;
12. writes por cada availability search;
13. editor universal de workflows.

---

## 49. Criterio para añadir features

Antes de añadir algo al core o módulos iniciales:

1. ¿Ayuda a representar una intención procesable?
2. ¿Ayuda a describir qué ofrece la organización?
3. ¿Ayuda a determinar si existe/puede comprometerse capacidad?
4. ¿Ayuda a ejecutar o demostrar el resultado?
5. ¿Necesita estado autoritativo dentro de Request Engine?
6. ¿Es común a múltiples verticales?
7. ¿Puede vivir mejor como integración/sistema especializado?
8. ¿Tenemos un caso real que lo exige ahora?

---

## 50. North Star

> **A headless, multi-tenant transactional request engine that turns customer or system intent into deterministic workflows, valid capacity commitments and verifiable outcomes, while exposing the operational context needed to complete them across locations, queues and field service.**

En español:

> **Un motor transaccional headless y multiempresa que transforma intención en workflows deterministas, compromisos válidos de capacidad y resultados verificables, conservando el contexto operacional necesario para cumplirlos en locations, colas y servicios en campo.**

Vocabulario canónico:

```text
Offering      = what can be obtained
Request       = what is wanted now
Workflow      = what must happen
Resource      = what can provide capacity
Capacity      = how much it can provide
Requirement   = what capacity an Offering needs
Allocation    = what capacity a Reservation committed
Assignment    = which concrete resource will execute
Schedule      = when capacity may exist
Location      = where the organization operates/receives
Destination   = where this specific work must occur
Reservation   = what capacity is committed
Admission     = how service access happens
Dispatch      = how assigned capacity moves toward Destination
ServiceSession = what actually ran
Fulfillment   = what outcome actually happened
```

Si una feature no ayuda a representar estas responsabilidades, mantener sus invariantes o producir trazabilidad operacional útil, probablemente pertenece fuera de Request Engine.
