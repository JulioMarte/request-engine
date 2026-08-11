# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.3. El schema PostgreSQL no se congela hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> Este documento define el lenguaje canónico y las fronteras del producto. `docs/01-architecture-v2.md` traduce estas reglas a arquitectura y `docs/02-pre-sql-domain-contract.md` define las garantías que el futuro schema debe demostrar.

---

## 1. Producto

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Request Engine es un motor transaccional, headless y multi-tenant que transforma intención durable en trabajo estructurado, compromisos verificables de capacidad, obligaciones monetarias, ejecución observable y resultados auditables.

Debe poder responder autoritativamente:

1. qué se pidió;
2. para quién;
3. quién participó y con qué rol;
4. quién estaba autorizado para actuar y bajo qué versión de authority/policy;
5. qué Offering(s) y cantidades estaban involucrados;
6. qué capacidad se retuvo o comprometió y qué requirements cubría;
7. qué admission y ejecución ocurrieron;
8. cómo se determinó cada importe y cada obligación;
9. qué dinero fue observado y cómo se distribuyó su valor neto;
10. qué scope se cumplió y cuál quedó pendiente;
11. qué mutación produjo cada Principal/integration/worker.

Una conversación es contexto externo. Un `Request` es trabajo durable.

---

## 2. Lo que NO es

No es CRM, ERP, identity provider universal, ledger contable, invoice/tax platform, PSP, banco, PBX, inventory system general, e-commerce platform completa, workforce optimizer, route optimizer, raw GPS store, shipping platform universal, industrial scheduler, BPMN/Temporal clone, generic agent framework ni generic relationship graph.

Puede integrarse con ellos.

### Boundary rule

> Request Engine conserva el mínimo estado autoritativo necesario para decidir, autorizar, comprometer, ejecutar o demostrar un Request. Todo lo demás se referencia o delega.

---

## 3. Distinciones que nunca se colapsan

```text
Principal ≠ Party
Participant role ≠ authority
Request lineage ≠ Request target
Request ≠ Reservation
Reservation ≠ QueueEntry
Reservation ≠ ServiceSession
Availability ≠ CapacityHold
Requirement template ≠ commitment requirement
PaymentEvidence ≠ PaymentTransaction
PaymentTransaction ≠ PaymentRequirement
Refund ≠ Reversal
Financial reversal ≠ business obligation cancellation
PaymentTransaction ≠ Fulfillment
PriceDetermination ≠ PaymentRequirement amount derivation
Operational health ≠ Reservation lifecycle
```

---

## 4. Organization, Principal, Party y authority

### Organization

Tenant boundary. Toda relación tenant-owned crítica debe permanecer dentro de la misma Organization.

### Principal

Actor autenticado que ejecuta una mutación: humano, empleado, service account, agent runtime, provider/webhook principal o worker.

`Principal` responde quién ejecutó la acción; no quién recibe/paga/solicita el servicio.

### Party

Identidad de negocio mínima que puede participar en un Request.

Kinds iniciales:

```text
person
organization
```

No es CRM ni directory universal.

### RequestParticipant

Relaciona Party con Request y expresa role:

```text
requester
recipient
payer
guardian
authorized_contact
```

Role nunca concede authority por sí solo.

### AuthorityGrant / Representation

Cuando una mutación depende de actuar por otro subject, la decisión debe poder explicar:

```text
actor/represented Party
action or scope
source/policy
validity
revocation state
version
```

Authority utilizada por una mutación es una dependencia transaccional: si puede revocarse concurrentemente, el command debe revalidar/serializar contra su estado actual.

La historia no apunta simplemente al estado mutable actual del grant. Audit conserva versión/snapshot/provenance de la authority usada en el momento de la decisión.

No construir un ACL/relationship graph universal.

---

## 5. Request, RequestType y RequestTarget

### Request

Unidad durable de intención procesable.

No asumir:

```text
1 Request = 1 Offering = 1 Reservation = 1 ServiceSession = 1 Fulfillment
```

### RequestType

Describe intención, por ejemplo:

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

### RequestTarget

Algunos RequestTypes actúan sobre una entidad existente. Esa relación es distinta de la lineage generada por el Request.

Ejemplos:

```text
cancel_reservation   → target Reservation
reschedule_reservation → target Reservation
```

`RequestTarget` es un child/link tipado, tenant-scoped y validado por RequestType. No es un generic relationship graph.

### Request terminality

Los terminal states son monotónicos inicialmente:

```text
completed
cancelled
failed_terminal
```

No se reabre un Request terminal automáticamente porque posteriormente aparezca un chargeback, reversal o problema operacional. Si hace falta nuevo trabajo se crea un nuevo Request/case correlacionado.

---

## 6. Cross-channel continuation

### ExternalCorrelation

Asocia Request con identifiers externos como website session, WhatsApp thread, voice call o ticket externo.

Correlation no es authentication ni authorization.

Un mismo external thread puede correlacionarse con varios Requests y un Request con varios external identifiers. No asumir uniqueness global `(channel, external_id)` → un Request.

Website → WhatsApp → Voice → Human puede continuar el mismo Request, pero cada mutación revalida authority.

---

## 7. Offering, Selection y fulfillment semantics

### Offering

Algo que una Organization ofrece.

Kinds iniciales:

```text
service
product
package
custom
```

No sustituye inventario ni commerce platform.

Si fulfillment depende de stock externo, confirmation requiere commitment/reference externo verificable o policy explícita que acepte el riesgo. Una observación de stock no equivale a inventory commitment.

### OfferingSelection

Selección concreta dentro del Request con Offering, quantity + unit semantics, validated configuration, recipient scope y snapshot histórico.

### FulfillmentModel

Cada Offering/version define cómo puede demostrarse su fulfillment. V1 soporta sólo modelos explícitos y pequeños:

```text
binary
quantity
components
external_authoritative
```

`quantity` permite aritmética determinística, por ejemplo 10 seats → 8 fulfilled.

`components` permite resultados cualitativos sin inventar fracciones, por ejemplo diagnosis + temporary_fix + permanent_repair.

No crear un fulfillment DSL universal.

Cuando un Selection contribuye a commitment/payment/fulfillment, cambios materiales se hacen mediante commands explícitos y snapshots/revisions.

---

## 8. Recipient / operational subject scope

El modelo debe poder relacionar explícitamente, cuando sea necesario:

```text
Party / RequestParticipant
→ OfferingSelection
→ ReservationItem / admission scope
→ Fulfillment
```

Así pueden existir mixed outcomes sin status global falso.

No crear todavía un `ServiceSubject` universal si links tipados resuelven el problema.

---

## 9. Workflow y completion criteria

Workflow es tipado, versionado y testeable. Puede pedir input, validar authority, determinar price, crear holds/requirements, esperar external work, confirmar Reservation, coordinar admission/dispatch, registrar Fulfillment y cerrar Request.

Request completion no puede depender únicamente de un blob como:

```text
workflow_state = {"done": true}
```

Los outcome criteria materiales deben ser tipados/versionados y evaluables contra facts autoritativos: required fulfillment scopes, required approvals, payment dispositions u otros criterios explícitos.

No construir generic workflow DSL/BPMN/state-machine framework.

---

## 10. Pricing y obligation derivation

### PriceDetermination

Explica el valor comercial de un scope:

```text
scope
currency
base amount
quantity inputs
adjustments/discounts/fees/taxes owned here
pricing source/policy + version
final amount
provenance
override Principal/reason
```

Historical determination no se reescribe.

### PaymentRequirement amount derivation

Una obligación no siempre equivale al precio completo. Ejemplo:

```text
commercial value = 55
payment policy = 50% deposit
PaymentRequirement = 27.50
```

Por tanto PaymentRequirement conserva además un `amount_derivation` snapshot con:

```text
commercial/pricing basis
payment policy + version
calculation inputs
required Money
```

No convertir PriceDetermination en generic financial calculator.

### Shared discounts / amendments

Si un discount aplica a varios selections, una cancelación parcial no asume prorrateo universal. El command vuelve a evaluar la pricing/amendment policy y registra nueva determination/consecuencias explícitas.

### Quote

Sólo se convierte en entity si necesitamos lifecycle propio de offer/accept/expire/supersede.

---

## 11. Resource y capacity authority

### Resource

Entidad concreta cuya capacidad limita el fulfillment:

```text
person
facility
room
chair
equipment
vehicle
```

### ResourceCapability

Capability tenant-scoped ofrecida por Resource.

### ResourceRequirementTemplate

Configuración reusable del Offering.

### CommitmentRequirement

Requirement materializado para una Reservation y uno o varios ReservationItems.

Esta es una corrección V2.3: un mismo requirement puede cubrir múltiples items cuando comparten realmente el mismo compromiso de capacidad.

```text
Reservation
├─ ReservationItem A ─┐
├─ ReservationItem B ─┼→ CommitmentRequirement
└─────────────────────┘          ↓
                         ResourceAllocation(s)
```

Una Allocation satisface un CommitmentRequirement, no necesariamente un único ReservationItem.

No double-count de un chair/barber/equipment compartido por dos items del mismo commitment.

### Capacity models

```text
exclusive
units
```

No OR/k-of-n algebra todavía.

---

## 12. CapacityPool y grouping

V2.3 deja de tratar `pool` como un Resource ordinario.

### CapacityPool

Reservable capacity authority para late binding de Resources fungibles.

Un pool reservable debe tener semántica demostrable. V1 permite sólo una estrategia restringida:

```text
member-derived reservable pool
```

Reglas V1:

1. membership que contribuye capacity es explícita y versionada;
2. un Resource no puede contribuir simultáneamente a dos reservable pools que compitan por la misma capacity/intervalo;
3. effective pool capacity deriva de members elegibles/disponibles y claims ya existentes;
4. pool claim y concrete member binding representan el mismo commitment, nunca dos consumos;
5. binding posterior debe garantizar que queda un miembro concreto elegible;
6. si el pool pierde capacidad después de confirmation, se detecta disruption/recovery; no se falsifica historia.

`ResourceGroup` continúa siendo sólo query/grouping helper y no capacity authority.

No soportar pools superpuestos arbitrarios en V1.

---

## 13. Availability, Hold y Reservation

### Availability

Query sin writes.

### ReservationOption

Resultado efímero; no garantiza nada.

### CapacityHold

Claim temporal autoritativo que compite en el mismo capacity conflict space que la futura Reservation.

States:

```text
active
confirmed
released
expired
```

Expired/released nunca confirma. Payment tardío no resucita capacity.

### Reservation

Significa únicamente confirmed capacity commitment.

V2.3 simplifica lifecycle:

```text
confirmed
cancelled
closed
```

`expired` se elimina del lifecycle de Reservation inicial; expiry pertenece naturalmente a Hold/offer/admission windows, no a un commitment confirmado genérico.

`closed` significa que no queda capacity comprometida. `cancelled` significa termination por cancellation.

Invariante:

```text
Reservation terminal
→ no capacity-consuming allocations remain active
```

Partial cancellation libera/reemplaza sólo el scope afectado. Global `cancelled` sólo cuando no queda commitment sobreviviente y cancellation fue la causa terminal.

---

## 14. ResourceAllocation y binding

`ResourceAllocation` asigna capacity a un `CommitmentRequirement` y conserva resource/pool, quantity, interval, status y lineage.

States:

```text
active
released
replaced
```

Replacement preserva historia.

Pool → concrete binding no crea un segundo capacity consumption.

`Assignment` sigue fuera del core mientras Allocation/binding sea la única fuente de verdad.

---

## 15. Travel/setup/transition time

Request Engine no se convierte en route optimizer.

V1 soporta dos mecanismos explícitos:

```text
fixed/conservative transition buffers
OR
external feasibility decision + snapshot/provenance
```

No prometer scheduling dinámico basado en pairwise travel-time arbitrario dentro del core V1.

Si un buffer/feasibility constraint material hace imposible dos commitments, debe participar en capacity validation.

---

## 16. Admission

Admission es ortogonal a Reservation.

### CheckIn

Presence/readiness fact para scope concreto.

### QueueEntry

Puede existir sin Reservation.

```text
walk-in: Request/subject → QueueEntry → ServiceSession
appointment: Reservation → CheckIn → QueueEntry → ServiceSession
```

### WaitlistEntry

No consume capacity:

```text
WaitlistEntry → match → CapacityHold → acceptance → Reservation
```

No-show se aplica a admission/recipient/item scope, nunca globalmente a Reservation.

---

## 17. ServiceSession, cancellation y Fulfillment

### ServiceSession

Execution real.

```text
Reservation N:M ServiceSession
```

Una session puede ejecutar varias Reservations y una Reservation varias sessions. Walk-in puede generar Session sin Reservation.

Cancellation/reschedule commands deben evaluar active ServiceSession links. Una Reservation no puede cancelarse como si execution no hubiese empezado cuando existe ejecución activa relevante; policy decide stop/partial/corrective semantics.

### Fulfillment

Append-oriented evidence de outcome para un Request/scope/recipient.

Debe respetar el FulfillmentModel del Offering snapshot.

Refund/reversal nunca borra Fulfillment.

---

## 18. Location, Destination y Dispatch

Location y Destination conservan snapshots relevantes.

### Dispatch

V2.3 estrecha su definición:

> Dispatch representa movimiento/coordinación hacia **un Destination concreto**.

Puede vincular varias Reservations sólo si ese movimiento/destination es común. Si hacen falta múltiples destinos, son múltiples Dispatches. Así Request Engine no se convierte en trip/route planner.

States:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No raw GPS telemetry.

---

## 19. Schedules y policy provenance

BusinessHours ≠ AvailabilitySchedule.

ScheduleException:

```text
closed
replace_hours
open_special
capacity_override
```

HolidayCalendar no es aggregate core inicial.

UTC para instantes autoritativos; IANA timezone + explicit fold/offset para input local ambiguo. Nonexistent local time se rechaza o resuelve por policy explícita.

Toda decisión material basada en policy conserva policy/version, evaluated inputs y override provenance.

---

## 20. PaymentRequirement y financial facts

### PaymentRequirement

Obligación monetaria concreta con Money, purpose, payer Party, pricing basis, amount_derivation, policy snapshot y disposition explícita:

```text
active
waived
cancelled
```

`open/partial/satisfied/overdue` son derivados/materializados desde valor financiero neto elegible.

### PaymentAttempt

Intento de cobro; success no implica settlement.

### PaymentEvidence

Comprobante presentado. Nunca crea settlement por sí solo.

### PaymentTransaction

Financial fact observado autoritativamente.

### PaymentAllocation

Asignación positiva de valor de PaymentTransaction hacia PaymentRequirement.

---

## 21. Refund, Reversal y PaymentAllocationAdjustment

### Refund

Operación iniciada para devolver dinero.

### FinancialReversal / Return

Financial fact externo/interno autoritativo que reduce valor previamente elegible.

### PaymentDispute

Lifecycle propio; no es Refund.

### PaymentAllocationAdjustment

V2.3 introduce una primitiva append-oriented para atribuir explícitamente pérdida/corrección de valor a PaymentAllocations/Requirements.

Ejemplo:

```text
Transaction 100
Allocation A = 50
Allocation B = 50
Reversal = 30
```

El sistema **no puede** inferir silenciosamente si A pierde 30, B pierde 30 o ambos 15.

Debe ocurrir una de estas opciones:

1. provider/source identifica attribution concreta;
2. policy versionada aplica una regla determinista;
3. se abre ReconciliationCase y ninguna satisfaction ambigua se inventa.

`PaymentAllocationAdjustment` registra el efecto atribuido y su provenance.

Invariantes:

```text
net contribution of allocation
= positive allocation - attributed invalidating adjustments

sum net positive contributions from transaction
<= current eligible transaction value
```

No borrar allocations históricas.

### Refund no reabre obligación automáticamente

Refund/reversal y business obligation disposition son ortogonales.

Ejemplos:

- goodwill refund puede mantener Requirement satisfied/cancelled según policy;
- cancellation refund normalmente acompaña Requirement cancellation/waiver/replacement;
- bank return puede hacer Requirement outstanding de nuevo.

El command/policy debe registrar explícitamente la consecuencia de negocio. Nunca asumir `refund => unpaid`.

---

## 22. Reconciliation

ReconciliationCase existe cuando matching/attribution/tratamiento financiero no es seguro.

Casos:

```text
missing_reference
ambiguous_match
partial_reversal_attribution
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
```

No adivinar.

---

## 23. Idempotency

Toda mutación reintentable soporta idempotency.

Dos conceptos:

### Transport idempotency

Evita duplicación por retry del mismo operation/caller.

### Durable operation identity

Para handoffs controlados, un server-generated operation/action token puede sobrevivir Website → WhatsApp → Voice → Human y evitar repetir la misma operación ya iniciada.

No intentar deduplicar mágicamente dos intenciones humanas independientes.

Replay garantiza el mismo **logical outcome/reference**, pero la representación devuelta sigue sujeta a autorización de lectura vigente; una idempotency key no es permiso para revelar datos después de revocation.

---

## 24. AI agents

```text
LLM interprets/proposes
→ typed command
→ application authorization
→ current-state + authority revalidation
→ policy evaluation
→ transaction
```

Tools son semánticos, no generic CRUD/status setters.

Hallucinated IDs resuelven tenant-first. Screenshot/payment claims crean como máximo PaymentEvidence. Availability nunca equivale a booked capacity.

Mutating tools reciben/generan operation identity fuera del razonamiento libre del LLM cuando sea posible.

---

## 25. Cardinalidades V2.3

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                     via RequestParticipant
Request 1 ── 0..N RequestTarget
Request 1 ── 0..N OfferingSelection
Request N ── M external correlation identities

Request N ── M Reservation               via Selection/ReservationItem lineage
OfferingSelection N ── M Reservation     via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CommitmentRequirement 1 ── 1..N ResourceAllocation

Reservation N ── M ServiceSession
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

Dispatch representa un Destination; varias Reservations pueden vincularse sólo cuando comparten el mismo movement/destination semantics.

---

## 26. Canonical vocabulary V2.3

### Core

```text
Organization
Principal
Party
AuthorityGrant / Representation
RequestParticipant
RequestType
RequestTarget
Request
ExternalCorrelation
Offering
OfferingSelection
FulfillmentModel
Workflow
PriceDetermination
Fulfillment
```

### Capacity

```text
Resource
ResourceCapability
ResourceRequirementTemplate
CommitmentRequirement
CapacityPool
CapacityHold
Reservation
ReservationItem
ResourceAllocation
```

### Admission / execution

```text
AdmissionPolicy
CheckIn
QueueEntry
WaitlistEntry
ReservationPolicy
ServiceSession
```

### Time / place / field

```text
BusinessHours
AvailabilitySchedule
ScheduleException
Location
Destination
ServiceArea
Dispatch
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
PaymentAllocationAdjustment
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

### Deliberadamente diferidos

```text
Assignment
ResourceGroup as domain aggregate
HolidayCalendar aggregate
ReservationDisruption aggregate
Quote
ReservationSeries
Agreement
Subscription
InventoryReservation subsystem
Invoice
Order
Ledger
Generic Amendment
Generic Policy DSL
Generic Workflow DSL
Route optimizer
Overlapping reservable pools
Advanced OR/k-of-n requirements
```

---

## 27. Invariantes fundacionales V2.3

1. no cross-tenant references;
2. Principal ≠ Party;
3. role ≠ authority;
4. authority mutable se revalida dentro de la authoritative transaction cuando determina permiso;
5. historical authority decision conserva versión/snapshot;
6. RequestTarget ≠ Request→Reservation lineage;
7. terminal Request no se reabre automáticamente;
8. correlation no concede authority;
9. quantity y FulfillmentModel son explícitos/versionados;
10. fulfillment scope nunca se inventa como fracción si el Offering no es quantity-based;
11. PriceDetermination ≠ PaymentRequirement amount derivation;
12. shared discount amendments no se prorratean sin policy;
13. CommitmentRequirement puede cubrir varios ReservationItems;
14. shared requirement no double-counts capacity;
15. CapacityPool tiene capacity authority demostrable y no overlapping contributors en V1;
16. live Holds + active Allocations nunca exceden capacity efectiva;
17. Hold expiry/confirmation se serializan;
18. Reservation significa sólo capacity commitment;
19. terminal Reservation no tiene active capacity-consuming allocations;
20. QueueEntry puede existir sin Reservation;
21. ServiceSession N:M Reservation;
22. cancellation evalúa active execution links;
23. Dispatch representa un Destination, no route plan;
24. travel correctness V1 usa buffer conservador o external feasibility snapshot;
25. PaymentEvidence nunca crea settlement;
26. financial facts son append-oriented;
27. partial reversal attribution nunca se adivina;
28. PaymentAllocationAdjustment hace determinista el net contribution;
29. refund/reversal no cambian obligation disposition implícitamente;
30. overpayment puede permanecer unallocated;
31. duplicate callbacks no duplican logical effects;
32. idempotency replay no evade current disclosure authorization;
33. operation identity puede sobrevivir handoff multicanal;
34. workflow completion depende de typed/versioned outcome criteria, no un boolean opaco;
35. derived states no son arbitrary write authority;
36. DST/local-time ambiguity se resuelve explícitamente.

---

## 28. Readiness gate

Antes de congelar PostgreSQL debemos demostrar al menos:

```text
shared chair/resource across multiple ReservationItems without double count
pool capacity and concrete binding without phantom capacity
partial reversal attribution across multiple PaymentRequirements
goodwill refund vs bank return with different obligation outcomes
cancel/reschedule Request targeting an existing Reservation
concurrent authority revocation vs mutation
multi-channel operation retry with changed Principal
qualitative/component fulfillment
terminal Request receiving later chargeback
Reservation close/cancel with zero active capacity claims
```

Si una de estas respuestas depende de “el application code normalmente sabrá qué hacer”, el schema todavía no está listo.