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

Una developer console interna para inspeccionar organizations, credentials, offerings, requests, reservations, resources, locations, dispatches, payments, events y webhooks es compatible con esta definición; no convierte a la UI en el centro del producto.

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
11. Si existe un pago, ¿cuánto se debe, cómo puede pagarse y qué evidencia autoritativa confirma que el dinero realmente fue recibido?
12. Si el servicio ocurre fuera de una location, ¿qué debe desplazarse y hacia dónde?
13. ¿Cuál fue el resultado final?

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
                                         │
                                    Payments?
                                         │
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
6. crear un `PaymentRequirement`;
7. solicitar confirmación o pago;
8. esperar verificación financiera o callback;
9. crear una tarea humana;
10. crear/coordinar un Dispatch;
11. completar la solicitud;
12. fallar de forma recuperable;
13. hacer handoff.

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
Reservation    = committed/planned capacity
CheckIn        = requester is present/ready
QueueEntry     = dynamic operational queue position/priority
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

```text
Offering: Haircut
requires:
  capability barber x1
  capability barber_chair x1
```

### Allocation

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

Y también split shifts:

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

## 32. Payments: obligación, intento, evidencia y dinero verificado

Request Engine puede coordinar pagos necesarios para cumplir un workflow, pero **no es un PSP, banco, sistema contable ni ledger general**.

La separación fundamental es:

```text
Pricing
= cuánto debe cobrarse y por qué

Payments
= cómo se intenta cobrar, verificar y aplicar ese dinero

Accounting / invoicing
= representación contable/fiscal del negocio
```

La invariante principal:

> **Intención de pagar ≠ evidencia de pago ≠ dinero recibido.**

Un screenshot, recibo subido, redirect de éxito del browser o mensaje del cliente nunca son por sí solos prueba autoritativa de que el dinero llegó.

### 32.1 `PaymentPolicy`: regla reusable

`PaymentPolicy` describe **cómo y cuándo un Offering/workflow exige o permite cobrar**, no una deuda concreta.

Modos de producto iniciales:

```text
none
optional
deposit
full_prepaid
pay_on_arrival
pay_after_service
```

Conceptualmente puede resolver:

```text
amount_rule
payment_timing
reservation_gate
accepted_methods
capacity_strategy
expiration_behavior
```

Ejemplo:

```text
Dental Procedure

PaymentPolicy:
  amount_rule: 20% deposit
  payment_timing: before_reservation_confirmation
  reservation_gate: payment_required
  accepted_methods: card | bank_transfer
```

### 32.2 `PaymentRequirement`: obligación concreta

`PaymentRequirement` representa **una cantidad concreta que debe satisfacerse para un propósito de negocio**.

Ejemplo:

```text
PaymentRequirement
purpose: reservation_deposit
amount: DOP 2,000
status: open
due_at: ...
```

La policy es reusable; el requirement pertenece a un Request/Reservation/fulfillment concreto.

Estados conceptuales iniciales:

```text
open
partially_satisfied
satisfied
waived
cancelled
```

`overdue` puede derivarse de `due_at`; no necesita ser un estado persistido.

### 32.3 `Money`

Toda cantidad monetaria debe transportar moneda explícita:

```text
Money
amount
currency
```

Nunca asumir moneda implícita ni usar floating point binario para autoridad financiera.

Conversión FX no ocurre de forma aproximada/implícita. Requiere policy/provider explícito si algún día se soporta.

### 32.4 `PaymentMethodConfiguration`: cómo cobra cada organización

Cada organization puede configurar sus propios métodos.

Ejemplo:

```text
QuisqueyaTech
- Bank Transfer - Banreservas
- Stripe Card
- Cash

Dental Clinic
- Azul Card
- Bank Transfer Popular
- Cash
```

Separar:

```text
method_family
= economic/user-facing method

provider
= system/integration that processes or verifies it
```

Method families iniciales:

```text
card
bank_transfer
cash
wallet
external
custom
```

Providers pueden ser:

```text
stripe
paypal
square
azul
bank_api_x
manual
custom_provider
```

No crear `if stripe`, `if paypal`, `if banreservas` dentro del dominio.

Una configuración puede describir:

```text
organization
method_family
provider_connection
supported_currencies
display_name
verification_mode
status
configuration/reference
```

### 32.5 `PaymentAttempt`: un intento de satisfacer el requirement

Un `PaymentRequirement` puede tener múltiples `PaymentAttempt`.

```text
Requirement: DOP 1,000

Attempt 1: card → failed
Attempt 2: card → failed
Attempt 3: bank_transfer → succeeded
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

No todos los métodos recorren todos los estados.

Un external ID como Stripe PaymentIntent, PayPal order/capture, Azul reference o bank transaction ID es **referencia externa del Attempt/Transaction**, nunca la identidad canónica de Request Engine.

### 32.6 `PaymentInstruction`: qué debe hacer el cliente

`PaymentInstruction` representa las instrucciones que Request Engine presentó al pagador para un Attempt.

Para transferencia:

```text
Bank: Banreservas
Account holder: Empresa X
Account: ...
Account type: ...
Amount: DOP 5,000
Reference: RE-A7F92
Expires: ...
```

Para otros métodos puede ser:

```text
redirect/payment URL
QR/reference
POS instructions
cash-at-location instructions
```

Las instrucciones deben conservar **snapshot**. Si mañana cambia la cuenta bancaria de la organization, un Attempt histórico conserva exactamente qué cuenta/instrucción se presentó.

### 32.7 Transferencia bancaria: experiencia y verdad financiera

Flujo preferido:

```text
PaymentRequirement
      ↓
PaymentAttempt: bank_transfer
      ↓
PaymentInstruction
bank/account/reference/amount
      ↓
customer transfers money
      ↓
PaymentEvidence? [optional]
      ↓
bank API/feed OR authorized manual verification
      ↓
PaymentTransaction confirmed/settled
      ↓
PaymentAllocation
      ↓
PaymentRequirement satisfied/partially_satisfied
```

Request Engine puede mostrar información bancaria y una referencia única para facilitar conciliación.

El cliente puede subir comprobante, pero:

> **El comprobante prueba lo que el cliente afirma haber hecho; no prueba que el banco receptor haya acreditado los fondos.**

### 32.8 `PaymentEvidence`: evidencia presentada, no dinero

`PaymentEvidence` puede representar:

```text
transfer receipt image
PDF
bank receipt/reference
claimed amount/date/reference
other supporting artifact
```

Estados pueden incluir:

```text
submitted
under_review
accepted_as_evidence
rejected
```

`accepted_as_evidence` **no equivale** a `PaymentRequirement.satisfied`.

Los archivos son sensibles: almacenamiento privado, acceso scoped/audited y retention policy. Un hash puede ayudar a detectar reutilización del mismo archivo, pero nunca convierte automáticamente una coincidencia en fraude.

### 32.9 Verificación automática versus manual

Fuentes autoritativas posibles:

```text
provider_webhook
provider_api
bank_feed
bank_api
manual_bank_verification
cash_verification
external_system
```

#### Banco integrado

El banco/feed/API confirma un movimiento recibido. Request Engine crea/reconcilia una `PaymentTransaction`.

#### Banco sin integración

```text
Evidence submitted
      ↓
verification_pending
      ↓
authorized employee opens bank portal/app
      ↓
independently confirms received funds
      ↓
PaymentTransaction
source = manual_bank_verification
verified_by = principal
```

La acción humana significa **“verifiqué el dinero en una fuente independiente”**, no “el screenshot parece verdadero”.

Debe requerir un scope privilegiado como `payments.verify` y producir audit.

Si no puede verificarse el dinero:

```text
payment.verification_failed
```

El workflow puede notificar al cliente, pedir revisión, nuevo intento, método alternativo o intervención humana.

### 32.10 `PaymentTransaction`: movimiento financiero observado

`PaymentTransaction` representa **un movimiento de dinero observado por una autoridad financiera o confirmado mediante un proceso autorizado**.

Conceptualmente:

```text
amount
currency
status
source
external_reference
occurred_at / received_at
verified_by nullable
metadata/reference
```

Estados financieros conceptuales pueden distinguir:

```text
pending
authorized
settled
failed
reversed
```

Por defecto, un `PaymentRequirement` se satisface mediante fondos `settled`/efectivamente recibidos y asignados.

`authorized` no significa necesariamente dinero capturado. Una policy futura puede aceptar autorización como gate solamente cuando el caso de negocio lo requiera explícitamente.

El modelo debe asumir que una transacción confirmada puede posteriormente tener reversal/return/dispute. Nunca borrar historia financiera para fingir que no ocurrió.

### 32.11 `PaymentAllocation`: aplicar dinero a obligaciones

No modelar pago como boolean `paid=true`.

```text
PaymentTransaction
      ↓
PaymentAllocation
      ↓
PaymentRequirement
```

Esto permite:

#### Pago parcial

```text
Requirement: DOP 10,000
Transaction A: DOP 4,000
Allocation A: 4,000
Remaining: 6,000
status: partially_satisfied
```

#### Múltiples pagos

```text
Transaction A: 3,000
Transaction B: 2,000
Requirement: 5,000 → satisfied
```

#### Un pago para varios requirements

```text
Transaction: 5,000
Allocation A → deposit 2,000
Allocation B → balance 3,000
```

#### Overpayment

```text
Requirement: 5,000
Transaction: 6,000
Allocation: 5,000
Unallocated: 1,000
```

El exceso no se aplica arbitrariamente. Puede requerir refund, credit, otra obligación o conciliación humana.

### 32.12 `ReconciliationCase`

Cuando los fondos existen pero no puede determinarse de forma segura a qué requirement pertenecen, crear un caso explícito en vez de adivinar.

Ejemplos:

```text
missing transfer reference
same amount from multiple possible customers
late transfer after CapacityHold expired
provider/bank event without known Attempt
unallocated overpayment
```

Matching puede considerar referencia, amount, date, sender data y receiving account, pero una coincidencia ambigua no debe mutar estado financiero automáticamente.

### 32.13 Pagos tardíos y relación con capacity

Un pago confirmado **no resucita automáticamente capacidad expirada**.

Ejemplo:

```text
CapacityHold expires at 18:00
customer transfer settles at 08:00 next day
original slot already taken
```

La `PaymentTransaction` sigue siendo dinero real recibido, pero la Reservation no se confirma retroactivamente.

El workflow debe resolver:

```text
offer alternative capacity
refund
retain authorized credit if product supports it
human reconciliation
```

PaymentPolicy debe poder seleccionar una estrategia de capacidad:

```text
hold_until_payment
revalidate_after_payment
confirm_then_collect
```

#### `hold_until_payment`

Capacidad se retiene por una ventana limitada mientras se espera pago. Adecuado para métodos rápidos; puede ser malo para transferencias lentas.

#### `revalidate_after_payment`

No garantiza capacity mientras el pago viaja. Al confirmarse fondos se vuelve a validar y se ofrece alternativa si ya no existe capacidad.

#### `confirm_then_collect`

Reservation puede confirmarse con requirement aún abierto, por ejemplo `pay_on_arrival` o `pay_after_service`.

### 32.14 Cash y métodos externos son first-class

Cash no es un hack.

```text
PaymentAttempt
method_family = cash
status = awaiting_customer_action
```

Un principal autorizado registra recepción real:

```text
PaymentTransaction
source = cash_verification
amount
location/principal/timestamp
```

Otros métodos externos/custom pueden registrarse mediante adapters sin contaminar el dominio con lógica de proveedor.

### 32.15 Success UI no es autoridad

Nunca considerar una URL como:

```text
/payment-success
```

prueba de pago.

Fuentes de autoridad:

```text
signed/idempotent provider webhook
server-to-server provider API
bank feed/API
authorized independent manual verification
```

Los callbacks deben ser firmados/validados cuando el provider lo permita, anti-replay e idempotentes.

### 32.16 Refunds, cancelaciones y reversals

`Refund` tiene lifecycle propio y puede ser parcial.

```text
requested
processing
succeeded
failed
cancelled
```

No sobrescribir la PaymentTransaction original.

```text
PaymentTransaction +5,000
Refund -2,000
```

Cancel/void de una autorización no capturada **no es lo mismo** que refund de dinero ya recibido.

El modelo financiero debe conservar historia append-oriented/auditable, incluyendo reversals/returns posteriores cuando ocurran.

### 32.17 Límites con invoicing/accounting

```text
PaymentRequirement ≠ Invoice
PaymentTransaction ≠ accounting ledger entry
```

Invoices pueden requerir numeración fiscal, impuestos, line items y reglas legales. General ledger, reconciliation contable completa, payroll, accounts payable y fiscal reporting permanecen fuera del core de Request Engine.

Request Engine conserva sólo el estado financiero necesario para coordinar correctamente el workflow y demostrar qué ocurrió.

### 32.18 Seguridad de payments

- Request Engine no almacena PAN/CVV;
- tokens/payment-method references del provider son preferibles;
- provider secrets fuera del frontend y protegidos;
- `payments.verify`, `payments.refund` y acciones similares requieren scopes explícitos;
- PaymentEvidence usa almacenamiento privado y acceso auditable;
- bank account display data se expone sólo donde corresponde;
- logs no contienen card data, full bank evidence, secrets o PII financiera innecesaria;
- una IA puede explicar instrucciones/consultar status, pero no auto-verificar evidencia ni inventar que un pago fue recibido.

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
GET  /v1/payment-requirements/{id}
POST /v1/payment-requirements/{id}/attempts
POST /v1/payment-attempts/{id}/evidence
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
get_payment_options
start_payment
get_payment_status
submit_payment_evidence
cancel_reservation
reschedule_reservation
```

Los agentes no necesitan razonar sobre resource graphs, locks, pool internals, raw GPS, PSP internals o bank reconciliation internals.

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

En payments específicamente:

```text
LLM can explain payment instructions
LLM can collect evidence/reference
LLM can query payment status

LLM cannot declare funds received
LLM cannot satisfy PaymentRequirement from screenshot/text alone
LLM cannot perform refund/verification without authorized deterministic capability + scope
```

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
create PaymentRequirement when required
verify authoritative payment outcome
apply payment to requirement
confirm Reservation according to policy
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
What is needed, what must happen, and what operational/payment state is authoritative for this workflow?

ERP/accounting
What resources, money, inventory and internal financial operations exist across the enterprise?
```

Request Engine puede consumir analytics, routing, banks o PSPs como capabilities/integrations, pero no se convierte en telemetry platform, accounting system, inventory system, bank, PSP ni global workforce optimizer.

Debe saber si existe capacidad suficiente y comprometerla correctamente. No necesariamente debe calcular el plan globalmente óptimo para decenas de técnicos.

Debe saber si una obligación de pago fue satisfecha de forma confiable. No necesita convertirse en ledger contable general.

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
- accounting/ERP/general ledger;
- full invoicing/tax platform;
- PSP/card vault;
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

Public/browser credentials y secret/server credentials son clases distintas. Nunca colocar organization secret keys, bank integration credentials o PSP secrets en frontend público.

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

Cada request/reservation debe permitir reconstruir:

```text
Who initiated this?
What was understood?
Which Offering was selected?
Which Location/Destination applied?
Which schedule/policies applied?
What capacity was considered/held/committed?
Which resources/pools were allocated or assigned?
Which PaymentRequirements were created and why?
Which payment instructions were shown?
Which evidence was submitted?
Which authoritative transactions were observed and how verified?
How were funds allocated to requirements?
What refunds/reversals/reconciliation cases occurred?
What dispatch/execution occurred?
Which principal/tool performed each mutation?
What external events occurred?
What was the final outcome?
```

---

## 42. Invariantes temporales, de capacidad y pagos

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
- PaymentEvidence nunca satisface por sí sola un PaymentRequirement;
- browser success/redirect nunca es autoridad de pago;
- requirement satisfaction deriva de PaymentTransactions autoritativas + PaymentAllocations;
- pagos tardíos no resucitan automáticamente CapacityHolds/Reservations expiradas;
- payment/refund/reversal history no se borra para ocultar movimientos ocurridos;
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
prq_...   PaymentRequirement
pat_...   PaymentAttempt
ptx_...   PaymentTransaction
rfd_...   Refund
ful_...
evt_...
```

Google Maps place/share URLs, Stripe IDs, PayPal IDs, bank transaction IDs, Twilio IDs, LiveKit identifiers u otros IDs externos son referencias; nunca identidad primaria del dominio.

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

Payments pueden ser condición para Fulfillment o Reservation, pero PaymentTransaction no sustituye Fulfillment: dinero recibido y resultado entregado son hechos diferentes.

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
PaymentPolicy: deposit or pay_on_arrival
card payment adapter path
cash/manual verified payment path
PaymentRequirement + PaymentAllocation
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
bank-transfer PaymentInstruction
PaymentEvidence upload
manual or provider-backed independent verification
payment failure notification path
late-payment/revalidate-after-payment behavior
optional deposit/full/payment-after-service policy
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
13. editor universal de workflows;
14. considerar screenshot/comprobante como dinero recibido;
15. copiar el lifecycle de Stripe/PayPal/Azul como dominio interno;
16. usar `paid: true/false` como único modelo financiero;
17. convertir payments coordination en accounting/ledger/PSP.

---

## 49. Criterio para añadir features

Antes de añadir algo al core o módulos iniciales:

1. ¿Ayuda a representar una intención procesable?
2. ¿Ayuda a describir qué ofrece la organización?
3. ¿Ayuda a determinar si existe/puede comprometerse capacidad?
4. ¿Ayuda a ejecutar o demostrar el resultado?
5. ¿Necesita estado autoritativo dentro de Request Engine?
6. Si mueve dinero, ¿necesitamos conocer ese estado para permitir/bloquear el workflow?
7. ¿Es común a múltiples verticales?
8. ¿Puede vivir mejor como integración/sistema especializado?
9. ¿Tenemos un caso real que lo exige ahora?

---

## 50. North Star

> **A headless, multi-tenant transactional request engine that turns customer or system intent into deterministic workflows, valid capacity commitments and verifiable outcomes, while exposing the operational and payment state needed to complete them across locations, queues and field service.**

En español:

> **Un motor transaccional headless y multiempresa que transforma intención en workflows deterministas, compromisos válidos de capacidad y resultados verificables, conservando el contexto operacional y financiero necesario para cumplirlos en locations, colas y servicios en campo.**

Vocabulario canónico:

```text
Offering           = what can be obtained
Request            = what is wanted now
Workflow           = what must happen
Resource           = what can provide capacity
Capacity           = how much it can provide
Requirement        = what capacity an Offering needs
Allocation         = what capacity a Reservation committed
Assignment         = which concrete resource will execute
Schedule           = when capacity may exist
Location           = where the organization operates/receives
Destination        = where this specific work must occur
Reservation        = what capacity is committed
Admission          = how service access happens
Dispatch           = how assigned capacity moves toward Destination
ServiceSession     = what actually ran
PaymentPolicy      = how/when payment is required
PaymentRequirement = what money is required for a concrete purpose
PaymentAttempt     = one attempt to satisfy that requirement
PaymentEvidence    = evidence submitted, not proof of received funds
PaymentTransaction = authoritative observed money movement
PaymentAllocation  = how verified money satisfies requirements
Fulfillment        = what outcome actually happened
```

Si una feature no ayuda a representar estas responsabilidades, mantener sus invariantes o producir trazabilidad operacional/financiera útil, probablemente pertenece fuera de Request Engine.
