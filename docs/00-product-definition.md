# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.2, candidata a diseño relacional **sólo después** de satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> Este documento define qué es Request Engine, qué no es, cuáles son sus primitivas canónicas y qué distinciones semánticas no pueden colapsarse. Las decisiones técnicas viven en `docs/01-architecture-v2.md`. Las cardinalidades, state semantics, concurrency proofs e invariantes pre-SQL viven en `docs/02-pre-sql-domain-contract.md`.
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

Request Engine es un **motor transaccional, headless y multi-tenant que transforma intención durable en trabajo estructurado, compromisos verificables de capacidad, obligaciones de pago, ejecución observable y resultados auditables**.

Debe poder responder de forma autoritativa:

1. qué se pidió;
2. quién o qué entidad de negocio participa y con qué rol;
3. quién está autorizado para actuar y por qué;
4. qué Offering(s) y cantidades están involucrados;
5. qué workflow/version gobierna el Request;
6. qué capacidad fue temporalmente retenida o finalmente comprometida;
7. qué admission/execution ocurrió, sin confundirlo con el compromiso;
8. cuánto se determinó comercialmente y por qué;
9. qué dinero fue realmente observado y cómo se asignó;
10. qué se cumplió, para quién y en qué cantidad/scope;
11. qué mutación produjo cada Principal, integration o worker.

Request Engine no existe para almacenar conversaciones. Una conversación, llamada o thread es contexto externo; un `Request` es trabajo durable.

---

## 2. Lo que Request Engine NO es

No es:

- CRM completo;
- ERP;
- identity provider universal;
- sistema contable / general ledger;
- plataforma fiscal o de invoicing universal;
- PSP o banco;
- PBX o communications platform;
- sistema general de inventario;
- e-commerce platform completa;
- workforce optimizer;
- route optimizer;
- raw GPS telemetry store;
- shipping/delivery platform universal;
- scheduler industrial multidimensional;
- BPMN/n8n/Temporal clone;
- framework genérico de agentes IA;
- generic object/relationship platform.

Puede integrarse con todos ellos.

### Boundary rule

> Si un dato es necesario para decidir, autorizar, comprometer, ejecutar o demostrar el resultado de un Request, Request Engine puede necesitar una representación autoritativa mínima. Si pertenece a la operación empresarial general fuera de ese Request, se referencia o delega.

Esto implica dos reglas simétricas:

- no absorber sistemas completos sólo porque aportan datos al workflow;
- no externalizar un estado mínimo si hacerlo impide demostrar por qué una decisión autoritativa fue válida.

---

## 3. Distinciones fundacionales que no pueden colapsarse

V2.2 declara estas separaciones como invariantes de lenguaje:

```text
Principal ≠ Party
Participant role ≠ authority
Request ≠ Reservation
Reservation ≠ QueueEntry
Reservation ≠ ServiceSession
CapacityHold ≠ Availability
PaymentEvidence ≠ PaymentTransaction
PaymentTransaction ≠ Fulfillment
PriceDetermination ≠ Quote
Operational health ≠ Reservation lifecycle
```

Si una implementación necesita fusionar dos de estas ideas, debe demostrar que no pierde una invariante del dominio.

---

## 4. Tenancy, actor, Party y authority

### Organization

`Organization` es el tenant boundary.

Toda entidad tenant-owned pertenece a exactamente una Organization. Ninguna relación tenant-owned crítica puede cruzar Organizations.

### Principal

`Principal` es el actor autenticado que ejecuta una mutación.

Puede ser:

```text
human user
employee
service account
agent runtime
provider/webhook principal
internal worker
```

`Principal` responde **quién ejecutó la acción**. No significa automáticamente requester, recipient, payer o guardian.

### Party

`Party` es la identidad de negocio mínima de una entidad que puede participar en un Request.

Kinds iniciales:

```text
person
organization
```

Esto permite representar limpiamente:

```text
empresa que paga por un empleado
padre que paga por un hijo
aseguradora o tercero pagador
persona que solicita para otra persona
```

`Party` no convierte Request Engine en CRM ni corporate-directory platform.

Para `person`, puede conservar identifiers/contact methods suficientes para resolver la identidad dentro del tenant. Para `organization`, conserva únicamente la identidad comercial mínima requerida por el Request.

Dedup/merge debe preservar historia; asociaciones históricas nunca se mueven o borran silenciosamente.

### RequestParticipant

`RequestParticipant` relaciona una Party con un Request y describe su papel transaccional.

Roles iniciales:

```text
requester
recipient
payer
guardian
authorized_contact
```

Un Request puede tener múltiples Participants por role y una Party puede tener varios roles.

**El role no concede authority.**

### AuthorityGrant / Representation

Cuando una mutación depende de actuar por otra Party o sobre un subject protegido, debe existir authority verificable suficiente para explicar:

```text
who may act
for/on behalf of whom
for which operation/scope
under which source/policy
with which validity/revocation state when relevant
```

No construir un ACL/relationship graph universal. Esta primitiva sólo existe para impedir que `guardian`, `authorized_contact`, channel identity o agent scope se conviertan accidentalmente en autoridad universal.

Una implementación puede materializar authority como grant, verified relationship, external authorization reference o policy-backed fact. Lo obligatorio es que la decisión sea auditable y no derive sólo del texto de un LLM.

---

## 5. Request: unidad durable de intención procesable

`Request` representa una necesidad concreta que una Organization debe procesar.

Ejemplos:

```text
"Quiero una limpieza dental"
"Necesito reparar una fuga"
"Quiero corte y barba"
"Quiero una cotización"
"Necesito cambiar una reservación"
```

Un canal puede producir cero, uno o varios Requests. Un Request puede sobrevivir:

```text
Website → WhatsApp → Voice → Human
```

No asumir:

```text
1 Request = 1 Offering = 1 Reservation = 1 ServiceSession = 1 Fulfillment
```

`Request` posee lifecycle propio de trabajo. No queda completed sólo porque:

- una Reservation se cerró;
- ocurrió una ServiceSession;
- se recibió dinero;
- un Fulfillment parcial fue registrado.

### RequestType

Expresa qué intenta lograr el solicitante, no el producto concreto.

Tipos iniciales:

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

La especialización se obtiene de:

```text
RequestType
+ OfferingSelections
+ RequestParticipants
+ verified authority
+ Organization policies
+ validated context
→ Workflow version
```

No crear un RequestType por Offering.

---

## 6. Cross-channel correlation

Request Engine no almacena la conversación, pero necesita preservar correlation mínima cuando un Request cruza channels.

### ExternalCorrelation

Referencia durable y tenant-scoped que vincula un Request y, cuando se haya verificado, una Party/Principal context con un identifier externo.

Ejemplos:

```text
website session/customer reference
WhatsApp conversation/identity reference
voice call/session reference
external CRM ticket
external booking source
```

`ExternalCorrelation`:

- no es authentication;
- no es bearer authorization;
- no convierte un thread/call ID en Party identity;
- permite continuar el mismo Request sin almacenar conversación completa.

Cada canal debe resolver authority independientemente para la mutación solicitada.

---

## 7. Offering y OfferingSelection

### Offering

`Offering` representa algo que la Organization ofrece y que una Party/sistema puede intentar obtener.

Ejemplos:

```text
Haircut
Dental Cleaning
Emergency Plumbing Visit
Technology Assessment
Router + Installation
```

Kinds iniciales pueden incluir:

```text
service
product
package
custom
```

Pero `Offering` no sustituye inventario, tax engine, catalog platform ni ERP.

### Product boundary

Si fulfillment de un Offering depende de stock que Request Engine no controla, la confirmación debe depender de una **precondición/commitment externo verificable** o de policy explícita que acepte ese riesgo.

No representar stock comercial como `Resource` sólo para evitar una integración de inventory.

### OfferingSelection

Selección concreta dentro de un Request.

Puede contener:

```text
offering
quantity + unit semantics
validated configuration
recipient/service-subject scope
selection status
historical snapshot/reference
```

Un Request tiene 0..N selections.

Una Selection puede satisfacerse mediante varias Reservations, ServiceSessions y Fulfillments.

### Quantity

`quantity` nunca es un número sin unidad lógica.

Ejemplos:

```text
2 seats
3 devices
4 service units
1 recipient
```

No crear un sistema universal de unidades físicas. Sí conservar suficiente semántica para pricing, capacity y fulfillment determinístico.

---

## 8. Recipient / service-subject scope

Los Participants describen roles del Request; no son suficientes para explicar quién consume cada parte de una Reservation.

El modelo debe poder establecer explícitamente, cuando sea relevante:

```text
OfferingSelection
→ recipient/service-subject scope
→ ReservationItem/admission scope
→ Fulfillment
```

Esto debe soportar:

```text
10 seats
8 attended
2 no-show
```

sin crear estados globales contradictorios.

No introducir todavía una ontología universal `ServiceSubject`. El diseño físico puede usar una relación explícita entre Party/RequestParticipant y Selection/ReservationItem/admission unit. La invariante es que el scope operacional sea inequívoco.

---

## 9. Workflow

Un workflow responde:

> Dado este Request, su estado autoritativo y las policies versionadas, ¿qué debe ocurrir ahora?

Puede:

1. pedir input faltante;
2. validar Participants/authority/selections;
3. determinar precio;
4. consultar availability;
5. crear CapacityHold;
6. crear PaymentRequirement;
7. esperar pago/verificación/external callback/humano;
8. confirmar Reservation;
9. coordinar admission;
10. coordinar Dispatch;
11. ejecutar recovery;
12. registrar Fulfillment;
13. completar o fallar de forma recuperable/terminal.

Workflows son tipados, versionados y testeables.

No construir inicialmente:

```text
generic workflow DSL
BPMN engine
visual workflow editor
universal state-machine framework
```

---

## 10. Pricing: verdad comercial mínima

### PriceDetermination

`PriceDetermination` explica cómo se obtuvo autoritativamente una cantidad para un scope concreto.

Debe poder conservar:

```text
priced scope
currency
base amount
quantity/unit inputs
explicit adjustments
explicit discounts/fees/taxes when owned here
pricing policy/source + version
final amount
provenance
calculated_at
Principal/reason for override
```

Puede provenir de:

- configuración interna versionada;
- pricing service externo;
- quote aprobada;
- override humano autorizado;
- authoritative external amount.

El resultado utilizado históricamente queda snapshotted.

### Quote is not PriceDetermination

`request_quote` sólo requiere una entidad `Quote` si el producto necesita lifecycle comercial propio como:

```text
offered
valid_until
accepted
rejected
expired
superseded
```

Mientras no exista ese requisito, una PriceDetermination + workflow state basta. No introducir `Quote` por anticipación.

### Price amendments

Después de generar obligaciones, un cambio de precio crea una nueva determination/revision y consecuencias explícitas:

```text
replace/cancel PaymentRequirement
create additional PaymentRequirement
waive remaining amount
refund excess
open reconciliation
```

Nunca reescribir silenciosamente la determination histórica.

---

## 11. Resource, requirement y capacity

### Resource

Algo cuya disponibilidad/capacidad limita materialmente si un commitment puede cumplirse.

Kinds iniciales:

```text
person
facility
room
chair
equipment
vehicle
pool
```

`virtual` no es kind core hasta que exista un conflicto de capacidad real que lo justifique.

### ResourceCapability

Capability/skill tenant-scoped ofrecida por Resource.

No enums globales por industria.

### ResourceRequirementTemplate

Regla reusable del Offering que describe qué capacity necesitaría un future commitment.

### EffectiveResourceRequirement

Requirement materializado para un ReservationItem concreto, con quantity/interval/scope ya resueltos.

Esta separación evita confundir configuración mutable del Offering con el requirement histórico de una Reservation.

Quantity rules iniciales:

```text
fixed
per_selection_unit
per_participant
from_validated_input
```

No introducir OR/k-of-n requirement algebra hasta que un caso real lo exija.

### Capacity models

Inicialmente:

```text
exclusive
units
```

`exclusive`: conflictos temporales incompatibles.

`units`: N unidades consumibles durante un intervalo.

Capacity no es inventario comercial general.

### Transition/setup/travel capacity

Si travel/setup/cleanup hace físicamente imposible dos commitments que individualmente no se solapan, ese tiempo debe participar en la validación de capacity o producir un constraint autoritativo equivalente.

Request Engine no necesita optimizar rutas, pero tampoco puede confirmar schedules físicamente imposibles ignorando transition time material.

---

## 12. Availability, ReservationOption y CapacityHold

### Availability

Consulta calculada de capacidad potencial. No produce writes.

### ReservationOption

Resultado calculado/efímero. Nunca es garantía futura.

### CapacityHold

Claim temporal autoritativo contra **el mismo capacity conflict space que consumiría la Reservation confirmada**.

Invariante:

> Live CapacityHolds + active confirmed ResourceAllocations nunca exceden la capacidad efectiva del Resource/pool para los intervalos/quantities relevantes.

Un Hold conserva suficiente información para revalidar exactamente:

```text
candidate ReservationItems
resolved EffectiveResourceRequirements
resource/pool claims
intervals
quantities
expiration
policy/version
```

Estados conceptuales:

```text
active
confirmed
released
expired
```

Sólo `active` consume capacity como hold.

Un Hold expired/released no confirma.

Un pago tardío no resucita capacity expirada.

---

## 13. Reservation: sólo compromiso confirmado de capacidad

`Reservation` significa una cosa:

> **commitment confirmado de capacity**.

Puede comprometer:

```text
exact slot
arrival window
capacity across one or more sub-intervals
```

No significa:

```text
queue position
check-in
service execution
fulfillment
payment
```

### ReservationItem

Explica qué scope seleccionado/comercial cubre el commitment.

Una Reservation puede contener múltiples ReservationItems y cubrir selections de más de un Request si un workflow real lo justifica.

No debe existir `Reservation.request_id` singular como ownership authority.

### Commitment lifecycle

Estados canónicos:

```text
confirmed
cancelled
expired
closed
```

`closed` significa que no queda capacity futura comprometida. No afirma attendance, fulfillment ni payment.

`completed`, `no_show`, `checked_in`, `waiting`, `in_service` y `en_route` no son Reservation commitment states.

### Partial cancellation/amendment

Si sólo parte de una Reservation multi-item/multi-recipient se cancela, no se puede colapsar toda la Reservation a `cancelled` salvo que todo el commitment termine.

La operación debe poder liberar/reemplazar el scope afectado preservando history y capacity accounting.

---

## 14. ResourceAllocation y late binding

`ResourceAllocation` representa capacity comprometida para satisfacer un `EffectiveResourceRequirement` específico.

Debe reconstruirse:

```text
ReservationItem
→ EffectiveResourceRequirement
→ ResourceAllocation
→ Resource/pool
→ interval
→ quantity
```

Una Allocation puede cubrir sólo parte del intervalo de la Reservation.

Lifecycle mínimo:

```text
active
released
replaced
```

Historia no se sobrescribe.

### Pool late binding

Reservar un `Resource(kind=pool)` compromete capacity agregada.

Asignar luego un miembro concreto no puede consumir la misma capacidad por segunda vez. Debe ser binding/realization/replacement con lineage explícito.

### Assignment

`Assignment` sigue deliberadamente fuera del core mientras ResourceAllocation pueda expresar de forma única quién/cómo satisface el requirement.

No crear dos verdades paralelas:

```text
Allocation says A
Assignment says B
```

---

## 15. Admission: independiente del commitment

### AdmissionPolicy

Describe cómo una Party/subject entra al servicio:

```text
scheduled
queue
window
hybrid
```

AdmissionPolicy no define si existe capacity commitment ni consecuencias financieras.

### CheckIn

Hecho observado de presence/readiness para un admission scope.

### QueueEntry

Posición/priority operacional.

**Una QueueEntry puede existir sin Reservation.**

Ejemplo walk-in:

```text
Request/subject
→ QueueEntry
→ ServiceSession
```

Ejemplo appointment + queue:

```text
Reservation
→ CheckIn
→ QueueEntry
→ ServiceSession
```

No asumir FIFO absoluto.

### WaitlistEntry

Interés en capacity futura que todavía no está comprometida.

```text
WaitlistEntry
→ match
→ temporary CapacityHold/offer
→ acceptance
→ Reservation
```

Queue y Waitlist nunca son equivalentes.

### No-show

No-show se registra/determina sobre un admission/recipient/item scope suficientemente específico. No es boolean ni status global de Reservation.

Una Reservation de 10 seats puede resultar en 8 attended + 2 no-show.

---

## 16. ServiceSession y Fulfillment

### ServiceSession

Representa un episodio real de ejecución.

Una Reservation puede participar en 0..N ServiceSessions y una ServiceSession puede ejecutar trabajo asociado a 0..N Reservations.

Por tanto la cardinalidad semántica recomendada es:

```text
Reservation N:M ServiceSession
```

Esto soporta:

- una Reservation ejecutada en varias sessions;
- una visita que ejecuta múltiples Reservations;
- ejecución sin Reservation previa en walk-in/external work cuando policy lo permita.

Los timestamps reales nunca reescriben timestamps planificados.

### Fulfillment

Evidencia auditable de que un scope concreto solicitado fue satisfecho total o parcialmente.

Debe identificar:

```text
Request
optional OfferingSelection/requested scope
recipient/service-subject scope when relevant
fulfilled quantity/scope
outcome/status
optional ServiceSession/evidence reference
recorded_at
source/Principal
```

Preferencia:

```text
one Fulfillment → one Request
```

Una ServiceSession que satisface dos Requests produce dos Fulfillment records.

Una Selection puede tener múltiples Fulfillments parciales.

Refund/reversal nunca borra Fulfillment.

---

## 17. Location, Destination, ServiceArea y Dispatch

### Location

Lugar operativo controlado/presentado por la Organization.

Puede contener:

- structured address;
- timezone IANA;
- BusinessHours;
- maps/share references;
- arrival/accessibility/parking instructions;
- media references.

Media es integration/reference, no aggregate core.

### Destination

Snapshot del lugar concreto donde debe ejecutarse un scope field-service.

Cambiar Destination después de commitment/dispatch es command de negocio:

```text
validate service area
re-evaluate price if relevant
re-evaluate capacity/travel constraints
re-evaluate dispatch/ETA
preserve previous snapshot
apply explicit change
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

Coordina movement de Resources hacia Destination para uno o varios operational scopes.

Estados iniciales:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No asumir rígidamente `Reservation 1:N Dispatch` si un mismo trip ejecuta varias Reservations. El contrato pre-SQL debe permitir link explícito sin convertir Dispatch en route optimizer.

Request Engine conserva ETA/tracking/share reference/latest meaningful position cuando sea útil, no raw high-frequency GPS telemetry.

---

## 18. Schedules, exceptions y timezone

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

No es entidad core inicial. Puede ser source/configuración reusable de ScheduleExceptions cuando exista necesidad real.

### Effective availability

Puede depender de:

```text
Organization/Location availability
∩ Offering restrictions
∩ Resource schedules
→ date-specific exceptions
→ transition/travel constraints when material
→ live holds/reservations
```

Schedule changes posteriores no reescriben Reservations confirmadas; producen detection/recovery cuando dejan commitments en riesgo.

### DST

Persistir UTC no basta para interpretar input local.

Toda operación local-time debe resolver:

- timezone IANA;
- nonexistent local time;
- ambiguous local time;
- offset/fold cuando exista ambigüedad.

Nunca normalizar silenciosamente.

---

## 19. ReservationPolicy, policy provenance y disruption

### ReservationPolicy

Composición versionada de reglas de:

```text
cancellation
reschedule
no-show
```

Debe considerar cuando aplique:

```text
initiator
reason
timing
recipient/item scope
current operational state
policy version
```

### Policy resolution

Toda decisión material basada en policy debe poder explicar:

```text
which policy/version won
which inputs were evaluated
why an override applied
who authorized override
```

No introducir generic rules DSL.

### Disruption

La capacidad de detectar y recuperar commitments en riesgo es obligatoria.

`ReservationDisruption` **no es aggregate root obligatorio** en V2.2.

Puede comenzar como durable disruption/recovery fact asociado a Reservation/Allocation. Sólo debe promoverse a `DisruptionCase` si necesita lifecycle propio como:

```text
ownership
SLA
multiple recovery attempts
escalation
human assignment
resolution history
```

Operational health:

```text
valid
at_risk
blocked
```

es projection derivada, no arbitrary mutable state.

---

## 20. Payments: obligación, evidencia y dinero

### PaymentPolicy

Describe cómo/cuándo cobrar.

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

Debe conservar Money, purpose, payer Party cuando se conozca, pricing provenance, policy reference/snapshot y due_at cuando aplique.

Estados como:

```text
open
partial
satisfied
overdue
```

son derivados/materializados desde financial facts.

Decisiones explícitas como:

```text
waived
cancelled
```

sí son business dispositions autoritativas.

### PaymentMethodConfiguration / PaymentProviderConnection

Integration/config tenant-scoped. Provider details no contaminan domain rules.

### PaymentAttempt

Intento de cobrar mediante método/provider.

Success del attempt no equivale automáticamente a settlement.

### PaymentInstruction

Snapshot de instrucciones dadas al payer. Value object/document persistido salvo necesidad real de lifecycle propio.

### PaymentEvidence

Comprobante presentado.

```text
submitted
under_review
accepted_as_evidence
rejected
```

**Accepted evidence sigue sin ser dinero.**

### PaymentTransaction

Financial fact observado autoritativamente.

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

Un settlement histórico no desaparece porque posteriormente exista Refund/Reversal/Dispute.

### PaymentAllocation

Asigna valor financiero elegible a PaymentRequirements.

Soporta:

- partial payment;
- multiple transactions → one requirement;
- one transaction → multiple requirements;
- overpayment/unallocated value.

### ReconciliationCase

Caso durable cuando existen financial facts pero su matching/tratamiento no es seguro.

No adivinar.

---

## 21. Refund, reversal y dispute

### Refund

Operación iniciada para devolver valor financiero.

```text
requested
processing
succeeded
failed
cancelled
```

Debe conocer amount/currency, reason, original financial scope, provider reference y provenance.

### Void

Cancelación de authorization no capturada. No es Refund.

### FinancialReversal / Return

Nuevo financial fact que reduce valor previamente elegible.

Ejemplos:

```text
bank return
provider reversal
ACH return
```

No borra el movimiento original.

### PaymentDispute

Lifecycle separado:

```text
opened
under_review
won
lost
closed
```

Dispute no es Refund. Un lost dispute puede producir un reversing financial fact.

Fulfillment permanece histórico aunque el dinero desaparezca posteriormente.

### Net satisfaction

PaymentRequirement satisfaction deriva de allocations financieramente elegibles netas. Si reversal/return invalida todo el valor, el Requirement puede volver a outstanding según policy sin deshacer Fulfillment.

---

## 22. Amendments

Después de commitment/payment/fulfillment, campos materiales no se editan con generic CRUD.

Material:

```text
offering
quantity
recipient scope
planned interval
Destination
price
EffectiveResourceRequirements
policy snapshot
```

Commands explícitos pueden:

- replace/release ReservationItem/allocation scope;
- crear nueva Reservation;
- crear nueva PriceDetermination;
- crear/cancelar/waive PaymentRequirement;
- crear Refund/Reconciliation;
- preservar lineage y provenance.

No introducir aggregate genérico `Amendment` todavía.

---

## 23. Idempotency, callbacks y concurrency

Toda mutación pública/reintentable relevante soporta idempotency.

Scope mínimo:

```text
organization + operation + caller/context + key
```

Misma key + mismo canonical payload:

```text
→ mismo logical result
```

Misma key + payload diferente:

```text
→ conflict
```

Callbacks externos:

1. validate signature/authenticity;
2. anti-replay cuando aplique;
3. persist provider event identity/fingerprint;
4. process idempotently;
5. no asumir ordering;
6. execute short internal transactions;
7. no network calls inside authoritative DB transaction.

Financial, capacity y tenant invariants no pueden depender únicamente de Python checks.

---

## 24. AI agents

La IA no tiene autoridad especial.

```text
LLM interprets/proposes
→ typed candidate/command
→ application authorization
→ current-state validation
→ policy evaluation
→ authoritative transaction
```

### Confused deputy protection

Una mutación exige, cuando aplique:

```text
authenticated Principal
Organization match
required capability/scope
verified Party/subject correlation
on-behalf-of authority
entity authorization
valid current state
policy approval
idempotency
```

Agent scope no sustituye subject authority.

### Tool design

Agent tools deben preferir commands semánticos:

```text
cancel_reservation
reschedule_reservation
change_destination
check_in
accept_waitlist_offer
submit_payment_evidence
```

por encima de `update_entity` genérico.

Availability nunca se presenta como committed booking; sólo CapacityHold/Reservation otorgan autoridad sobre capacity.

Hallucinated IDs se resuelven tenant-first y nunca producen cross-tenant leakage descriptivo.

Screenshots/payment claims sólo pueden crear PaymentEvidence, nunca settlement.

---

## 25. Events, audit y outbox

### Audit

Debe responder:

```text
who did what
on behalf of whom
why
under which policy/version
with which override/reason
source/channel/correlation
```

Audit no es logs.

### DomainEvent

Representa hechos del dominio; no sustituye authoritative transactional state.

### Transactional outbox

Domain mutation + outbox append ocurren en la misma DB transaction.

Delivery puede ser at-least-once. Consumers deben ser idempotentes.

---

## 26. Cardinalidades canónicas V2.2

```text
Organization 1 ── N Principals
Organization 1 ── N Parties
Organization 1 ── N Offerings
Organization 1 ── N Requests

Request N ── M Party
    via RequestParticipant

Request 1 ── 0..N OfferingSelection
Offering 1 ── 0..N OfferingSelection

Request N ── M Reservation
    via OfferingSelection/ReservationItem lineage

OfferingSelection N ── M Reservation
    via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem 1 ── 0..N EffectiveResourceRequirement
EffectiveResourceRequirement 1 ── 0..N ResourceAllocation
Resource 1 ── 0..N ResourceAllocation

Reservation N ── M ServiceSession
ServiceSession 1 ── 0..N Fulfillment
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment

QueueEntry 0..1 ── Reservation
    Reservation optional; walk-in queue is valid

PaymentTransaction N ── M PaymentRequirement
    via PaymentAllocation

Request 1 ── 0..N ExternalCorrelation
```

Dispatch ↔ Reservation cardinality se mantiene explícitamente no congelada a 1:N hasta definir si Dispatch representa un trip/operational movement que puede cubrir múltiples commitments.

Recipient/service-subject links deben permitir Party/Participant ↔ Selection/ReservationItem/admission scope sin imponer un global `ReservationParticipant` aggregate.

---

## 27. Canonical vocabulary V2.2

### Core

```text
Organization
Principal
Party
AuthorityGrant / Representation
RequestParticipant
RequestType
Request
ExternalCorrelation
Offering
OfferingSelection
Workflow
PriceDetermination
Fulfillment
```

### Capacity / reservation

```text
Resource
ResourceCapability
ResourceRequirementTemplate
EffectiveResourceRequirement
CapacityHold
Reservation
ReservationItem
ResourceAllocation
```

### Admission

```text
AdmissionPolicy
CheckIn
QueueEntry
WaitlistEntry
ReservationPolicy
```

### Time / place / execution

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
FinancialReversal / Return
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

### Deliberately not first-class yet

```text
Contact as universal core identity
ReservationParticipant aggregate
Assignment
ResourceGroup
HolidayCalendar aggregate
ReservationDisruption aggregate
Quote
ReservationSeries
Agreement
Subscription
Delivery
InventoryReservation
Invoice
Order
Ledger
Generic Amendment
Generic Policy DSL
Generic Workflow DSL
```

---

## 28. Domain diagram

```text
                           ORGANIZATION
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
      PRINCIPAL               PARTY                OFFERING
          │                     │                     │
          │           Authority/Representation        │
          │                     │                     │
          └───────────────► REQUEST ◄─────────────────┘
                              │
                    RequestParticipants
                              │
                    OfferingSelections
                              │
                      Workflow(version)
                              │
             ┌────────────────┼───────────────────┐
             │                │                   │
     PriceDetermination     Capacity          Admission
             │                │                   │
     PaymentRequirement   CapacityHold?      CheckIn/Queue
             │                │                   │
     PaymentAllocation    RESERVATION              │
             ▲                │                   │
             │        ReservationItems            │
    PaymentTransaction        │                   │
      │    │    │      EffectiveRequirements      │
   Refund Rev Dispute          │                   │
                       ResourceAllocations          │
                              │                    │
                              └────────┬───────────┘
                                       │
                               ServiceSession(s)
                                       │
                                  Fulfillment(s)
                                       │
                                  Request outcome

Request ── ExternalCorrelation ── Website / WhatsApp / Voice / external systems
```

---

## 29. Foundation invariants

1. no cross-tenant references;
2. public/external IDs never grant authority;
3. Principal and Party are not implicitly interchangeable;
4. Participant role does not itself grant authority;
5. on-behalf-of mutations preserve authority provenance;
6. cross-channel correlation does not become authentication;
7. OfferingSelection quantity has validated unit semantics;
8. recipient/service-subject scope is unambiguous when operational outcomes differ;
9. historical snapshots are not rewritten by future configuration changes;
10. Availability/ReservationOption never commit capacity;
11. live Holds + confirmed allocations never exceed effective capacity;
12. expired/released Hold never confirms;
13. hold confirmation has no gap where capacity is unclaimed;
14. every active allocation satisfies an identifiable EffectiveResourceRequirement;
15. confirmed Reservation either has sufficient allocations or is detectably at risk/blocked;
16. pool late-binding never double-counts capacity;
17. Reservation means capacity commitment, never queue position;
18. QueueEntry may exist without Reservation;
19. mixed attendance/outcomes never collapse to Reservation.no_show/completed;
20. partial cancellation releases only affected commitment scope;
21. planned execution times are never overwritten by actual times;
22. Fulfillment identifies concrete requested/recipient/quantity scope;
23. Fulfillment remains historical after refunds/chargebacks;
24. PaymentRequirement has auditable pricing provenance;
25. PaymentEvidence never satisfies PaymentRequirement;
26. authoritative financial facts are append-oriented;
27. PaymentAllocation cannot spend more eligible value than exists;
28. refund/reversal/dispute never erases original financial observation;
29. late payment never resurrects expired capacity;
30. material amendments are explicit commands, not blind updates;
31. policy-based material decisions preserve policy/version provenance;
32. idempotency key reused with different payload conflicts;
33. duplicate callbacks produce at most one logical effect;
34. derived state cannot be arbitrary write authority;
35. agent scope never substitutes subject/resource authorization;
36. local-time ambiguity/DST is resolved explicitly;
37. transition/travel time participates in capacity correctness when material;
38. external inventory dependencies cannot be silently treated as guaranteed fulfillment.

---

## 30. Required vertical slices before stable schema

### Barbershop

Must prove:

- requester ≠ recipient;
- walk-in QueueEntry without Reservation;
- appointment + queue coexistence;
- haircut + beard multi-selection;
- barber + chair requirements;
- partial attendance/no-show;
- resource sickness;
- deposit/cash/card;
- final-capacity race.

### Dental

Must prove:

- child + guardian + payer;
- authority independent from Participant role;
- organization payer / third-party payer;
- staged multi-resource requirements;
- equipment failure;
- multi-recipient admission;
- multiple ServiceSessions;
- partial fulfillment.

### Plumbing / field service

Must prove:

- arrival window;
- Destination/ServiceArea;
- travel/transition constraints;
- technician pool → concrete binding;
- vehicle failure/redispatch;
- destination change after en_route;
- bank transfer/evidence/manual verification;
- late payment after Hold expiry;
- one visit satisfying multiple Requests/Reservations.

### Payments

Must prove:

- partial payment;
- multiple payments → one Requirement;
- one transaction → multiple Requirements;
- overpayment;
- partial refund;
- reversal/return;
- dispute/chargeback after Fulfillment;
- duplicate/out-of-order webhook;
- concurrent reconciliation;
- dishonest/manual verification remains auditable, not magically trustworthy.

### Multi-channel / agent

Must prove:

- Website → WhatsApp → Voice → Human on same Request;
- ExternalCorrelation without bearer authority;
- agent retry duplication;
- hallucinated ID;
- cross-tenant identifier attack;
- unauthorized on-behalf-of mutation;
- stale availability followed by authoritative Hold.

---

## 31. Deliberately deferred

Do not add yet:

```text
ReservationSegment
ReservationSeries
Agreement
Subscription
Quote aggregate unless quote lifecycle is required
Delivery logistics
WorkforceOptimizer
RouteOptimizer
generic pricing DSL
generic rules DSL
generic relationship graph
BPMN/editor universal
full inventory
invoice/tax engine
accounting ledger
advanced OR/k-of-n resource requirements
FX
```

Recurrence may create individual Requests/Reservations until series-level operations become an actual requirement.

---

## 32. Readiness gate before PostgreSQL design

The model is ready for relational design only when `docs/02-pre-sql-domain-contract.md` can answer without ambiguity:

```text
What was requested and for whom?
Which Party participated, and who was authorized to act?
Which channel correlation resumed the Request without becoming authority?
What capacity was promised?
Which effective requirement does every allocation satisfy?
Can queue admission exist independently from Reservation?
How is partial attendance/cancellation scoped?
Can one ServiceSession execute multiple Reservations?
How are field-service transition times prevented from creating impossible schedules?
Why was each amount charged?
What money was authoritatively observed?
How do refunds/reversals/disputes affect net satisfaction?
What was actually fulfilled and for whom?
Which policy/version authorized every material decision?
What happens when two actors race the same invariant?
```

Until those answers are backed by explicit invariants and concurrency ownership, the schema is **not frozen**.