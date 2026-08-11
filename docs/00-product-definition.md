# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.5. El schema PostgreSQL no se congela hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
>
> Este documento define lenguaje, ownership y semántica del dominio. `docs/01-architecture-v2.md` define protocolos técnicos. `docs/02-pre-sql-domain-contract.md` es el gate normativo previo a SQL.

---

## 1. Producto

```text
Something requests something
           ↓
Request Engine determines
           ↓
what deterministic work must happen
```

Request Engine es un motor transaccional, headless y multi-tenant que transforma intención durable en trabajo estructurado, compromisos verificables de capacidad, obligaciones monetarias, ejecución observable y resultados auditables.

El producto conserva cinco verdades durables:

1. **Intent truth** — qué fue solicitado y para quién.
2. **Authority truth** — quién podía producir cada mutación material y bajo qué authority/policy version.
3. **Commitment truth** — qué capacidad fue retenida o comprometida y para qué requirement.
4. **Financial truth** — qué se debía, qué valor financiero fue observado, con qué finality, y cómo fue aplicado.
5. **Outcome truth** — qué parte del scope solicitado fue cumplida, por qué evidencia y qué quedó pendiente.

Una conversación, llamada o thread es contexto externo. Un `Request` es trabajo durable.

---

## 2. Boundary

Request Engine NO es CRM, ERP, IdP universal, accounting ledger, invoice/tax engine, PSP, banco, PBX, inventory system, e-commerce platform completa, workforce optimizer, route optimizer, GPS telemetry store, universal shipping platform, industrial scheduler, BPMN/Temporal clone, generic workflow platform, generic relationship graph ni framework genérico de agentes.

Puede integrarse con ellos.

> **Boundary rule:** conservar el mínimo estado autoritativo necesario para decidir, autorizar, comprometer, ejecutar o demostrar un Request. Delegar el resto sin externalizar las cinco verdades anteriores.

---

## 3. Distinciones que nunca se colapsan

```text
Principal ≠ Party
Participant role ≠ authority
Request target ≠ generated lineage
Request ≠ Reservation
Reservation ≠ QueueEntry
Reservation ≠ ServiceSession
ServiceSession ≠ Fulfillment
Availability ≠ CapacityHold
CapacityHold ≠ ResourceAllocation
ResourceRequirementTemplate ≠ CommitmentRequirement
PaymentEvidence ≠ PaymentTransaction
PaymentAttempt success ≠ usable financial value
PaymentTransaction ≠ PaymentRequirement
Refund ≠ FinancialReversal
FinancialReversal ≠ business obligation cancellation
PriceDetermination ≠ PaymentRequirement amount derivation
Operational health ≠ Reservation lifecycle
ExternalCorrelation ≠ authentication/authorization
Observed stock ≠ committed inventory
```

---

## 4. Organization, Principal, Party y Representation

### Organization

Hard tenant boundary. Toda relación tenant-owned crítica permanece dentro de la misma Organization.

### Principal

Actor autenticado o autenticable que ejecuta una operación: humano, employee identity, service account, agent runtime, provider/webhook principal o worker.

### Party

Identidad de negocio mínima involucrada en Requests.

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

### Representation

Nombre canónico para authority materializada que permite actuar `on_behalf_of` de una Party o subject scope.

Debe poder explicar:

```text
represented Party / subject
authorized Principal or Party
action/scope
source/policy
valid_from / valid_until?
revocation state
version/provenance
```

Authority externa se verifica y snapshottea localmente con source, verified_at, version/reference y optional validity window. Request Engine no promete conocimiento instantáneo de revocaciones externas.

Audit conserva la versión exacta usada para cada decisión material.

No construir generic ACL graph.

---

## 5. Request

### Request

Unidad durable de intención procesable.

No asumir:

```text
1 Request = 1 Offering = 1 Reservation = 1 ServiceSession = 1 Fulfillment
```

Estados semánticos iniciales:

```text
active
waiting
completed
cancelled
failed_terminal
```

Terminalidad es monotónica. Chargeback, disruption o reversal posteriores no reabren automáticamente el Request; generan recovery work, case o nuevo Request cuando corresponda.

Completion depende de outcome criteria tipados/versionados evaluados contra facts autoritativos.

### RequestType

Describe la intención, por ejemplo:

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

Entidad existente sobre la que un Request pretende actuar. Es distinta de la lineage producida por ese Request.

```text
cancel_reservation → target Reservation
reschedule_reservation → target Reservation
```

No usar authoritative generic `(target_type, target_id)` sin FK real.

---

## 6. Cross-channel continuation

### ExternalCorrelation

Relaciona Requests con website sessions, WhatsApp threads, voice calls, tickets u otras interaction identities.

Semántica N:M:

```text
one interaction → many Requests
one Request → many interactions
```

Correlation nunca concede authority.

Website → WhatsApp → Voice → Human puede continuar el mismo Request, pero cada mutación revalida Principal, tenant, Representation, current state, policy e idempotency.

---

## 7. Offering, Selection y requested scope

### Offering

Algo que una Organization ofrece.

```text
service
product
package
custom
```

Si fulfillment depende de inventario externo, confirmation requiere commitment/reference externo verificable o policy explícita que acepte el riesgo. Stock observado no equivale a inventory committed.

### OfferingSelection

Selección concreta dentro de un Request con:

```text
Offering/version
quantity
unit semantics
validated configuration
recipient scope
historical snapshot
```

No existe quantity sin unidad semántica explícita.

### FulfillmentModel

Cada Offering/version declara cómo se demuestra outcome:

```text
binary
quantity
components
external_authoritative
```

`quantity` sólo permite arithmetic remaining scope cuando la unidad es aditiva.

`components` usa component keys versionadas; no porcentajes inventados.

No construir fulfillment DSL universal.

---

## 8. Fulfillment — definición normativa V2.5

`ServiceSession` representa **ejecución real**.

`Fulfillment` representa **la aplicación append-oriented de evidencia de outcome a un scope solicitado de exactamente un Request**.

No representa la visita, sesión, trabajo físico ni pago.

Un hecho operacional puede satisfacer varios Requests mediante Fulfillments separados:

```text
ServiceSession S
├─ Fulfillment F1 → Request A / requested scope A
└─ Fulfillment F2 → Request B / requested scope B
```

Cada Fulfillment debe identificar inequívocamente:

```text
Request
requested scope
OfferingSelection when applicable
recipient/subject scope when applicable
ServiceSession or external source when applicable
FulfillmentModel/version
outcome quantity/components/result
evidence/provenance
observed_at / occurred_at when distinct
```

Correcciones no borran historia. Se añaden correction/supersession facts o nuevos Fulfillments según semántica, preservando lineage.

Refund, reversal o dispute nunca borran Fulfillment.

---

## 9. Workflow

Workflow es tipado, versionado y testeable. Puede pedir input, validar authority, determinar price, crear requirements/holds, esperar trabajo externo, confirmar Reservation, coordinar admission/dispatch, registrar Fulfillment y completar/fallar Request.

Outcome criteria materiales permanecen identificables y versionados.

No construir generic workflow DSL/BPMN/state-machine framework.

---

## 10. Pricing y obligations

### PriceDetermination

Explica valor comercial de un scope tipado:

```text
priced scope
currency
base amount
quantity inputs
adjustments/discounts/fees/taxes supplied or owned here
pricing source/policy + version
final amount
provenance
override Principal/reason
```

Request Engine puede conservar impuestos/fees ya determinados por una pricing source o reglas explícitamente owned, pero no se convierte en tax platform universal.

Historical determination no se reescribe.

### PaymentRequirement

Obligación monetaria concreta. Conserva:

```text
payer Party
purpose
commercial basis
PriceDetermination reference/snapshot
PaymentPolicy/version
calculation inputs
required Money
business disposition
```

Business disposition:

```text
active
waived
cancelled
```

`open`, `partial`, `satisfied`, `overdue` son derivados/materializados desde net valid allocations + policy/time.

No manual `paid=true`.

---

## 11. Resources, requirements y capacity

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

Capability tenant-scoped y versionable cuando afecte commitments históricos.

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

Shared requirement consume capacidad una sola vez.

Capacity models V1:

```text
exclusive
units
```

No OR/k-of-n algebra todavía.

---

## 12. CapacityPool

`CapacityPool` es una capacity authority reservable para late binding; no es Resource ni ResourceGroup.

V1 sólo permite member-derived pools con contributors fungibles para el requirement concreto.

Reglas:

1. membership explícita/versionada;
2. contributors no alimentan reservable pools superpuestos para la misma capacity conflict space;
3. pool capacity deriva de eligible members y live claims;
4. pool claim + concrete realization son un solo consumption;
5. contributor directo y pool claim compiten bajo el mismo serialization protocol;
6. unresolved late binding sólo cuando fungibility es demostrable;
7. si no, bind concrete Resource durante Hold/confirmation;
8. pérdida posterior de capacity produce disruption/recovery, no history rewrite.

---

## 13. CapacityHold — atomic commitment set V2.5

`CapacityHold` ya no se define como un claim individual. Es el **commitment set temporal autoritativo** usado para reservar provisionalmente todo el capacity scope necesario para una futura Reservation.

Un Hold puede cubrir 1..N CommitmentRequirement candidates y producir 1..N internal `CapacityClaim`s sobre 1..N CapacityAuthorities.

Regla central:

> **Atomicity:** para un requested commitment que requiere varios recursos/capacities simultáneamente, todos los claims obligatorios se adquieren en una única transacción autoritativa o ninguno se adquiere.

Ejemplo:

```text
Dental cleaning
CapacityHold H
├─ dentist claim
├─ chair claim
├─ room claim
└─ equipment claim
```

Está prohibido exponer como `active` un Hold cuyo required claim set quedó parcialmente adquirido.

Partial hold sólo existe si el workflow declara explícitamente requirements independientes y partial commitment permitido; nunca como consecuencia accidental de failure intermedio.

States:

```text
active
confirmed
released
expired
```

Un Hold consume capacity sólo mientras:

```text
state = active
AND expires_at > authoritative wall-clock time
```

Expired/released nunca confirma. Payment tardío no resucita capacity.

---

## 14. CapacityAuthority y CapacityClaim — internos

`CapacityAuthority` es el stable lock/revision target de un Resource o CapacityPool reservable.

`CapacityClaim` es el common persistence conflict-space para Hold claims y confirmed Allocation claims.

No son business aggregates ni agent/API vocabulary.

Invariante:

> live hold claims + active allocation claims nunca exceden la capacidad válida del mismo authority/interval.

---

## 15. Reservation y ResourceAllocation

### Reservation

Compromiso confirmado de capacity y requested scope.

```text
confirmed
cancelled
closed
```

No usar global statuses `completed`, `no_show`, `checked_in`, `waiting`, `in_service` o `en_route`.

Terminal Reservation implica cero active capacity-consuming claims.

### ResourceAllocation

Domain truth que satisface un CommitmentRequirement usando Resource/CapacityPool authority, quantity e interval.

```text
active
released
replaced
```

Hold confirmation transforma/realiza el complete required claim set de forma atómica. Nunca puede producir una Reservation confirmada con requirements obligatorios parcialmente cubiertos.

`Assignment` permanece fuera del core mientras Allocation/binding sea la única source of truth.

---

## 16. Schedules, location y temporal semantics

BusinessHours ≠ AvailabilitySchedule.

ScheduleException:

```text
closed
replace_hours
open_special
capacity_override
```

Todo cambio capaz de modificar reservability pertenece a una stable capacity/schedule authority revision.

### Resource ↔ Location

Un Resource puede operar en múltiples Locations a través del tiempo sin duplicarse como Resource.

Eligibility/reservability puede depender de:

```text
Resource
Location/service context
interval
capability
schedule revision
```

Location-changing schedule/configuration debe invalidar la misma authority revision usada por Holds/confirmations.

UTC para instantes. Local input usa IANA timezone y resolución explícita de ambiguous/nonexistent local times mediante offset/fold o rechazo.

---

## 17. Admission, queues y waitlists

Admission es ortogonal a Reservation.

### AdmissionScope

Concepto semántico, no necesariamente nueva aggregate/table. Identifica inequívocamente el subject/item/Reservation scope al que aplican CheckIn, QueueEntry y no-show facts.

### CheckIn

Presence/readiness fact para AdmissionScope concreto.

### QueueEntry

Lifecycle operacional de espera. Puede existir sin Reservation.

```text
walk-in: Request/subject → QueueEntry → ServiceSession
appointment: Reservation → CheckIn → QueueEntry → ServiceSession
```

La `position` absoluta no es business truth estable. El orden se deriva de ordering keys/facts/policy; estimaciones son projections.

### WaitlistEntry

Interés en capacity no comprometida:

```text
WaitlistEntry → match → CapacityHold → acceptance → Reservation
```

Waitlist nunca consume capacity directamente.

No-show pertenece a AdmissionScope/recipient/item, nunca a Reservation global.

---

## 18. ServiceSession

Execution real.

```text
Reservation N:M ServiceSession
```

Una ServiceSession puede contribuir a múltiples Requests/Fulfillments.

Planned timestamps nunca se sobrescriben con actual timestamps.

Cancellation/reschedule debe serializar contra active session linkage cuando la ejecución pueda haber comenzado.

---

## 19. Location, Destination, ServiceArea y Dispatch

`Location` es lugar operativo de la Organization.

`Destination` es el lugar concreto donde una ejecución debe ocurrir.

`ServiceArea` expresa eligibility geográfica, no routing.

`Dispatch` representa movimiento/coordinación hacia un Destination concreto y puede cubrir varias Reservations sólo si comparten movement/destination semantics.

```text
planned
assigned
en_route
arrived
cancelled
failed
```

### Destination mutation rule

Destination nunca se cambia silenciosamente después de dispatch planning. Un cambio preserva old destination + initiator + reason, invalida feasibility snapshot relevante y obliga a re-evaluar movement/commitment consequences.

V1 field service soporta:

```text
fixed/conservative transition buffers
OR
external feasibility decision + snapshot/provenance
```

Cualquier cambio material de Destination, interval, assigned Resource o relevant schedule invalida la feasibility decision previa.

No route graph ni raw high-frequency GPS telemetry.

---

## 20. ReservationPolicy y Amendment Contract

Cancellation/reschedule/no-show decisions preservan:

```text
policy key/version
evaluated inputs
initiator/reason
recipient/item scope
override Principal/reason
```

### Amendment Contract V2.5

No se crea `GenericAmendment` aggregate.

Pero toda operación post-commitment que cambie materialmente scope o consequences debe preservar un contrato transversal:

```text
operation identity
initiator Principal / represented Party
reason
policy/version
before authoritative references/version
after authoritative references/version
replaced/released/created lineage
evaluated inputs
override provenance when applicable
occurred_at
```

Aplica al menos a:

```text
reschedule
partial cancellation
resource replacement
destination change
repricing
payer/recipient corrections that alter obligations
capacity recovery
```

History no se reescribe para simular que el estado anterior nunca existió.

Operational health:

```text
valid
at_risk
blocked
```

es projection derivada.

No `ReservationDisruption` aggregate obligatorio hasta demostrar lifecycle propio.

---

## 21. Payment observations y finality V2.5

### PaymentAttempt

Intento de iniciar/capturar/cobrar valor mediante provider. Success no implica que exista valor financiero allocatable.

### PaymentEvidence

Comprobante presentado por humano/sistema. Nunca crea settlement ni usable value por sí solo.

### PaymentTransaction

Financial fact autoritativamente observado por una source confiable dentro del boundary configurado.

Debe expresar conceptualmente:

```text
direction
Money amount/currency
source kind
PaymentProviderConnection / financial account reference when applicable
external transaction identity when available
occurred_at/effective_at
observed_at
counterparty identity/reference when known
financial status/finality
eligible value for local allocation
provenance / observation method
correction/reversal lineage
```

### Financial finality

Request Engine no finge que todos los rails financieros tienen el mismo lifecycle.

Finality/status vocabulary interno debe poder distinguir al menos conceptualmente:

```text
observed_pending
observed_available
observed_final
invalidated/reversed through separate financial fact
```

La exacta mapping proviene del adapter/provider/bank policy. Sólo value declarado **eligible for allocation** por una versioned financial-source policy puede satisfacer PaymentRequirements.

Un provider webhook `payment_succeeded` no se convierte automáticamente en `observed_final`.

### Manual financial verification

`manual_bank_verification` o `cash_verification` puede crear authoritative financial fact sólo mediante un command privilegiado que preserve:

```text
verifier Principal
authority/scope
source/account/cash context
observed evidence/reference
amount/currency
occurred_at/observed_at
reason
policy/version
optional second-approval requirement
```

Un screenshot analizado por IA sólo puede crear PaymentEvidence.

---

## 22. PaymentAllocation, Refund, Reversal y Dispute

### PaymentAllocation

Asignación positiva de eligible PaymentTransaction value hacia PaymentRequirement.

```text
sum(net eligible allocations from transaction)
<= current eligible transaction value
```

Currencies deben coincidir salvo futuro modelo FX explícito.

### PaymentAllocationAdjustment

Atribuye pérdida/corrección de valor a allocation existente.

```text
sum(adjustments sourced from reversal) <= reversal amount
sum(invalidating adjustments against allocation) <= eligible historical contribution
```

Si attribution es ambigua → ReconciliationCase.

### Refund

Operation iniciada para devolver valor.

```text
requested
processing
succeeded
failed
cancelled
```

Refund no reescribe original transaction ni business obligation disposition automáticamente.

### FinancialReversal / Return

Financial fact separado que reduce/invalida value previamente reconocido.

### PaymentDispute

Lifecycle del dispute/chargeback.

Original financial facts y Fulfillment permanecen históricos.

---

## 23. Reconciliation

`ReconciliationCase` existe cuando matching, attribution, treatment o financial finality no puede resolverse con certeza.

```text
missing_reference
ambiguous_match
partial_reversal_attribution
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
finality_mismatch
```

No adivinar.

---

## 24. Idempotency y operation identity

### Transport idempotency

Retry protection scoped a organization + operation + caller/context + idempotency key + canonical payload hash.

### Durable operation identity

Server-generated operation token puede sobrevivir controlled handoff entre channels/principals.

Replay devuelve el mismo logical outcome/reference, pero current read authorization se reevalúa. Una idempotency key nunca es bearer authorization.

---

## 25. AI agents

```text
LLM interprets/proposes
→ typed semantic command
→ tenant resolution
→ authorization/Representation check
→ current-state revalidation
→ policy evaluation
→ authoritative transaction
```

No generic CRUD/status setters.

Agent rules:

- hallucinated IDs resolve tenant-first;
- stale availability nunca confirma capacity;
- repeated tool execution depende de idempotency;
- correlation no concede authority;
- screenshot/payment claims crean como máximo PaymentEvidence;
- semantic tools son preferidos a entity CRUD;
- long cross-channel workflows continúan sobre el mismo Request, no sobre conversation memory.

---

## 26. Cardinalidades canónicas V2.5

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party                     via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
External interaction identity N ── M Request

Request N ── M Reservation               via Selection/ReservationItem lineage
OfferingSelection N ── M Reservation     via ReservationItem

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CapacityHold 1 ── 1..N required claim intents/claims internally
CommitmentRequirement 1 ── 1..N ResourceAllocation

Reservation N ── M ServiceSession
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

`Reservation ↔ Participant` no requiere relación global independiente si requested/admission scope ya es inequívoco.

---

## 27. Canonical vocabulary V2.5

### Core

```text
Organization
Principal
Party
Representation
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
AdmissionScope (semantic concept)
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

### Persistence-internal

```text
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision (or equivalent)
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
Generic Amendment aggregate
Generic Policy DSL
Generic Workflow DSL
Route optimizer
Overlapping reservable pools
Advanced OR/k-of-n requirements
Generic ServiceSubject
Generic relationship graph
```

---

## 28. Foundation invariants V2.5

1. no cross-tenant authoritative references;
2. no generic polymorphic FK for critical domain relationships;
3. Principal ≠ Party and participant role ≠ authority;
4. authority-dependent mutation preserves exact Representation/policy provenance;
5. ExternalCorrelation never grants authority;
6. Request terminal states are monotonic;
7. Request completion serializes with changes to required outcome scope;
8. RequestTarget is separate from generated lineage;
9. OfferingSelection quantity/unit/FulfillmentModel are reconstructible historically;
10. Fulfillment is an append-oriented application of outcome evidence to exactly one Request scope;
11. corrections never erase historical Fulfillment;
12. shared CommitmentRequirement consumes capacity once;
13. a compound required CapacityHold is atomic: all mandatory claims or none;
14. Hold and Allocation claims share one logical conflict space;
15. live claims never exceed valid capacity;
16. pool/direct-member claims serialize and never double-count;
17. non-fungible pools bind concrete Resource before commitment;
18. schedule/location/membership mutations serialize against stable authority revision;
19. expired Hold cannot confirm and expiry does not depend on cleanup timing;
20. Reservation confirmation cannot leave mandatory requirements under-covered;
21. terminal Reservation has zero active consuming claims;
22. planned and actual execution timestamps remain distinct;
23. queue absolute position is not persisted as unquestioned business truth;
24. Destination/material field-service changes invalidate stale feasibility decisions;
25. all material post-commitment changes preserve Amendment Contract provenance;
26. PaymentEvidence and PaymentAttempt success contribute zero allocatable value by themselves;
27. PaymentTransaction records observation source, identity, timing, financial finality and eligible value semantics;
28. only eligible transaction value may satisfy PaymentRequirements;
29. original financial facts survive refund/reversal/dispute;
30. allocation/adjustment/reversal/refund budgets cannot over-consume value;
31. ambiguous financial attribution/finality creates reconciliation rather than guesswork;
32. manual financial verification requires explicit privileged authority and provenance;
33. business obligation disposition is independent from money movement;
34. idempotency prevents duplicate mutation but never grants read/write authority;
35. no network call participates inside authoritative DB transaction;
36. capacity/financial/tenant invariants cannot depend only on application pre-checks;
37. all multi-authority mutations use deterministic lock ordering.

---

## 29. Schema readiness gate

Schema exploration is allowed. Schema freeze requires `docs/02-pre-sql-domain-contract.md` to map every critical invariant to one of:

```text
DB constraint
stable lock authority + transaction protocol
optimistic version protocol
explicitly bounded application policy
```

Additionally, command proofs must demonstrate compound capacity atomicity, Fulfillment scope validity, financial eligibility/finality, amendment lineage and multi-tenant authority under races.
