# Request Engine — definición de producto y norte arquitectónico

> **Estado:** documento fundacional para Request Engine V2.
>
> Este documento define **qué es Request Engine, qué no es, cuáles son sus primitivas de dominio y qué límites deben guiar su evolución**. Las decisiones concretas de infraestructura pertenecen a ADRs y a `docs/01-architecture-v2.md`; no deben redefinir el producto.
>
> Esta versión incorpora el stress test de dominio realizado después de madurar Reservations, Resources, Locations/Dispatch y Payments. Las correcciones resultantes son parte de la foundation, no features verticales.

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

> **Una persona, sistema o agente solicita un resultado a una organización. Request Engine convierte esa intención en trabajo estructurado, determina el workflow permitido, coordina capabilities deterministas y mantiene estado autoritativo hasta producir uno o más resultados verificables.**

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

Una developer console interna para inspeccionar organizations, credentials, contacts/participants, offerings/selections, requests, reservations, resources, locations, dispatches, payments, disruptions, events y webhooks es compatible con esta definición; no convierte a la UI en el centro del producto.

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

1. ¿Quién está pidiendo algo y para quién?
2. ¿Qué quiere conseguir?
3. ¿Qué Offering u Offerings satisfacen esa intención?
4. ¿Qué cantidad, configuración o participantes están involucrados?
5. ¿Qué información falta?
6. ¿Dónde puede prestarse o recibirse el servicio?
7. ¿Cuándo existe capacidad real?
8. ¿Qué recursos son necesarios y en qué cantidad?
9. ¿Qué reglas y políticas aplican?
10. ¿Qué workflow debe ejecutarse?
11. ¿Qué requiere confirmación, pago o intervención humana?
12. Si existe un pago, ¿cuánto se debe, quién paga, cómo puede pagarse y qué evidencia autoritativa confirma que el dinero realmente fue recibido?
13. Si el servicio ocurre fuera de una location, ¿qué debe desplazarse y hacia dónde?
14. Si desaparece capacidad ya comprometida, ¿cómo se recupera sin borrar el commitment original?
15. ¿Qué resultado o resultados concretos satisficieron finalmente la intención?

Request Engine proporciona una capa común para responder esas preguntas sin duplicar lógica de negocio en cada website, bot, flujo de n8n, portal o agente de voz.

---

## 4. `Request`: unidad de intención procesable

Un `Request` representa **una intención concreta y procesable que una organización debe atender**.

Ejemplos:

```text
"Quiero una limpieza dental"
"Necesito que un técnico revise una fuga hoy"
"Quiero corte y barba"
"Quiero una cotización"
"Necesito que me llamen"
"Quiero una evaluación de QuisqueyaTech"
"Quiero cambiar mi reservación"
```

`Request` no significa “cualquier dato del sistema”. No representa un pago, una métrica web, un producto ni una persona.

> **Request puede representar cualquier necesidad procesable, no cualquier cosa existente.**

Una conversación puede producir cero, uno o varios Requests. Un Request puede sobrevivir al canal que lo originó.

No asumir:

```text
1 Request = 1 Offering = 1 Reservation = 1 Fulfillment
```

Las cardinalidades reales son más flexibles.

---

## 5. `Principal`, `Contact` y participantes: actor no equivale a persona atendida

El stress test demostró que un único `contact_id` no representa correctamente situaciones reales.

Separar:

```text
Principal
= actor autenticado que ejecutó una mutación

Contact
= identidad de negocio de una persona/contacto

Participant role
= papel que un Contact cumple dentro de un Request o Reservation
```

Ejemplo:

```text
AI agent / employee Principal
        │ acts on behalf of
        ▼
María — requester / guardian
José  — recipient
Pedro — payer
```

El Principal sigue siendo la fuente de audit para “quién ejecutó la acción”. Los participant roles explican “qué papel tenía cada Contact en el trabajo”.

Roles iniciales útiles:

```text
requester
recipient
payer
guardian
authorized_contact
```

Una persona puede cumplir varios roles.

Conceptualmente:

```text
RequestParticipant
  Request + Contact + role(s)

ReservationParticipant
  Reservation + Contact + role(s) + relevant snapshot/context
```

No introducir conceptos verticales como `patient`, `student` o `tenant` en el core; una UX vertical puede mapear `recipient` a la palabra apropiada.

---

## 6. `Offering`: qué ofrece la organización

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

pero no debe producir una mega-entidad con cientos de campos nullable.

Un `package` real puede ser un Offering con semántica comercial propia. Eso es distinto de que un cliente seleccione varios Offerings independientes en un mismo Request.

---

## 7. `OfferingSelection`: qué Offerings concretos forman parte del Request

Un Request puede involucrar cero, uno o varios Offerings.

```text
Request
├── Haircut x1
├── Beard Trim x1
└── Shampoo x1
```

No obligar a crear un Offering artificial `Haircut + Beard + Shampoo` para cada combinación posible.

`OfferingSelection` representa **una selección concreta de un Offering dentro de una intención**, incluyendo cuando corresponda:

```text
offering
quantity
configuration / validated input
recipient participant(s)
selection status
relevant snapshot/reference
```

Ejemplos:

```text
Haircut x1 → recipient José
Haircut x1 → recipient Miguel
Beard Trim x1 → recipient Pedro
```

Un RequestType como `request_callback` puede no tener OfferingSelection. Un Request de compra/reserva puede tener varias.

Esta separación permite que el workflow decida si varias selections:

- comparten una Reservation;
- requieren Reservations separadas;
- generan purchase/quote Fulfillments distintos;
- se satisfacen parcialmente.

---

## 8. `RequestType`: qué quiere lograr el solicitante

```text
Offering         = what the organization provides
OfferingSelection = which Offering(s) this Request is about
RequestType      = what the requester wants to accomplish
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
OfferingSelections
    +
Participants
    +
Organization policies
    +
Request context
    ↓
Workflow version
```

No crear tipos universales como `book_haircut`, `book_beard_trim`, etc.

---

## 9. Modelo mental del sistema

```text
                               CHANNELS

       Website       WhatsApp       Voice AI       Human UI       API
          │              │              │              │            │
          └──────────────┴──────────────┴──────────────┴────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │       INTAKE        │
                              │ identity / context  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                      Participants ───► REQUEST ◄── OfferingSelections
                                         │
                                  type + policy
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
                                         │
                                    Payments?
                                         │
                                         ▼
                                   Dispatch?
                                         │
                                         ▼
                                ServiceSession(s)?
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   FULFILLMENT(S)    │
                              │ outcome + evidence  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                                    EVENTS / AUDIT
```

Los canales son adapters. No poseen la lógica autoritativa del negocio.

---

## 10. Workflow

Request Engine responde:

> Dado este `Request`, sus selections/participants, la organización, sus policies y el contexto actual, ¿qué debe ocurrir ahora?

Un workflow puede:

1. pedir información faltante;
2. resolver/validar OfferingSelections;
3. consultar una capability;
4. ofrecer opciones;
5. crear un `CapacityHold`;
6. ejecutar una operación;
7. crear un `PaymentRequirement`;
8. solicitar confirmación o pago;
9. esperar verificación financiera, capacidad, callback o intervención humana;
10. crear/coordinar un Dispatch;
11. recuperar una Reservation afectada por disruption;
12. completar uno o varios resultados;
13. fallar de forma recuperable;
14. hacer handoff.

No construir inicialmente BPMN, un editor universal ni un clon de n8n/Temporal. La primera versión favorece workflows tipados, versionados y testeables en código/configuración.

---

## 11. Capabilities

Ejemplos:

```text
reservations.searchAvailability
reservations.createHold
reservations.confirm
reservations.reschedule
reservations.cancel
reservations.checkIn
reservations.joinQueue
reservations.recoverDisruption

locations.getDetails
locations.getCurrentHours

dispatch.assign
dispatch.markEnRoute
dispatch.markArrived

payments.getOptions
payments.createAttempt
payments.submitEvidence
payments.getStatus
payments.verifyReceived
payments.requestRefund

quotes.createDraft
quotes.send
contacts.upsert
notifications.send
handoff.createTask
```

Un workflow consume capabilities. Los canales y agentes consumen Request Engine.

---

## 12. `Reservation`: compromiso de capacidad

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

Una Reservation no es un contenedor universal de todos los estados operacionales posteriores.

---

## 13. `ReservationItem` y cardinalidades Request ↔ Reservation

Una Reservation puede comprometer capacidad para una o varias OfferingSelections.

`ReservationItem` representa **qué Offering/selection y qué cantidad están cubiertos por esa Reservation**.

Conceptualmente puede contener:

```text
reservation
offering
offering_selection reference nullable
quantity
recipient/participant references
relevant Offering/policy snapshot
```

Esto permite:

```text
1 Request → multiple Reservations
1 Request → multiple OfferingSelections
1 Reservation → multiple ReservationItems
1 Reservation → selections de un mismo Request o, cuando el workflow lo justifica, de Requests relacionados
```

Una Reservation administrativa directa puede existir sin un Request previo, pero debe seguir teniendo ReservationItems/Offering identity suficiente para explicar qué capacidad fue comprometida.

No crear foreign keys o invariantes que impongan accidentalmente una relación 1:1 entre Request y Reservation.

---

## 14. Lifecycle de Reservation versus estado operacional

El stress test reveló que mezclar `checked_in`, `in_service`, `en_route`, etc. dentro de `Reservation.status` duplica otros lifecycles y permite combinaciones imposibles.

Separar:

```text
Reservation commitment status
= estado del compromiso de capacidad

Operational projection / health
= qué está ocurriendo operacionalmente y si el commitment sigue siendo cumplible
```

Commitment statuses iniciales deliberadamente pequeños:

```text
confirmed
cancelled
completed
no_show
expired   [sólo cuando una policy válida haga que el commitment caduque]
```

`CapacityHold` cubre la etapa previa a confirmation; no existe `Reservation.status = held`.

Estados como:

```text
checked_in
waiting_in_queue
en_route
in_service
```

pertenecen a `CheckIn`, `QueueEntry`, `Dispatch`, `ServiceSession` o a una read projection compuesta.

Operational health puede exponerse como:

```text
valid
at_risk
blocked
```

sin cambiar automáticamente el commitment status.

Ejemplo:

```text
Reservation.commitment = confirmed
Reservation.operational_health = at_risk
```

si el barber asignado se enferma pero la organización todavía puede intentar reallocation.

---

## 15. Availability, `ReservationOption`, `CapacityHold` y confirmación

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

Revalida capacity, quantity rules, participants, policies y ResourceRequirements transaccionalmente.

Una respuesta previa de availability nunca garantiza que la capacidad siga disponible.

---

## 16. `AdmissionPolicy`

Define cómo una Reservation entra al servicio.

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

También permite coexistencia controlada de Reservations programadas y walk-ins sobre capacidad compartida.

La AdmissionPolicy puede determinar **cuándo** un atraso se convierte en no-show o en entrada a queue; las consecuencias financieras/cancelación pertenecen a ReservationPolicy.

---

## 17. Queue no es Waitlist

Separar explícitamente:

```text
QueueEntry
= customer has a capacity commitment/admission context and is waiting operationally

WaitlistEntry
= customer wants future capacity that has NOT been committed
```

Un WaitlistEntry:

- no consume capacity;
- no es Reservation;
- conserva Offering/preferences/date-window/location/party-size relevantes;
- puede producir un CapacityHold/offer cuando aparece capacidad;
- sólo se convierte en Reservation después de aceptación y confirmación válida.

Flujo conceptual:

```text
no capacity
   ↓
WaitlistEntry
   ↓
capacity becomes available
   ↓
match + temporary CapacityHold/offer
   ↓
customer accepts
   ↓
Reservation
```

Waitlist puede quedar fuera del primer vertical slice de implementación, pero su boundary es parte de la foundation para evitar abusar de Queue.

---

## 18. `CheckIn`, `QueueEntry` y `ServiceSession`

Separar:

```text
Reservation    = committed/planned capacity
CheckIn        = presence/readiness
QueueEntry     = dynamic operational queue state
ServiceSession = actual execution
```

No sobrescribir lo planificado con tiempos reales.

```text
Reservation planned: 10:00–10:30
CheckIn:             10:07
ServiceSession:      10:14–10:52
```

Una Reservation queue-based puede crearse para un walk-in en el momento de llegada.

Una Reservation puede producir **cero, una o varias ServiceSessions**. Esto permite procesos multietapa sin introducir prematuramente `ReservationSegment`.

Ejemplo:

```text
Reservation 10:00–10:45

Allocation X-Ray Tech     10:00–10:15
Allocation X-Ray Machine  10:00–10:15
Allocation Dentist        10:15–10:45
Allocation Treatment Room 10:15–10:45

ServiceSession #1: X-Ray
ServiceSession #2: Consultation
```

---

## 19. `Resource`: qué puede proveer capacidad

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

> **Algo es Resource cuando su disponibilidad/capacidad participa de forma autoritativa en la posibilidad de cumplir una Reservation.**

---

## 20. `ResourceCapability`

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

---

## 21. Capacity

Capacity responde:

> **¿Cuánto puede proveer un Resource simultáneamente o dentro del modelo operacional relevante?**

Para V2 se mantienen modelos deliberadamente pequeños:

```text
exclusive
units
```

### `exclusive`

Una Reservation consume el Resource de forma exclusiva en el período relevante.

```text
barber
dentist
chair
vehicle
machine
```

### `units`

El Resource expone N unidades reservables y una Reservation consume cierta cantidad.

```text
class seats
tour seats
shared support capacity
reservable equipment pool
```

No usar capacity como inventario comercial general. Request Engine debe garantizar capacidad reservable, no convertirse en inventory management ni en un scheduler multidimensional tipo cluster/workforce optimizer.

---

## 22. `ResourceRequirement` y quantity rules

`ResourceRequirement` describe **qué capacidad necesita un Offering**, no qué Resource concreto se asignará.

Una cantidad fija no cubre todos los casos. V2 admite quantity rules pequeñas y deterministas:

```text
fixed
per_selection_unit
per_participant
from_validated_input
```

Ejemplos:

```text
Haircut
  barber: fixed/per_selection_unit según modelo de simultaneidad
  chair:  per_selection_unit

Yoga Class
  instructor: fixed 1
  seat_capacity: per_participant

Equipment Rental
  equipment_units: from_validated_input(quantity)
```

`from_validated_input` sólo puede referenciar un campo tipado/validado conocido. No ejecutar arbitrary expressions, JavaScript, SQL ni un DSL universal.

La cantidad efectiva debe quedar materializada/snapshotted cuando se compromete capacity, para que cambios posteriores de input/policy no reescriban la historia.

---

## 23. `ResourceAllocation` y Assignment

Separar:

```text
Requirement
= what capacity an Offering needs

Allocation
= what capacity a Reservation committed

Assignment
= which concrete operational resource will execute
```

Ejemplo:

```text
Reservation res_123
allocates:
  Carlos x1
  Chair 2 x1
```

Field service puede hacer late binding:

```text
Reservation: tomorrow 1–4 PM
Allocation: North Technician Pool x1
Later assignment: Miguel + Vehicle 02
```

Una Allocation puede cubrir sólo parte del intervalo total de la Reservation. Todas las allocations no necesitan compartir exactamente `planned_from/planned_to`.

Cuando cambia un Resource:

```text
Vehicle02 allocation → released/replaced
Vehicle05 allocation → active
```

No sobrescribir historia como si Vehicle02 nunca hubiera estado asignado.

Statuses/lifecycle de allocation deben poder conservar al menos:

```text
active
released
replaced
```

más audit/eventos apropiados.

---

## 24. Resource pools y groups

No confundir:

```text
ResourceGroup
= organizational/query grouping

Resource(kind=pool)
= reservable aggregate capacity
```

Un grupo ayuda a descubrir recursos. Un pool permite comprometer capacidad agregada antes de asignar un miembro concreto.

---

## 25. Principio del scheduler

Availability no debe limitarse a “buscar citas libres”.

Debe responder:

> **¿Existe una combinación válida de tiempo, policy, participants, quantities y capacity que satisfaga todos los ResourceRequirements de los ReservationItems?**

```text
OfferingSelections
      ↓
ReservationItems candidate
      ↓
ResourceRequirements + quantity rules
      ↓
Schedules + Location/ServiceArea + policies
      ↓
compatible Resources / pools
      ↓
remaining capacity
      ↓
ReservationOption
```

Request Engine garantiza capacidad válida y compromisos correctos. **No tiene que resolver el plan global óptimo de una fuerza laboral completa.** Routing global, optimización de costos y planificación avanzada pueden delegarse a sistemas especializados.

---

## 26. Tiempo: `BusinessHours` y `AvailabilitySchedule`

No reducir tiempo a una columna `opening_hours`.

Separar:

```text
BusinessHours
= cuándo una organización/Location está normalmente abierta o disponible al público

AvailabilitySchedule
= cuándo una capacidad/Offering/Resource puede realmente reservarse
```

Pueden diferir.

```text
Office BusinessHours:
Mon–Fri 09:00–17:00

Emergency Plumbing AvailabilitySchedule:
24/7
```

Un schedule debe soportar múltiples intervalos por día y timezone IANA explícita.

```text
Mon–Fri: 09:00–18:00
Saturday: 09:00–12:00
Sunday: closed
```

Y split shifts:

```text
Monday:
09:00–12:00
14:00–18:00
```

---

## 27. Jerarquía y composición de schedules

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

Un Resource puede restringir el horario heredado, pero no debe expandir silenciosamente una Location/organization cerrada.

```text
Organization: Sunday closed
Carlos: Sunday available
```

no abre automáticamente el negocio. Una apertura extraordinaria debe declararse explícitamente.

---

## 28. `ScheduleException` y `HolidayCalendar`

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

`HolidayCalendar` conserva la capacidad de V1 para feriados/cierres sin hardcodear “feriado = cerrado”.

Policies:

```text
closed_by_default
normal_schedule
special_hours
```

También deben existir fechas custom del negocio:

```text
staff training
company event
inventory day
private closure
```

Una ScheduleException nueva cambia disponibilidad futura, pero **no cancela ni reescribe silenciosamente Reservations ya confirmadas**. Si invalida una allocation existente, produce un disruption/recovery flow.

---

## 29. `Location`: dónde opera o recibe la organización

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

Una organization puede tener múltiples Locations, y Offerings/Resources pueden estar disponibles sólo en ciertas Locations.

---

## 30. Ubicación pensada para usuarios reales y `LocationMedia`

La representación práctica preferida para compartir una Location puede ser:

```text
Google Maps URL
Google Maps place/share link
map pin URL
human-readable address
arrival instructions
landmark text
```

`latitude`/`longitude` pueden existir como datos interoperables opcionales para mapas, validación o integraciones, pero **no son la experiencia primaria que se presenta al usuario**.

> **Store enough structured location data for machines, but expose/share the representation humans actually use.**

No acoplar identidad de Location a Google Maps.

Una Location puede exponer media/instrucciones:

```text
image
video
text/instruction
external media reference
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

Los binarios viven en object/media storage; Request Engine conserva references, metadata, captions, alt text, transcript cuando corresponda y orden de presentación.

---

## 31. `Destination`: dónde debe cumplirse una Reservation específica

No confundir Location con dirección del cliente.

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

El Destination conserva snapshot histórico suficiente.

Cambiar Destination después de confirmar o iniciar Dispatch es una operación de negocio, no una edición ciega:

```text
ChangeDestination
    ↓
validate ServiceArea
    ↓
re-evaluate pricing/capacity/assignment/ETA where applicable
    ↓
confirm change
    ↓
audit old + new snapshot
```

---

## 32. `ServiceArea`

Field service necesita responder si una Destination es atendible.

V2 comienza con mecanismos simples:

```text
named zone
city/province
postal code
radius
```

Puede aplicarse a organization, Location, Offering o Resource/pool según el caso.

Polygons, travel-time constraints y routing geoespacial avanzado sólo cuando exista necesidad real.

---

## 33. `Dispatch`: mover capacidad hacia un Destination

Para field service:

```text
Reservation
= capacity was committed

Dispatch
= assigned operational capacity is being coordinated/moved toward Destination
```

Ejemplo:

```text
Request: leaking pipe
    ↓
OfferingSelection: Emergency Plumbing Visit
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

Estados iniciales:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No meter estos estados dentro de Reservation.

Una Reservation puede producir más de un Dispatch cuando una recuperación operacional lo requiera; la implementation no debe imponer 1:1 accidental si el caso real necesita redispatch.

---

## 34. Dispatch status, tracking y delivery boundary

Request Engine conserva hechos útiles:

```text
assigned resource display info
dispatch status
estimated_arrival_at
tracking/share URL
latest meaningful position/reference when policy allows
last_updated_at
```

Puede emitir:

```text
dispatch.assigned
dispatch.en_route
dispatch.eta_updated
dispatch.arrived
```

No es un time-series store de GPS.

```text
technician app / GPS provider
        ↓
tracking/telemetry system
        ↓
meaningful current state / ETA / reference
        ↓
Request Engine
```

Un futuro módulo `Delivery` puede reutilizar Destination, windows, tracking references y events, pero shipment/packages/courier/proof-of-delivery sólo entran con un caso real.

---

## 35. `ReservationPolicy`: reglas después del commitment

`PaymentPolicy` responde **cómo/cuándo cobrar**. `AdmissionPolicy` responde **cómo/cuándo entrar al servicio**. Ninguna debe decidir por sí sola qué ocurre cuando una Reservation se cancela, reprograma o termina en no-show.

Introducir `ReservationPolicy` como composición versionada de:

```text
CancellationPolicy
ReschedulePolicy
NoShowPolicy
```

Debe poder evaluar al menos:

```text
who initiated the action: customer | business | system
reason code/context
time remaining before planned service
current commitment/admission state
applicable policy version
```

Ejemplos:

```text
customer cancellation >24h → allow + full refund directive
customer cancellation <2h  → allow + deposit forfeiture
business cancellation      → allow + full refund + rebooking path
no-show                     → release capacity + apply configured financial consequence
```

ReservationPolicy **decide la consecuencia de negocio**. Payments ejecuta consecuencias financieras mediante `PaymentRequirement`, `Refund`, allocation/reconciliation, etc.; ReservationPolicy nunca edita directamente una PaymentTransaction.

Policies deben conservar snapshot/version relevante al confirmar la Reservation.

Overrides humanos requieren permission explícita y audit.

---

## 36. `ReservationDisruption`: commitment confirmado pero capacidad en riesgo

Una Reservation confirmada no desaparece porque posteriormente falle un Resource, cierre una Location o aparezca una excepción operacional.

Ejemplos:

```text
Carlos gets sick
Chair 2 breaks
Vehicle 02 becomes unavailable
Location closes unexpectedly
```

Flujo:

```text
capacity-affecting change
       ↓
identify affected active allocations/reservations
       ↓
ReservationDisruption
       ↓
operational_health = at_risk
       ↓
attempt safe reallocation/reassignment
       │
       ├── success → health = valid; preserve allocation history
       │
       └── failure → health = blocked
                     ↓
               reschedule / cancel / human recovery
```

`ReservationDisruption` representa un caso operacional durable/auditable cuando recovery no es instantáneo.

Razones iniciales pueden incluir:

```text
resource_unavailable
location_unavailable
capacity_reduced
schedule_exception
assignment_failed
service_area_changed
other_operational
```

El commitment sigue `confirmed` mientras la policy/workflow no lo cambie explícitamente.

---

## 37. Payments: obligación, intento, evidencia y dinero verificado

Request Engine puede coordinar pagos necesarios para cumplir un workflow, pero **no es un PSP, banco, sistema contable ni ledger general**.

```text
Pricing
= cuánto debe cobrarse y por qué

Payments
= cómo se intenta cobrar, verificar y aplicar ese dinero

Accounting / invoicing
= representación contable/fiscal del negocio
```

> **Intención de pagar ≠ evidencia de pago ≠ dinero recibido.**

Un screenshot, recibo subido, redirect de éxito del browser o mensaje del cliente nunca son por sí solos prueba autoritativa de que el dinero llegó.

### 37.1 `PaymentPolicy`

Regla reusable que describe cómo/cuándo un Offering/workflow exige o permite cobrar.

Modes iniciales:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Puede resolver:

```text
amount_rule
payment_timing
reservation_gate
accepted_methods
capacity_strategy
expiration_behavior
```

Capacity strategies:

```text
hold_until_payment
revalidate_after_payment
confirm_then_collect
```

### 37.2 `PaymentRequirement`

Obligación monetaria concreta para un propósito.

```text
purpose
Money(amount + currency)
status
due_at
payer participant/contact when known
policy snapshot
```

Estados:

```text
open
partially_satisfied
satisfied
waived
cancelled
```

`overdue` puede derivarse.

Un Requirement puede estar asociado a Request, Reservation y/o contexto de OfferingSelections; no asumir que toda obligación pertenece a un único item comercial.

### 37.3 `Money`

Toda cantidad transporta amount + currency. No floating point binario. No FX implícito.

### 37.4 `PaymentMethodConfiguration` y providers

Cada organization configura sus métodos.

Method families:

```text
card
bank_transfer
cash
wallet
external
custom
```

Provider/integration es distinto:

```text
stripe
paypal
square
azul
bank_api_x
manual
custom_provider
```

No introducir provider-specific branches en domain code.

### 37.5 `PaymentAttempt`

Un Requirement puede tener múltiples Attempts.

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

External provider IDs son referencias, nunca identidad canónica.

### 37.6 `PaymentInstruction`

Describe lo que el pagador debe hacer y conserva snapshot.

Transferencia:

```text
bank
account holder
account/display details
account type
amount/currency
unique transfer reference
expiration/customer message
```

Otros métodos pueden devolver redirect URL, QR, POS/cash instructions, etc.

### 37.7 Bank transfer y `PaymentEvidence`

```text
PaymentRequirement
      ↓
PaymentAttempt: bank_transfer
      ↓
PaymentInstruction
      ↓
customer transfers money
      ↓
PaymentEvidence? [optional]
      ↓
bank API/feed OR authorized manual independent verification
      ↓
PaymentTransaction settled
      ↓
PaymentAllocation
      ↓
Requirement satisfied/partially_satisfied
```

`PaymentEvidence` puede ser receipt image/PDF/reference/claimed data.

Estados:

```text
submitted
under_review
accepted_as_evidence
rejected
```

> **Accepted evidence is still not money received.**

Blobs son privados; access audited/scoped. File hash puede señalar reutilización, no declarar fraude automáticamente.

### 37.8 Verificación automática y manual

Fuentes autoritativas:

```text
provider_webhook
provider_api
bank_feed
bank_api
manual_bank_verification
cash_verification
external_system
```

Sin integración bancaria:

```text
Evidence submitted
      ↓
verification_pending
      ↓
authorized principal checks bank independently
      ↓
PaymentTransaction(source=manual_bank_verification)
```

La acción humana significa “verifiqué el dinero en una fuente independiente”, no “el screenshot parece verdadero”.

Requiere scope como `payments.verify` y audit.

Si no se encuentra el dinero:

```text
payment.verification_failed
```

El workflow notifica/reintenta/ofrece otro método o escala.

### 37.9 `PaymentTransaction`

Movimiento financiero autoritativamente observado/confirmado.

```text
amount
currency
status
source
external_reference
occurred_at / received_at
verified_by nullable
```

Estados financieros:

```text
pending
authorized
settled
failed
reversed
```

Default: sólo dinero `settled` + allocated satisface Requirements.

`authorized` no equivale a captured/received salvo policy explícita futura.

No borrar historia frente a reversal/return/dispute.

### 37.10 `PaymentAllocation`

```text
PaymentTransaction
      ↓
PaymentAllocation
      ↓
PaymentRequirement
```

Soporta:

- partial payments;
- múltiples Transactions para un Requirement;
- una Transaction aplicada a varios Requirements;
- overpayment/unallocated funds.

Nunca modelar simplemente `paid=true`.

### 37.11 `ReconciliationCase`

Si existen fondos pero el matching no es seguro, no adivinar.

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

### 37.12 Pago tardío versus capacity

Un pago confirmado no resucita automáticamente capacidad expirada.

```text
CapacityHold expires
PaymentTransaction settles later
      ↓
money remains real
Reservation remains unconfirmed
      ↓
revalidate / offer alternative / refund / explicit credit / human reconciliation
```

### 37.13 Cash y métodos externos

Cash usa el mismo modelo:

```text
PaymentAttempt(cash)
      ↓
authorized principal receives cash
      ↓
PaymentTransaction(cash_verification)
      ↓
PaymentAllocation
```

### 37.14 Success UI no es autoridad

Nunca considerar `/payment-success` como prueba financiera.

Authority:

```text
signed provider webhook
server-to-server provider API
bank feed/API
authorized independent manual verification
```

Callbacks: signature validation, anti-replay, idempotency.

### 37.15 Refunds, voids y reversals

`Refund` tiene lifecycle propio y puede ser parcial:

```text
requested
processing
succeeded
failed
cancelled
```

Void/cancel de autorización no capturada no es Refund.

No sobrescribir PaymentTransaction original. Financial history es append-oriented/auditable.

### 37.16 Fulfillment y financial settlement son lifecycles independientes

Si un servicio fue completado y posteriormente ocurre chargeback/reversal:

```text
ServiceSession remains historical fact
Fulfillment remains historical fact
PaymentTransaction/reversal changes financial state
PaymentRequirement may become outstanding again
```

No “deshacer” la realidad operacional para encajar un cambio financiero.

### 37.17 Límites y seguridad

```text
PaymentRequirement ≠ Invoice
PaymentTransaction ≠ accounting ledger entry
```

No almacenar PAN/CVV. Provider secrets fuera de frontend. PaymentEvidence privado. Verification/refund/reconciliation con scopes separados. IA puede explicar instrucciones y consultar status, pero no declarar fondos recibidos ni aceptar screenshots como payment authority.

---

## 38. Forms / Intake

Primitivas iniciales:

```text
FormDefinition
FormSubmission
```

Schemas reutilizables por website forms, voice agents, WhatsApp, human UI, REST API y MCP/tool schemas.

La presentación cambia; el contrato de negocio permanece.

---

## 39. API para software y tools para agentes

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
POST /v1/requests
POST /v1/reservations/options
POST /v1/reservations/holds
POST /v1/reservations
GET  /v1/reservations/{id}/status
GET  /v1/dispatches/{id}
GET  /v1/payment-requirements/{id}
POST /v1/payment-requirements/{id}/attempts
POST /v1/payment-attempts/{id}/evidence
```

Agent tools orientadas a objetivos:

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

Agentes no necesitan razonar sobre relationship tables, resource graphs, locks, pool internals, raw GPS, PSP internals o bank reconciliation internals.

---

## 40. IA no es autoridad

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

Texto libre o una transcripción nunca modifican por sí solos Reservations, payments, assignments u otro estado crítico.

En payments:

```text
LLM can explain payment instructions
LLM can collect evidence/reference
LLM can query payment status

LLM cannot declare funds received
LLM cannot satisfy PaymentRequirement from screenshot/text alone
LLM cannot perform refund/verification without authorized capability + scope
```

Participant roles y OfferingSelections también deben llegar al engine como estructuras validadas, no como semántica implícita escondida en conversación libre.

---

## 41. Workflow interno versus n8n

> **Si eliminar una secuencia de pasos podría dejar inconsistente el estado autoritativo del negocio, esa lógica pertenece a Request Engine.**

Ejemplo interno:

```text
validate OfferingSelections/participants
resolve Destination/service area
collect required data
resolve quantity rules
check capacity
apply ReservationPolicy/PaymentPolicy
create PaymentRequirement when required
verify authoritative payment outcome
apply payment to requirement
confirm/recover/cancel Reservation according to policy
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

## 42. Límites con CRM, ERP, analytics y optimizers

```text
CRM
Who is this person and what is our relationship?

Request Engine
What is needed, for whom, what must happen, and what operational/payment state is authoritative?

ERP/accounting
What resources, money, inventory and financial operations exist across the enterprise?
```

Request Engine puede consumir analytics, routing, banks o PSPs como capabilities/integrations, pero no se convierte en telemetry platform, accounting system, inventory system, bank, PSP ni global workforce optimizer.

Debe saber si existe capacidad suficiente y comprometerla correctamente. No necesariamente debe calcular el plan globalmente óptimo.

Debe saber si una obligación de pago fue satisfecha de forma confiable. No necesita convertirse en ledger contable general.

---

## 43. Qué pertenece al core y módulos iniciales

### Tenancy e identidad operacional

- organizations;
- principals / credentials;
- contacts;
- participant roles/associations;
- organization-scoped configuration;
- locations.

### Intent and work

- offerings;
- OfferingSelections;
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

- reservations / capacity / ReservationItems;
- schedules / availability;
- ReservationPolicy / disruptions;
- forms / intake;
- dispatch / field execution;
- payments coordination.

Boundary de dominio no implica microservicio.

---

## 44. Qué NO pertenece al core

- healthcare-specific records/models;
- Chatwoot/Evolution/Meta provisioning;
- n8n workflows externos;
- LiveKit workers;
- LLM provider internals/prompts;
- SIP/PBX implementation;
- inventory completo;
- accounting/ERP/general ledger;
- full invoicing/tax platform;
- PSP/card vault;
- CRM completo;
- universal analytics/telemetry store;
- raw high-frequency GPS history;
- global route/workforce optimizer;
- universal delivery/shipping platform;
- universal workflow editor;
- generic relationship/object platform;
- generic rules DSL.

---

## 45. Multi-tenancy

Toda entidad tenant-owned se ejecuta dentro de organization resuelta desde principal/credential.

```text
credential
    ↓
organization + principal + scopes
    ↓
domain operation
```

Public/browser credentials y secret/server credentials son clases distintas. Nunca colocar organization secret keys, bank integration credentials o PSP secrets en frontend público.

Participant associations, OfferingSelections, Reservations, allocations, payments y disruptions nunca pueden cruzar tenants.

---

## 46. Eventos, outbox, idempotencia y trazabilidad

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
reconciliation/recovery
```

Eventos adicionales derivados del stress test:

```text
request.participant_added
request.offering_selected
reservation.confirmed
reservation.rescheduled
reservation.cancelled
reservation.no_show
reservation.capacity_disrupted
reservation.capacity_recovered
resource_allocation.released
resource_allocation.replaced
waitlist.matched
```

Eventos financieros representativos:

```text
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
payment.refund_requested
payment.refund_processing
payment.refunded
payment.refund_failed
```

Debe poder reconstruirse:

```text
Who initiated the mutation (Principal)?
Which Contacts participated and in what roles?
What was understood/requested?
Which OfferingSelections and quantities were selected?
Which participants were recipients/payers?
Which Location/Destination applied?
Which schedules/policies applied and which versions?
What capacity was considered/held/committed?
Which ReservationItems were covered?
Which resources/pools were allocated, released, replaced or assigned?
Were any disruptions detected and how recovered?
Which PaymentRequirements were created and why?
Which instructions/evidence/authoritative Transactions existed?
How were funds allocated/refunded/reconciled?
What Dispatch/ServiceSessions occurred?
Which Fulfillments satisfied which Request/selections?
What external events occurred?
```

---

## 47. Invariantes temporales, capacity, policy y payments

- timestamps persistidos como instantes UTC;
- timezone IANA en schedules/locations que interpretan tiempo local;
- availability no equivale a Reservation;
- CapacityHold no es Reservation;
- confirmation revalida capacity/participants/quantity/policies transaccionalmente;
- schedule exceptions/holidays forman parte del cálculo efectivo;
- cambios posteriores de schedule/resource no reescriben Reservations confirmadas: disparan disruption/recovery;
- BusinessHours y AvailabilitySchedule son conceptos distintos;
- buffers y Resources forman parte del conflicto real;
- Reservations pueden consumir exclusive resources o capacity units;
- ResourceRequirement quantity rules son tipadas/deterministas;
- QueueEntry, WaitlistEntry y Reservation son conceptos distintos;
- Reservation commitment status no replica CheckIn/Queue/Dispatch/ServiceSession;
- allocation replacement/release conserva historia;
- snapshots conservan condiciones históricas relevantes;
- ReservationPolicy y PaymentPolicy son boundaries distintos;
- PaymentEvidence nunca satisface por sí sola un PaymentRequirement;
- browser success/redirect nunca es autoridad de pago;
- requirement satisfaction deriva de authoritative PaymentTransactions + PaymentAllocations;
- pagos tardíos no resucitan CapacityHolds/Reservations expiradas;
- Fulfillment y financial settlement siguen lifecycles independientes;
- payment/refund/reversal history no se borra;
- side effects externos ocurren post-commit.

---

## 48. Public IDs e IDs externos

Ejemplos:

```text
org_...
cnt_...
off_...
sel_...   OfferingSelection
req_...
res_...
dsp_...
prq_...   PaymentRequirement
pat_...   PaymentAttempt
ptx_...   PaymentTransaction
rfd_...   Refund
ful_...
evt_...
```

No todo link table necesita public ID.

Google Maps URLs, provider IDs, bank transaction IDs, Twilio/LiveKit identifiers son referencias; nunca identidad primaria del dominio.

---

## 49. Conversations vs Requests

> **Conversation is context. Request is work.**

Una conversation puede originar múltiples Requests y cerrarse sin terminar sus lifecycles.

El Contact que habló en la conversation no necesariamente es el recipient o payer del trabajo resultante.

---

## 50. `Fulfillment`: resultado verificable sin relaciones 1:1 falsas

`Fulfillment` conecta intención con resultado real.

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

Reglas:

```text
1 Request → 0..N Fulfillments
1 Reservation → 0..N ServiceSessions
1 ServiceSession → puede producir Fulfillments para uno o varios Requests mediante Fulfillment records separados
1 OfferingSelection → puede ser satisfecha total o parcialmente
```

Un Fulfillment puede referenciar la OfferingSelection concreta que satisface cuando aplique.

Ejemplo: una sola visita de plomería resuelve dos Requests. No hace falta un Fulfillment “multi-request” genérico; la misma ServiceSession puede evidenciar dos Fulfillment records, uno para cada Request/selection.

PaymentTransaction no sustituye Fulfillment: dinero recibido y resultado entregado son hechos distintos.

---

## 51. Vertical slice obligatorio de V2

### Demo Barbershop

Debe demostrar:

```text
requester ≠ recipient scenario
OfferingSelections: Haircut + Beard / multiple recipients
ResourceRequirements con fixed + per_selection/per_participant quantity proof
BusinessHours Mon–Fri / Saturday reduced / Sunday closed
holiday + special-hours exception
resource-specific availability
scheduled
queue
hybrid
walk-in
QueueEntry vs Waitlist boundary
exclusive resources
capacity revalidation
resource disruption + reallocation proof
ReservationPolicy cancellation/reschedule/no-show proof
Location with address + map link + arrival media/instructions
PaymentPolicy deposit/pay_on_arrival
card adapter path
cash/manual verified payment path
PaymentRequirement + PaymentAllocation
```

### Demo Plumbing

Debe demostrar:

```text
OfferingSelection + intake
24/7 or Offering-specific availability independent from office BusinessHours
arrival window
ServiceArea validation
Destination snapshot + controlled destination change proof
technician pool allocation
late concrete technician/vehicle assignment
vehicle/resource disruption + replacement history
Dispatch planned → en_route → arrived
ETA/status updates
map/share references where useful
ServiceSession(s)
bank-transfer PaymentInstruction
PaymentEvidence upload
manual or provider-backed independent verification
payment failure notification path
late-payment/revalidate-after-payment behavior
optional deposit/full/payment-after-service policy
business/customer cancellation consequences
```

### Cross-scenario foundation tests

Además probar:

```text
1 Request with multiple OfferingSelections
1 Request → multiple Reservations
1 Reservation → multiple ReservationItems
multiple participants with requester/recipient/payer roles
1 Reservation → multiple ServiceSessions
one ServiceSession evidencing multiple Fulfillments
payment reversal after Fulfillment does not rewrite service history
```

---

## 52. Lo que el stress test resolvió y lo que se difiere

### Adoptado en foundation

```text
participant roles
OfferingSelection
ReservationItem
ResourceRequirement quantity rules
ReservationPolicy
commitment status vs operational health
ReservationDisruption/recovery
allocation release/replacement history
Waitlist boundary
flexible Request/Reservation/Fulfillment cardinalities
```

### Deliberadamente diferido

No añadir todavía:

```text
ReservationSegment
ReservationSeries
Subscription
Agreement
Delivery logistics platform
WorkforceOptimizer
generic rules DSL
```

Procesos multietapa pueden usar multiple ResourceAllocations + ServiceSessions antes de justificar ReservationSegment.

Recurrencia puede representarse inicialmente mediante Reservations individuales. Si aparece un caso real repetitivo, un futuro `Agreement`/`ReservationSeries` puede **generar** Requests, Reservations y PaymentRequirements sin redefinir sus semánticas.

---

## 53. Lo que se preserva de V1

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

## 54. Lo que V2 debe evitar

1. vertical-specific models en el core;
2. convertir `Request`, `Offering`, `Resource` o `Reservation` en blobs que significan cualquier cosa;
3. asumir un único Contact con todos los roles;
4. asumir 1 Request = 1 Offering = 1 Reservation = 1 Fulfillment;
5. crear Offerings combinatorios para representar cada selección múltiple;
6. exact-time appointments como única forma de capacity commitment;
7. una única `opening_hours` incapaz de modelar reality/overrides;
8. tratar un feriado como cierre universal obligatorio;
9. tratar Location y Destination como el mismo concepto;
10. cancelar/rewrite silently confirmed Reservations cuando cambia Resource/Schedule;
11. mezclar commitment status con CheckIn/Queue/Dispatch/ServiceSession;
12. usar Queue como Waitlist;
13. almacenar raw GPS high-frequency data sin razón operacional;
14. convertir Dispatch en universal logistics platform prematuramente;
15. construir workforce optimizer global;
16. n8n como dependencia autoritativa;
17. OpenAPI manual separado de schemas reales;
18. writes por cada availability search;
19. editor universal de workflows;
20. considerar screenshot/comprobante como dinero recibido;
21. copiar lifecycle de Stripe/PayPal/Azul como dominio interno;
22. usar `paid: true/false` como único modelo financiero;
23. convertir payments coordination en accounting/ledger/PSP;
24. meter cancel/refund/no-show rules dentro de PaymentPolicy;
25. añadir ReservationSeries/Subscription/Segment antes de necesidad real.

---

## 55. Criterio para añadir features

Antes de añadir algo al core o módulos iniciales:

1. ¿Ayuda a representar una intención procesable o sus participantes/selections?
2. ¿Ayuda a describir qué ofrece la organización?
3. ¿Ayuda a determinar si existe/puede comprometerse capacity?
4. ¿Ayuda a conservar o recuperar un commitment ya realizado?
5. ¿Ayuda a ejecutar o demostrar un resultado?
6. ¿Necesita estado autoritativo dentro de Request Engine?
7. Si mueve dinero, ¿necesitamos conocer ese estado para permitir/bloquear el workflow?
8. ¿Es común a múltiples verticales?
9. ¿Puede vivir mejor como integración/sistema especializado?
10. ¿Tenemos un caso real que lo exige ahora?

---

## 56. North Star y vocabulario canónico

> **A headless, multi-tenant transactional request engine that turns customer or system intent into deterministic workflows, valid capacity commitments and verifiable outcomes, while preserving the participant, operational and payment state needed to complete and recover them across locations, queues and field service.**

En español:

> **Un motor transaccional headless y multiempresa que transforma intención en workflows deterministas, compromisos válidos de capacidad y resultados verificables, conservando el contexto de participantes, operaciones y pagos necesario para cumplirlos y recuperarlos en locations, colas y servicios en campo.**

```text
Principal            = who/what authoritatively performed a mutation
Contact              = business identity of a person/contact
Participant          = role a Contact plays in specific work
Offering             = what can be obtained
OfferingSelection    = which Offering/quantity/recipient is requested
Request              = what is wanted now
Workflow             = what must happen
ReservationItem      = which selected Offering/quantity is under a capacity commitment
Resource             = what can provide capacity
Capacity             = how much it can provide
ResourceRequirement  = what capacity a selected Offering needs
ResourceAllocation   = what capacity a Reservation committed
Assignment           = which concrete Resource will execute
Schedule             = when capacity may exist
Location             = where the organization operates/receives
Destination          = where this specific work must occur
Reservation          = committed capacity
OperationalHealth    = whether that commitment is currently fulfillable
ReservationDisruption = durable recovery case when committed capacity is threatened
Admission             = how service access happens
QueueEntry            = operational waiting after/with commitment
WaitlistEntry         = uncommitted interest in future capacity
Dispatch              = how assigned capacity moves toward Destination
ServiceSession        = what actually ran
ReservationPolicy    = cancellation/reschedule/no-show consequences
PaymentPolicy        = how/when payment is required
PaymentRequirement   = concrete money obligation
PaymentAttempt       = one attempt to satisfy that obligation
PaymentInstruction   = what the payer was told to do
PaymentEvidence      = evidence submitted, not proof of received funds
PaymentTransaction   = authoritative observed money movement
PaymentAllocation    = how verified money satisfies requirements
ReconciliationCase   = ambiguity requiring explicit financial resolution
Refund               = explicit return-of-funds lifecycle
Fulfillment          = verified business outcome
```

Si una feature no ayuda a representar estas responsabilidades, mantener sus invariantes o producir trazabilidad operacional/financiera útil, probablemente pertenece fuera de Request Engine.
