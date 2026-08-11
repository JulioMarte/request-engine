# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.4. El schema PostgreSQL no se congela hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> Este documento define el lenguaje canónico y los boundaries del producto. `docs/01-architecture-v2.md` traduce estas reglas a arquitectura técnica. `docs/02-pre-sql-domain-contract.md` define las garantías que el diseño relacional deberá demostrar.

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
3. quién participó y con qué role;
4. quién estaba autorizado para actuar y bajo qué authority/policy version;
5. qué Offering(s), quantities y fulfillment semantics estaban involucrados;
6. qué capacity se retuvo/comprometió y qué requirements cubría;
7. qué admission y ejecución ocurrieron;
8. cómo se determinó cada importe y obligación;
9. qué dinero fue observado y cómo se distribuyó su valor neto;
10. qué scope se fulfilled y cuál quedó pendiente;
11. qué mutación produjo cada Principal/integration/worker.

Una conversación es contexto externo. Un `Request` es trabajo durable.

---

## 2. Lo que NO es

No es CRM, ERP, identity provider universal, accounting ledger, invoice/tax platform, PSP, banco, PBX, general inventory system, e-commerce platform completa, workforce optimizer, route optimizer, raw GPS store, universal shipping platform, industrial scheduler, BPMN/Temporal clone, generic agent framework ni generic relationship graph.

Puede integrarse con ellos.

### Boundary rule

> Request Engine conserva el mínimo estado autoritativo necesario para decidir, autorizar, comprometer, ejecutar o demostrar un Request. Todo lo demás se referencia o delega.

No absorber un sistema externo completo sólo porque aporta una señal. Tampoco externalizar una verdad mínima si hacerlo impide demostrar por qué una decisión autoritativa fue válida.

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
Requirement template ≠ CommitmentRequirement
CapacityHold ≠ ResourceAllocation
PaymentEvidence ≠ PaymentTransaction
PaymentTransaction ≠ PaymentRequirement
Refund ≠ FinancialReversal
Financial reversal ≠ business obligation cancellation
PaymentTransaction ≠ Fulfillment
PriceDetermination ≠ PaymentRequirement amount derivation
Operational health ≠ Reservation lifecycle
External correlation ≠ authentication/authorization
```

---

## 4. Organization, Principal, Party y authority

### Organization

Tenant boundary. Toda relación tenant-owned crítica permanece dentro de la misma Organization.

### Principal

Actor autenticado que ejecuta una mutación: humano, empleado, service account, agent runtime, provider/webhook principal o worker.

### Party

Identidad de negocio mínima que participa en Requests.

Kinds iniciales:

```text
person
organization
```

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

Una mutación `on_behalf_of` debe poder explicar:

```text
actor/represented Party
action or scope
source/policy
validity
revocation state
version/provenance
```

Request Engine sólo puede prometer serialización fuerte contra **authority localmente materializada**. Authority originada externamente se verifica/snapshotea localmente con source, verified_at y optional valid_until; cambios externos posteriores llegan por callback/reverification. No se promete conocimiento instantáneo de revocaciones externas sin distributed transaction.

Audit conserva la exacta authority version/snapshot usada. No depende de leer posteriormente una fila mutable.

No construir generic ACL/relationship graph.

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

Algunos RequestTypes actúan sobre entidades existentes. Esa relación es distinta de la lineage producida por el Request.

Ejemplo:

```text
cancel_reservation → target Reservation
```

`RequestTarget` es un concepto tipado y cerrado por RequestType. **No autoriza una referencia polimórfica genérica `target_type + target_id` sin integridad referencial fuerte.** El diseño físico debe usar links tipados soportados explícitamente.

### Terminality

Estados terminales iniciales:

```text
completed
cancelled
failed_terminal
```

Son monotónicos. Eventos posteriores como chargeback/reversal/disruption no reabren automáticamente el mismo Request; crean nuevo Request/case/recovery work cuando policy lo requiera.

Completion depende de outcome criteria tipados/versionados evaluados contra facts autoritativos, no de un `workflow_state.done=true` opaco.

---

## 6. Cross-channel continuation

### ExternalCorrelation

Correlaciona Requests con website sessions, WhatsApp threads, voice calls o external tickets.

La relación es N:M semánticamente:

```text
one external interaction → multiple Requests
one Request → multiple external interactions
```

Correlation no es authentication ni authorization.

Website → WhatsApp → Voice → Human puede continuar el mismo Request, pero cada mutation revalida authority y current state.

---

## 7. Offering, Selection y FulfillmentModel

### Offering

Algo que una Organization ofrece.

Kinds iniciales:

```text
service
product
package
custom
```

Si fulfillment depende de stock externo, confirmation requiere commitment/reference externo verificable o policy explícita que acepte el riesgo. `stock observed` no equivale a `inventory committed`.

### OfferingSelection

Selección concreta dentro del Request con Offering, quantity + unit semantics, validated configuration, recipient scope y historical snapshot.

### FulfillmentModel

Cada Offering/version declara cómo se demuestra fulfillment:

```text
binary
quantity
components
external_authoritative
```

`quantity` permite arithmetic remaining scope cuando la unidad lo soporta.

`components` permite outcomes cualitativos sin inventar porcentajes arbitrarios.

No crear fulfillment DSL universal.

---

## 8. Recipient / operational subject scope

Cuando recipients pueden tener outcomes distintos, el modelo debe vincular de forma inequívoca:

```text
Party / RequestParticipant
→ OfferingSelection
→ ReservationItem / admission scope
→ Fulfillment
```

No se requiere un `ServiceSubject` universal si links tipados resuelven el problema.

---

## 9. Workflow

Workflow es tipado, versionado y testeable. Puede pedir input, validar authority, determinar price, crear holds/requirements, esperar external work, confirmar Reservation, coordinar admission/dispatch, registrar Fulfillment y completar/fallar Request.

Los outcome criteria materiales deben permanecer identificables y versionados.

No construir generic workflow DSL/BPMN/state-machine framework.

---

## 10. Pricing y obligation derivation

### PriceDetermination

Explica valor comercial de un scope:

```text
priced scope
currency
base amount
quantity inputs
adjustments/discounts/fees/taxes owned here
pricing source/policy + version
final amount
provenance
override Principal/reason
```

El priced scope es semánticamente tipado. El diseño relacional no puede resolverlo con un opaque polymorphic FK si eso elimina referential integrity.

Historical determination no se reescribe.

### PaymentRequirement amount derivation

Una obligación conserva además un snapshot de cómo se derivó desde commercial value + payment policy:

```text
commercial basis
payment policy/version
calculation inputs
required Money
```

### Shared discounts/amendments

No asumir prorrateo universal. Partial cancellation/repricing ejecuta policy explícita y registra nueva determination/consecuencias.

### Quote

Sólo aparece como entity si necesita lifecycle propio de offer/accept/expire/supersede.

---

## 11. Resource, requirements y capacity

### Resource

Entidad concreta que aporta capacidad:

```text
person
facility
room
chair
equipment
vehicle
```

### ResourceCapability

Capability tenant-scoped.

### ResourceRequirementTemplate

Configuración reusable del Offering.

### CommitmentRequirement

Requirement materializado para una Reservation. Puede cubrir 1..N ReservationItems cuando comparten realmente el mismo compromiso.

```text
Reservation
├─ Item A ─┐
├─ Item B ─┼→ CommitmentRequirement
└──────────┘          ↓
              ResourceAllocation(s)
```

Esto evita double-count de capacity compartida.

### Capacity models

```text
exclusive
units
```

No OR/k-of-n algebra todavía.

---

## 12. CapacityPool

`CapacityPool` es capacity authority reservable para late binding; no es Resource ni ResourceGroup.

V1 soporta sólo member-derived pools con reglas estrictas:

1. membership explícita/versionada;
2. contributors no pueden alimentar simultáneamente reservable pools superpuestos para la misma capacity/interval;
3. pool capacity deriva de members elegibles/disponibles y existing claims;
4. pool claim + concrete binding representan un solo consumption;
5. contributor directo y pool claim compiten mediante el mismo serialization protocol;
6. un pool sólo puede reservarse para un CommitmentRequirement cuando sus members relevantes son fungibles respecto a ese requirement;
7. si fungibility no puede demostrarse, bind concrete Resource durante Hold/confirmation;
8. pérdida posterior de pool capacity produce disruption/recovery, no history rewrite.

No static `pool.capacity=N` sin backing members en V1.

---

## 13. CapacityAuthority y CapacityClaim — conceptos técnicos, no vocabulario comercial

El dominio conserva `Resource`, `CapacityPool`, `CapacityHold` y `ResourceAllocation` como conceptos distintos.

Sin embargo, la arquitectura puede usar una abstracción persistence-internal llamada `CapacityAuthority` para representar el lock target común de un Resource o CapacityPool, y `CapacityClaim` para representar el conflict-space común consumido por Holds y confirmed Allocations.

Estas abstracciones existen para sostener una invariante:

> Live hold claims + confirmed allocation claims nunca exceden la capacity válida del mismo authority/interval.

No son aggregate roots de negocio ni se exponen en API/agent tools.

---

## 14. Availability, Hold y Reservation

### Availability

Query calculada. Puede usar caches/projections pero nunca concede authority.

### ReservationOption

Resultado efímero.

### CapacityHold

Claim temporal autoritativo.

States:

```text
active
confirmed
released
expired
```

Un hold lógico deja de consumir capacity cuando `expires_at <= authoritative current time`, aunque un cleanup worker todavía no haya materializado `expired`. Worker cleanup no define la verdad temporal.

Expired/released nunca confirma. Payment tardío no resucita capacity.

### Reservation

Confirmed capacity commitment.

States:

```text
confirmed
cancelled
closed
```

Terminal Reservation implica cero active capacity-consuming allocations/claims.

Partial cancellation libera/reemplaza sólo scope afectado. Shared CommitmentRequirements se reevalúan bajo el Reservation serialization boundary para no liberar capacity todavía requerida por surviving items.

---

## 15. ResourceAllocation y binding

`ResourceAllocation` satisface un CommitmentRequirement y conserva authority/resource/pool, quantity, interval, status y lineage.

States:

```text
active
released
replaced
```

Pool → concrete binding no crea segundo consumption.

`Assignment` permanece fuera del core mientras Allocation/binding sea única source of truth.

---

## 16. Schedule authority y transition constraints

BusinessHours ≠ AvailabilitySchedule.

ScheduleException:

```text
closed
replace_hours
open_special
capacity_override
```

Toda configuración que pueda cambiar la capacidad reservable de un Resource/Pool debe pertenecer a una **stable schedule/capacity authority revision** contra la cual Holds/confirmations puedan serializarse. Esto evita races donde una nueva ScheduleException aparece después de availability check pero antes del commitment.

V1 field service soporta sólo:

```text
fixed/conservative transition buffers
OR
external feasibility decision + snapshot/provenance
```

No generic pairwise route optimization.

UTC para instantes; IANA timezone + explicit offset/fold para ambiguous local input.

---

## 17. Admission

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

No-show pertenece a admission/recipient/item scope, nunca a global Reservation status.

---

## 18. ServiceSession y Fulfillment

### ServiceSession

Execution real.

```text
Reservation N:M ServiceSession
```

Cancellation/reschedule debe evaluar active session links. Planned timestamps nunca se sobrescriben con actual timestamps.

### Fulfillment

Append-oriented outcome evidence respetando FulfillmentModel y recipient/requested scope.

Refund/reversal nunca borra Fulfillment.

---

## 19. Location, Destination y Dispatch

`Dispatch` representa movement/coordinación hacia **un Destination concreto**. Puede cubrir varias Reservations sólo si comparten ese movement/destination semantics.

States:

```text
planned
assigned
en_route
arrived
cancelled
failed
```

No raw GPS telemetry ni route planning universal.

---

## 20. ReservationPolicy y policy provenance

Cancellation/reschedule/no-show decisions preservan:

```text
policy key/version
evaluated inputs
initiator/reason
recipient/item scope
override Principal/reason
```

Operational health:

```text
valid
at_risk
blocked
```

es projection derivada.

No ReservationDisruption aggregate obligatorio hasta que recovery requiera lifecycle propio.

---

## 21. Payments y financial facts

### PaymentRequirement

Obligación con Money, purpose, payer Party, pricing basis, amount_derivation, policy snapshot y business disposition:

```text
active
waived
cancelled
```

`open/partial/satisfied/overdue` son derivados/materializados.

### PaymentAttempt

Intento de cobro; success no implica settlement.

### PaymentEvidence

Comprobante presentado; nunca settlement por sí solo.

### PaymentTransaction

Financial fact autoritativamente observado.

### PaymentAllocation

Asignación positiva de transaction value hacia Requirement.

---

## 22. Refund, Reversal y PaymentAllocationAdjustment

### Refund

Operation iniciada para devolver valor.

### FinancialReversal / Return

Financial fact que reduce valor previamente elegible.

### PaymentDispute

Lifecycle propio.

### PaymentAllocationAdjustment

Atribuye explícitamente pérdida/corrección de valor a PaymentAllocations.

Para un reversal parcial ambiguo:

1. source/provider identifica attribution;
2. policy versionada determina attribution;
3. o ReconciliationCase bloquea una inferencia falsa.

Invariantes:

```text
net allocation contribution
= positive allocation - invalidating adjustments

sum(adjustments sourced from one reversal)
<= reversal amount

sum(invalidating adjustments against one allocation)
<= its eligible historical contribution
```

Refund/reversal y business obligation disposition son ortogonales. `refund => unpaid` está prohibido como regla universal.

---

## 23. Reconciliation

`ReconciliationCase` existe cuando matching/attribution/tratamiento financiero no es seguro.

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

## 24. Idempotency y operation identity

Dos capas:

### Transport idempotency

Retry de la misma operation/caller.

### Durable operation identity

Server-generated token que puede sobrevivir handoff controlado entre channels/principals.

Replay preserva el mismo logical outcome/reference pero la respuesta sigue current read authorization; idempotency key no es authorization token.

---

## 25. AI agents

```text
LLM interprets/proposes
→ typed semantic command
→ application authorization
→ current-state/authority revalidation
→ policy evaluation
→ authoritative transaction
```

No generic CRUD/status setters. Hallucinated IDs resuelven tenant-first. Screenshot payment claims crean como máximo PaymentEvidence. Availability nunca significa booked capacity.

---

## 26. Canonical cardinalities V2.4

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                     via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
Request N ── M external interaction identities

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

---

## 27. Canonical vocabulary V2.4

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

### Persistence-internal, not business vocabulary

```text
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision (or equivalent stable lock/revision target)
```

### Deliberately deferred

```text
Assignment
ResourceGroup aggregate
HolidayCalendar aggregate
ReservationDisruption aggregate
Quote
ReservationSeries
Agreement
Subscription
Inventory subsystem
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

## 28. Foundation invariants V2.4

1. no cross-tenant authoritative references;
2. no generic polymorphic FK for critical domain relationships;
3. Principal ≠ Party and role ≠ authority;
4. authority-dependent mutations use current locally authoritative version and preserve historical provenance;
5. ExternalCorrelation never grants authority;
6. Request terminal states are monotonic;
7. RequestTarget semantics are separate from generated lineage;
8. OfferingSelection quantity/unit and FulfillmentModel are versioned enough to reconstruct outcomes;
9. shared CommitmentRequirement consumes capacity once;
10. partial cancellation cannot release a shared requirement still needed by surviving items;
11. CapacityPool contributors and direct Resource claims share serialization semantics;
12. pool late binding never double-counts capacity;
13. heterogeneous/non-fungible pools do not use unresolved late binding in V1;
14. Availability/ReservationOption never commit capacity;
15. Hold and confirmed Allocation claims compete in one logical conflict space;
16. schedule/membership changes serialize against a stable authority revision;
17. expired Hold cannot confirm and expiry truth does not depend on cleanup worker timing;
18. terminal Reservation has no active capacity-consuming claims;
19. planned and actual execution timestamps remain distinct;
20. Fulfillment is append-oriented and unaffected historically by later financial events;
21. PaymentEvidence never creates settlement;
22. original financial facts survive refund/reversal/dispute;
23. allocation adjustments obey both reversal budget and allocation budget;
24. business obligation disposition is separate from financial value movement;
25. ambiguous financial attribution opens reconciliation instead of guessing;
26. idempotency prevents duplicate mutation but does not bypass current read authorization;
27. material policy decisions preserve policy/version/provenance;
28. no network call participates inside authoritative DB transaction;
29. capacity/financial/tenant invariants cannot depend only on application pre-checks;
30. all multi-authority mutations use deterministic lock ordering.

---

## 29. Readiness gate

El dominio puede pasar a diseño relacional sólo cuando `docs/02-pre-sql-domain-contract.md` demuestre para cada invariant:

```text
DB constraint
OR stable lock authority + transaction protocol
OR optimistic version protocol
OR explicitly bounded application policy
```

Si la respuesta es “el código normalmente lo comprueba antes”, el schema todavía no está listo.