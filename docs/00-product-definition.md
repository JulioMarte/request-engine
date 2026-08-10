# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.1, lista para diseño relacional una vez se satisfaga `docs/02-pre-sql-domain-contract.md`.
>
> Este documento define **qué es Request Engine, qué no es, cuáles son sus primitivas de dominio y qué invariantes semánticas no pueden romperse**. Las decisiones de implementación pertenecen a `docs/01-architecture-v2.md`. Las cardinalidades, máquinas de estado e invariantes pre-SQL se detallan en `docs/02-pre-sql-domain-contract.md`.
>
> Si un documento técnico contradice este documento, gana este documento.

---

## 1. Definición del producto

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Request Engine es un **motor transaccional, headless y multi-tenant que transforma intención en trabajo estructurado, compromisos de capacidad, obligaciones de pago verificables y resultados auditables**.

Su responsabilidad termina cuando puede responder de manera autoritativa:

1. qué se pidió;
2. para quién;
3. qué Offering(s) están involucrados;
4. qué workflow aplica;
5. qué capacidad fue prometida y por qué sigue siendo válida o está en riesgo;
6. cuánto se debe y por qué;
7. qué dinero fue realmente observado;
8. qué ejecución ocurrió;
9. qué parte del resultado solicitado fue satisfecha;
10. quién o qué sistema produjo cada mutación autoritativa.

Request Engine no existe para almacenar conversaciones. Una conversación es contexto; un `Request` es trabajo durable.

---

## 2. Lo que Request Engine NO es

No es:

- CRM completo;
- ERP;
- sistema contable / general ledger;
- sistema fiscal o de invoicing universal;
- PSP;
- banco;
- PBX;
- sistema de inventario comercial general;
- e-commerce platform completa;
- workforce optimizer;
- route optimizer;
- raw GPS telemetry store;
- shipping/delivery platform universal;
- scheduler industrial multidimensional;
- BPMN/n8n/Temporal clone;
- framework genérico de agentes de IA;
- identity provider universal;
- generic object/relationship platform.

Puede integrarse con todos ellos.

Regla de boundary:

> Si el dato es necesario para determinar, comprometer, ejecutar o demostrar el resultado de un Request, Request Engine puede necesitar conservar una representación autoritativa mínima. Si pertenece a una operación empresarial general más amplia, debe referenciarse o delegarse.

---

## 3. Tenancy, actor e identidad de negocio

### Organization

`Organization` es el tenant boundary.

Toda entidad tenant-owned debe pertenecer a exactamente una Organization y ninguna relación tenant-owned puede cruzar Organizations.

### Principal

`Principal` es el actor autenticado que ejecuta una mutación.

Puede ser:

- usuario humano;
- empleado;
- service account;
- agent runtime;
- webhook/system principal;
- worker interno.

`Principal` responde **quién ejecutó la acción**. No representa necesariamente al cliente, recipient o payer.

### Contact

`Contact` es una identidad de negocio tenant-scoped de una persona/contacto.

No debe convertirse en CRM universal ni identity provider. Puede contener identifiers/contact methods suficientes para resolver a la persona dentro de la Organization.

La deduplicación/merge de Contacts debe preservar historia; no se borran asociaciones históricas silenciosamente.

### Participant

Un `Participant` representa el papel de un Contact dentro de un Request.

Roles iniciales:

```text
requester
recipient
payer
guardian
authorized_contact
```

Una persona puede tener varios roles y un Request puede tener múltiples participantes por rol.

**Importante:** un rol describe semántica de negocio; no concede por sí solo autoridad legal o técnica. `guardian` o `authorized_contact` pueden requerir reglas/verification adicionales.

No introducir `patient`, `student`, `customer`, etc. como modelos core incompatibles.

---

## 4. Request: unidad durable de intención procesable

`Request` representa una necesidad concreta que una Organization debe procesar.

Ejemplos:

```text
"Quiero una limpieza dental"
"Necesito reparar una fuga"
"Quiero corte y barba"
"Quiero una cotización"
"Necesito cambiar mi reservación"
```

Un canal puede producir cero, uno o varios Requests. Un Request puede sobrevivir a Website → WhatsApp → Voice → Human.

No asumir:

```text
1 Request = 1 Offering = 1 Reservation = 1 Fulfillment
```

`Request` debe tener lifecycle propio de trabajo y workflow; no se considera completado únicamente porque una Reservation terminó o porque se recibió dinero.

---

## 5. RequestType

`RequestType` expresa **qué intenta lograr el solicitante**, no qué producto específico está involucrado.

Tipos iniciales relativamente genéricos:

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

La especialización deriva de:

```text
RequestType
+ OfferingSelections
+ Participants
+ Organization policies
+ Request context
→ Workflow version
```

No crear un RequestType por cada Offering.

---

## 6. Offering y OfferingSelection

### Offering

`Offering` es la fachada canónica para representar algo que una Organization ofrece y que otra persona/sistema puede intentar obtener.

Ejemplos:

```text
Haircut
Dental Cleaning
Emergency Plumbing Visit
Technology Assessment
Router + Installation
```

Puede especializarse por composición en lugar de una mega-entidad nullable.

`Offering.kind` puede distinguir categorías útiles como:

```text
service
product
package
custom
```

pero `Offering` no sustituye inventario, catálogo e-commerce, ERP ni tax engine.

### OfferingSelection

`OfferingSelection` representa una selección concreta de un Offering dentro de un Request.

Puede contener:

```text
offering
quantity + unit semantics
validated configuration
recipient scope
selection status
historical snapshot/reference
```

Un Request puede tener 0..N selections.

Una Selection puede satisfacerse mediante varias Reservations y/o varios Fulfillments.

### Quantity

`quantity` nunca debe asumirse como un escalar sin semántica. La cantidad debe transportar la unidad lógica definida por el Offering cuando sea relevante.

Ejemplos distintos:

```text
2 seats
3 devices
4 service units
1 recipient
```

No crear un sistema universal de unidades físicas; sí conservar la semántica necesaria para validar capacity, pricing y fulfillment.

---

## 7. Workflow

El workflow responde:

> Dado este Request, sus selections, participants, policies y el estado autoritativo actual, ¿qué debe ocurrir ahora?

Un workflow puede:

1. solicitar input faltante;
2. validar participants/selections;
3. determinar precio;
4. buscar capacidad;
5. crear CapacityHold;
6. crear PaymentRequirement;
7. esperar confirmación/pago/verificación/callback/humano;
8. confirmar Reservation;
9. coordinar admission;
10. coordinar Dispatch;
11. ejecutar recuperación de disruption;
12. registrar Fulfillment;
13. completar o fallar de forma recuperable/terminal.

Los workflows son tipados, versionados y testeables. No construir inicialmente BPMN, un DSL universal ni un workflow editor genérico.

---

## 8. Pricing: verdad comercial mínima

Este boundary es obligatorio antes de SQL.

`PaymentRequirement` no explica por sí solo por qué existe una cantidad. Request Engine necesita conservar una determinación comercial mínima y auditable.

### PriceDetermination

`PriceDetermination` representa **cómo se obtuvo autoritativamente una cantidad comercial para un scope concreto**.

Debe poder conservar, según aplique:

```text
scope: Request / OfferingSelection / ReservationItem / other supported context
currency
base amount
quantity/unit inputs
explicit adjustments
explicit discounts/fees/taxes when Request Engine is responsible for them
pricing policy/version or external pricing source reference
final amount
reason/provenance
calculated_at
```

No convierte Request Engine en invoice engine, tax platform ni accounting ledger.

Un precio puede provenir de:

- configuración interna versionada;
- quote aprobada;
- pricing service externo;
- override humano autorizado;
- importe validado proporcionado por sistema externo.

El resultado relevante debe quedar snapshotted para que cambios posteriores no reescriban historia.

### Price amendments

Después de generar una obligación financiera, un cambio de precio no debe editar silenciosamente la historia.

Debe crear una nueva determinación/revisión y producir una consecuencia explícita:

```text
replace/cancel PaymentRequirement
create additional PaymentRequirement
waive remaining amount
refund excess
open reconciliation
```

---

## 9. Resource, capability, requirement y capacity

### Resource

`Resource` es algo cuya disponibilidad/capacidad limita materialmente si una Reservation puede cumplirse.

Kinds iniciales:

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

### ResourceCapability

Capacidad/skill tenant-scoped que un Resource puede ofrecer.

No usar enums globales por industria.

### ResourceRequirement

Describe la capacidad que necesita un ReservationItem/Offering, no el Resource concreto.

Quantity rules iniciales:

```text
fixed
per_selection_unit
per_participant
from_validated_input
```

La cantidad efectiva debe materializarse al crear el commitment.

### Capacity models

Inicialmente:

```text
exclusive
units
```

`exclusive`: conflicto temporal exclusivo.

`units`: N unidades reservables y consumo cuantificado.

No usar capacity como inventario comercial general.

---

## 10. Availability, ReservationOption y CapacityHold

### Availability

Consulta de capacidad potencial. No produce writes.

### ReservationOption

Resultado calculado/efímero. No es garantía futura.

### CapacityHold

`CapacityHold` es una reclamación temporal y autoritativa contra **el mismo espacio de capacidad que una Reservation confirmada consumiría**.

Ésta es una invariante fundamental:

> Live CapacityHolds + active confirmed capacity commitments nunca pueden exceder la capacidad válida del Resource/pool para el intervalo y quantity correspondientes.

Un Hold debe conservar suficientes datos para revalidar exactamente:

```text
ReservationItems candidate
resolved ResourceRequirements
resource/pool claims
intervals
quantities
expiration
policy/version
```

Un Hold expirado/released no puede confirmarse.

Un pago tardío no resucita un Hold expirado.

---

## 11. Reservation y ReservationItem

### Reservation

`Reservation` representa **un commitment confirmado de capacidad**.

Puede representar:

```text
exact slot
arrival window
queue-based commitment
hybrid scheduled + queue
```

No representa toda la operación posterior.

### ReservationItem

Explica qué scope comercial/seleccionado está cubierto por el commitment.

Una Reservation puede contener múltiples ReservationItems y puede cubrir selections de más de un Request cuando un workflow real lo justifique.

No debe existir un `request_id` singular como ownership autoritativo de Reservation.

### Commitment lifecycle

El status de Reservation describe el commitment, no cada outcome operacional.

Estados iniciales recomendados:

```text
confirmed
cancelled
expired
closed
```

`closed` significa que la Reservation ya no mantiene capacidad futura pendiente; **no afirma que todos los recipients asistieron, que todo fue fulfilled o que se pagó**.

No usar `completed` y `no_show` como estados globales obligatorios de Reservation porque fallan para Reservations multi-item/multi-recipient con resultados mixtos.

No-show se determina a nivel de admission/participant/item scope y sus consecuencias se aplican mediante policy.

---

## 12. ResourceAllocation: trazabilidad de capacity

`ResourceAllocation` representa capacidad concreta o agregada comprometida para satisfacer **un ResourceRequirement específico**.

No basta con relacionarla sólo con Reservation.

Debe poder reconstruirse:

```text
ReservationItem
→ effective ResourceRequirement
→ ResourceAllocation
→ Resource/pool
→ interval
→ quantity
```

Una Allocation puede cubrir sólo parte del intervalo total de Reservation.

Lifecycle mínimo:

```text
active
released
replaced
```

La historia no se sobrescribe.

### Pool y late binding

Reservar `Resource(kind=pool)` compromete capacidad agregada.

La asignación posterior de un miembro concreto **no puede consumir una segunda vez la misma capacidad**. Debe modelarse como binding/replacement/child realization de la capacidad ya comprometida, según la estrategia técnica elegida.

### Assignment

`Assignment` no es una primitiva core independiente hasta que exista una necesidad que no pueda expresarse mediante el lifecycle/binding de ResourceAllocation.

El modelo debe evitar dos verdades paralelas: “allocation dice A” y “assignment dice B”.

---

## 13. Admission: CheckIn, Queue y Waitlist

### AdmissionPolicy

Define cómo se entra al servicio:

```text
scheduled
queue
window
hybrid
```

No decide consecuencias financieras; eso pertenece a ReservationPolicy + Payments.

### CheckIn

Hecho de presencia/readiness observado.

### QueueEntry

Posición/priority operacional de alguien que ya tiene contexto de admission/capacity.

No asumir FIFO absoluto.

### WaitlistEntry

Interés en capacidad futura que todavía NO ha sido comprometida.

```text
WaitlistEntry
→ match
→ temporary CapacityHold/offer
→ acceptance
→ Reservation
```

Queue y Waitlist nunca son equivalentes.

### No-show

No-show no es un boolean global de Reservation. Debe asociarse al scope operacional relevante: participant, ReservationItem o admission unit.

Una Reservation de 10 plazas puede tener 8 atendidos + 2 no-show sin caer en un estado global contradictorio.

---

## 14. ServiceSession y Fulfillment

### ServiceSession

Representa ejecución real.

Una Reservation puede producir 0..N ServiceSessions.

Los tiempos reales nunca reescriben los tiempos planificados.

### Fulfillment

`Fulfillment` representa evidencia auditable de que **un scope concreto solicitado fue satisfecho total o parcialmente**.

Debe poder identificar:

```text
Request
offering selection / requested scope when applicable
recipient scope when relevant
fulfilled quantity/scope
status/outcome
ServiceSession or external evidence reference
recorded_at
```

Una ServiceSession puede producir varios Fulfillments para varios Requests.

Un Request puede producir varios Fulfillments.

Una OfferingSelection puede satisfacerse parcialmente mediante varios Fulfillments.

`Fulfillment` no equivale a PaymentTransaction.

---

## 15. Location, Destination, ServiceArea y Dispatch

### Location

Lugar operativo controlado/presentado por la Organization.

Puede contener:

- address estructurada;
- timezone IANA;
- BusinessHours;
- map/share references;
- arrival/accessibility/parking instructions;
- media references.

### Destination

Lugar concreto donde debe cumplirse una Reservation específica.

Conserva snapshot histórico.

Cambiar Destination después de confirmation/dispatch es una operación de negocio:

```text
validate service area
re-evaluate pricing
re-evaluate capacity/assignment
re-evaluate ETA
apply explicit change
preserve old/new history
```

### ServiceArea

Boundary inicial simple:

```text
named zone
city/province
postal code
radius
```

### Dispatch

Coordina capacidad asignada hacia Destination.

Estados iniciales:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

Una Reservation puede producir 0..N Dispatches.

Request Engine conserva estado operacional útil, no raw high-frequency GPS telemetry.

---

## 16. Schedules, exceptions y timezone

### BusinessHours

Cuándo Organization/Location está abierta al público.

### AvailabilitySchedule

Cuándo Offering/Resource/capacity puede reservarse.

### ScheduleException

Tipos iniciales:

```text
closed
replace_hours
open_special
capacity_override
```

### HolidayCalendar

Puede ser una fuente/configuración de exceptions. No debe ser aggregate rico por defecto ni asumir holiday = closed.

### Composición

Availability efectiva puede depender de:

```text
Organization
∩ Location
∩ Offering restrictions
∩ Resource schedule
→ date-specific exceptions
→ live holds/reservations
```

Cambios de schedule posteriores nunca reescriben Reservations confirmadas; pueden abrir ReservationDisruption.

### DST

Persistir instantes UTC no basta para interpretar input local.

Toda operación basada en hora local debe resolver explícitamente:

- timezone IANA;
- hora local inexistente durante spring-forward;
- hora local ambigua durante fall-back;
- offset/fold escogido cuando exista ambigüedad.

Nunca asumir silenciosamente una de dos ocurrencias de una hora local ambigua.

---

## 17. ReservationPolicy y disruption

### ReservationPolicy

Composición versionada de reglas de:

```text
cancellation
reschedule
no-show
```

Debe evaluar al menos initiator, reason, timing, current operational state y policy version.

La policy decide consecuencias de negocio; Payments ejecuta consecuencias financieras.

Overrides humanos requieren scope + reason + audit.

### ReservationDisruption

Representa un caso durable cuando un commitment confirmado pierde o corre riesgo de perder capacidad.

Ejemplos:

```text
resource unavailable
location unavailable
capacity reduced
schedule exception
vehicle failure
assignment failure
```

La Reservation no desaparece.

```text
capacity-affecting change
→ detect affected commitments
→ disruption open
→ recovery/reallocation
   ├─ success: resolved
   └─ failure: reschedule/cancel/human action
```

`operational_health` (`valid/at_risk/blocked`) debe ser projection derivada del estado real, no un campo libremente mutable.

---

## 18. Payments: obligación, intento, evidencia y dinero

### PaymentPolicy

Describe cómo/cuándo un workflow exige o permite cobrar.

Modes iniciales:

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

### PaymentRequirement

Obligación monetaria concreta.

Debe referenciar la `PriceDetermination` o provenance que explica el amount cuando aplica.

Estados conceptuales:

```text
open
partially_satisfied
satisfied
waived
cancelled
```

`overdue` es derivado.

La satisfaction no debe depender de un boolean manual: deriva de PaymentAllocations elegibles contra financial facts válidos.

### PaymentMethodConfiguration / PaymentProviderConnection

Config/integration tenant-scoped. Provider-specific details no contaminan domain rules.

### PaymentAttempt

Intento de satisfacer un Requirement mediante un método/provider.

Un Attempt exitoso no implica necesariamente dinero settled.

### PaymentInstruction

Snapshot de instrucciones entregadas al payer. Puede ser value object/documento persistido; no necesita aggregate independiente salvo necesidad real.

### PaymentEvidence

Comprobante presentado.

Estados posibles:

```text
submitted
under_review
accepted_as_evidence
rejected
```

**Accepted evidence sigue sin ser dinero.**

### PaymentTransaction

Hecho financiero autoritativamente observado.

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

Estados/provider observations pueden incluir pending/authorized/settled/failed, pero el historial financiero debe ser append-oriented.

No cambiar retrospectivamente un settlement para fingir que nunca existió.

### PaymentAllocation

N:M entre PaymentTransaction y PaymentRequirement.

Soporta:

- partial payments;
- varios transactions para una obligación;
- una transaction para varias obligaciones;
- overpayment/unallocated funds.

Sólo valor financiero elegible/settled según policy puede satisfacer Requirements.

### ReconciliationCase

Para fondos observados cuyo matching o tratamiento no es seguro.

No adivinar.

---

## 19. Refund, reversal, return y dispute/chargeback

Estos conceptos no son equivalentes.

### Refund

Operación iniciada para devolver dinero previamente recibido.

Lifecycle:

```text
requested
processing
succeeded
failed
cancelled
```

Un Refund debe indicar qué financial value/original transaction(s) intenta devolver y por qué.

### Void

Cancelación de una autorización no capturada. No es Refund.

### Reversal / Return

Nuevo hecho financiero autoritativo que reduce o elimina valor previamente considerado disponible.

Ejemplos:

- bank transfer returned;
- provider reversal;
- ACH return.

Debe representarse como un financial fact relacionado con el movimiento original, no borrando el original.

### Dispute / Chargeback

Tiene lifecycle propio cuando el provider lo expone:

```text
opened
under_review
won
lost
closed
```

Un chargeback perdido puede producir un reversing financial fact.

Fulfillment/ServiceSession permanecen históricos aunque el dinero se revierta.

### Requirement satisfaction after reversals/refunds

La satisfaction debe recalcularse/proyectarse desde allocations financieramente elegibles netas.

Si todas las allocations que satisfacían un Requirement dejan de ser elegibles por reversal/return, el Requirement puede volver a quedar outstanding según policy. Esto no deshace el Fulfillment.

---

## 20. Amendments: no editar compromisos históricos ciegamente

Después de confirmation/payment, cambios materiales requieren operaciones explícitas.

Aplica a:

```text
OfferingSelection
quantity
recipient scope
Destination
planned time/window
price
ResourceRequirements
policy snapshot
```

Una modificación puede:

- reemplazar/cancelar ReservationItem;
- crear nueva Reservation;
- liberar/reasignar capacity;
- crear nueva PriceDetermination;
- crear/cancelar/ajustar PaymentRequirements mediante hechos explícitos;
- generar Refund/Reconciliation;
- preservar provenance completo.

No se permite que un simple `UPDATE` reescriba lo que históricamente fue prometido.

No se introduce todavía un aggregate genérico `Amendment`; primero se modelan commands explícitos por operación.

---

## 21. Concurrency y authority

La corrección transaccional no depende del orden feliz de llamadas de API.

Debe sobrevivir:

- dos personas intentando la última capacidad;
- múltiples CapacityHolds concurrentes;
- payment llegando mientras expira un Hold;
- cancellation y check-in simultáneos;
- Resource unavailable mientras Reservation confirma;
- webhook duplicado/out-of-order;
- refund y reversal simultáneos;
- dos empleados intentando asignar el mismo Resource;
- dos workers procesando el mismo outbox item;
- reconciliations concurrentes.

Los invariantes exactos se detallan en `02-pre-sql-domain-contract.md`.

---

## 22. Idempotency

Toda mutación pública/reintentable relevante debe soportar idempotency.

Una key debe estar scoped al tenant + operación + caller/context apropiado.

Misma key + mismo payload lógico:

```text
→ mismo resultado lógico
```

Misma key + payload diferente:

```text
→ conflicto/rechazo
```

Idempotency técnica no intenta deduplicar intenciones humanas semánticamente equivalentes con keys distintas.

---

## 23. External callbacks

Callbacks externos:

1. validar autenticidad/signature cuando exista;
2. aplicar anti-replay;
3. persistir provider event identity/fingerprint;
4. procesar idempotentemente;
5. no asumir orden de llegada;
6. ejecutar commands internos cortos/transaccionales;
7. no mantener DB transaction abierta durante network calls.

---

## 24. AI agents y continuidad multicanal

La IA nunca obtiene autoridad especial.

```text
AI interprets/proposes
→ structured candidate
→ Request Engine validates
→ deterministic policy/workflow
→ scoped capability
→ authoritative transaction
```

Un agent puede explicar, recopilar, consultar y proponer. No puede declarar dinero recibido por texto/screenshot ni saltarse authorization.

### Confused deputy protection

`Principal` autorizado para una capability no significa automáticamente que puede actuar sobre cualquier Contact/Request/Reservation.

Toda mutación debe validar:

```text
principal identity
organization
scope/capability permission
subject/on-behalf-of authority when relevant
resource ownership/current state
```

### Cross-channel continuation

Website → WhatsApp → Voice → Human puede continuar el mismo Request si cada canal resuelve independientemente authority.

Separar:

```text
Request identity
Principal authorization
Channel/session correlation
```

Un `request_id` nunca funciona como bearer authorization token.

Cada tool mutante revalida estado autoritativo actual; nunca confía en availability/status almacenado sólo en el contexto del LLM.

---

## 25. Events, audit y outbox

### Audit

Responde:

```text
who did what
on behalf of whom when relevant
why
under which policy/version
with which override/reason
```

Audit no es logs.

### Domain events

Representan hechos del dominio, no sustituyen el estado autoritativo transaccional.

### Transactional outbox

External side effects ocurren post-commit.

At-least-once delivery es aceptable si consumidores son idempotentes.

---

## 26. Cardinalidades canónicas

Resumen normativo:

```text
Request 1 ── 0..N OfferingSelections
Request N ── M Contacts            via Participants
Request N ── M Reservations        derived via ReservationItems/Selections
Request 1 ── 0..N Fulfillments

OfferingSelection N ── M Reservations via ReservationItems
OfferingSelection 1 ── 0..N Fulfillments (preferred small Fulfillment records)

Reservation 1 ── 1..N ReservationItems
Reservation 1 ── 0..N ResourceAllocations
Reservation 1 ── 0..N ServiceSessions
Reservation 1 ── 0..N Dispatches

ResourceRequirement 1 ── 0..N ResourceAllocations

PaymentTransaction N ── M PaymentRequirements via PaymentAllocations

ServiceSession 1 ── 0..N Fulfillments
```

No introducir FKs 1:1 que contradigan estas semánticas.

---

## 27. Canonical domain vocabulary V2.1

### Core

```text
Organization
Principal
Contact
Participant
Offering
OfferingSelection
RequestType
Request
Workflow
PriceDetermination
Fulfillment
```

### Reservations / capacity

```text
Resource
ResourceCapability
ResourceRequirement
CapacityHold
Reservation
ReservationItem
ResourceAllocation
AdmissionPolicy
CheckIn
QueueEntry
WaitlistEntry
ReservationPolicy
ReservationDisruption
```

### Time / place / field service

```text
BusinessHours
AvailabilitySchedule
ScheduleException
Location
Destination
ServiceArea
Dispatch
ServiceSession
```

### Payments

```text
PaymentPolicy
PaymentRequirement
PaymentMethodConfiguration
PaymentProviderConnection
PaymentAttempt
PaymentInstruction
PaymentEvidence
PaymentTransaction
PaymentAllocation
Refund
FinancialReversal/Return
PaymentDispute
ReconciliationCase
```

### Platform

```text
AuditRecord
DomainEvent
OutboxMessage
IdempotencyRecord
```

### Deliberately not first-class aggregates yet

```text
ReservationParticipant
Assignment
ResourceGroup
HolidayCalendar
CancellationPolicy entity
ReschedulePolicy entity
NoShowPolicy entity
ReservationSeries
Agreement
Subscription
Delivery
InventoryReservation
Invoice
Order
Ledger
```

Pueden aparecer como projections/config/components o introducirse después de una necesidad real.

---

## 28. Domain diagram

```text
                           ORGANIZATION
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
          Principals         Contacts         Offerings
              │                 │                 │
              │             Participants          │
              └──────────────► REQUEST ◄──────────┘
                                │
                        OfferingSelections
                                │
                          Workflow(version)
                                │
                ┌───────────────┼────────────────┐
                │               │                │
       PriceDetermination    Capacity          Other work
                │               │
                │       ResourceRequirements
                │               │
                │         CapacityHold?
                │               │
                │          RESERVATION
                │               │
                │       ReservationItems
                │               │
                │      ResourceAllocations
                │               │
                ├───────────┐   │
                │           │   │
        PaymentRequirement  │   │
                │           │   │
         PaymentAttempts    │   │
                │           │   │
        PaymentEvidence?    │   │
                │           │   │
      PaymentTransactions   │   │
                │           │   │
       PaymentAllocations   │   │
                │           │   │
 Refund/Reversal/Dispute    │   │
                            │   │
                     Admission / Dispatch
                            │   │
                            └─┬─┘
                              │
                       ServiceSession(s)
                              │
                       FULFILLMENT(S)
                              │
                          REQUEST outcome
```

---

## 29. Foundation invariants

Estas invariantes son obligatorias y deben poder implementarse con DB + application rules sin contradicción:

1. no cross-tenant references;
2. public IDs no conceden authority;
3. OfferingSelection quantity tiene semántica validada;
4. historical snapshots no se reescriben por cambios futuros;
5. Availability/ReservationOption no comprometen capacity;
6. live Hold + confirmed capacity nunca exceden capacity disponible;
7. expired Hold no confirma;
8. toda active Allocation satisface un ResourceRequirement identificable;
9. confirmed Reservation mantiene sus requirements o abre disruption;
10. pool late-binding no duplica capacity;
11. cancellation no borra history;
12. mixed attendance/outcomes no se colapsan en Reservation.no_show/completed global;
13. Fulfillment identifica scope/quantity realmente satisfecho;
14. PaymentRequirement tiene provenance monetaria;
15. PaymentEvidence nunca satisface un Requirement;
16. authoritative financial facts son append-oriented;
17. PaymentAllocation no gasta más valor que el eligible financial amount;
18. refunds/reversals/disputes no borran el movimiento original;
19. financial reversal no deshace Fulfillment;
20. late payment no resucita capacity expirada;
21. amendments materiales son commands explícitos, no blind updates;
22. idempotency key reutilizada con payload diferente se rechaza;
23. external callbacks duplicados no duplican efectos;
24. derived states no se escriben arbitrariamente;
25. agent scope no sustituye subject/resource authorization;
26. local-time ambiguity/DST se resuelve explícitamente.

La forma relacional exacta para sostenerlas se define después de validar `docs/02-pre-sql-domain-contract.md`.

---

## 30. Vertical slices obligatorios antes de declarar schema estable

### Barbershop

Debe demostrar:

- requester ≠ recipient;
- multiple selections/recipients;
- barber + chair requirements;
- scheduled + queue + hybrid;
- late customer/no-show parcial;
- resource sickness/disruption;
- deposit/cash/card;
- capacity race.

### Dental

Debe demostrar:

- child + guardian + payer;
- staged multi-resource requirements;
- equipment failure;
- multiple ServiceSessions;
- mixed outcomes;
- partial fulfillment.

### Plumbing

Debe demostrar:

- arrival window;
- Destination/ServiceArea;
- technician pool → concrete resource binding;
- vehicle failure/redispatch;
- destination change after dispatch;
- bank transfer/evidence/manual verification;
- late payment after Hold expiry;
- one visit satisfying multiple Requests.

### Payments stress cases

Debe demostrar:

- partial payment;
- multiple payments → one Requirement;
- one transaction → multiple Requirements;
- overpayment;
- refund parcial;
- reversal/return;
- dispute/chargeback after Fulfillment;
- duplicate/out-of-order webhook;
- concurrent reconciliation.

---

## 31. Qué se difiere deliberadamente

No añadir todavía:

```text
ReservationSegment
ReservationSeries
Agreement
Subscription
Delivery logistics
WorkforceOptimizer
generic pricing DSL
generic rules DSL
generic relationship graph
BPMN/editor universal
full inventory
invoice/tax engine
accounting ledger
```

Recurrence se puede representar con Reservations individuales hasta que exista necesidad de operar sobre la serie como una entidad.

---

## 32. Criterio final antes de SQL

El modelo está listo para pasar a diseño PostgreSQL sólo si podemos responder sin ambigüedad:

```text
¿Qué pidió exactamente el cliente?
¿Para quién?
¿Qué se prometió?
¿Qué capacity concreta satisface cada requirement?
¿Por qué se cobró esa cantidad?
¿Qué dinero fue realmente observado?
¿Qué devoluciones/reversals/disputes ocurrieron?
¿Qué se ejecutó realmente?
¿Qué scope fue fulfilled y cuál quedó pendiente?
¿Quién autorizó cada mutación?
¿Qué ocurre si dos actores hacen la operación al mismo tiempo?
```

El contrato obligatorio que convierte estas preguntas en cardinalidades, state transitions e invariantes implementables está en `docs/02-pre-sql-domain-contract.md`.
