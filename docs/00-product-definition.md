# Request Engine — definición de producto y dominio canónico

> **Estado:** foundation V2.6. El schema PostgreSQL no se congela hasta satisfacer `docs/02-pre-sql-domain-contract.md`.
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

Conserva cinco verdades durables:

1. **Intent truth** — qué fue solicitado y para quién.
2. **Authority truth** — quién podía producir cada mutación material y bajo qué authority/policy version.
3. **Commitment truth** — qué capacidad/commitments fueron retenidos o confirmados y para qué requirement.
4. **Financial truth** — qué se debía, qué hechos/observaciones financieras existen, qué valor era elegible y cómo fue aplicado.
5. **Outcome truth** — qué parte del scope solicitado fue cumplida, qué evidencia lo sostiene y qué quedó pendiente.

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
local commitment ≠ external commitment dependency
PaymentAttempt ≠ PaymentTransaction
PaymentEvidence ≠ PaymentTransaction
PaymentTransaction ≠ FinancialObservation
FinancialReversal ≠ ObservationCorrection
PaymentTransaction ≠ PaymentRequirement
Refund ≠ FinancialReversal
FinancialReversal ≠ business obligation cancellation
PriceDetermination ≠ PaymentRequirement amount derivation
Operational health ≠ Reservation lifecycle
Request lifecycle ≠ completion validity
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

Authority materializada que permite actuar `on_behalf_of` de una Party o subject scope.

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

`Request` es la unidad durable de intención procesable.

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

Terminalidad es monotónica. Chargeback, disruption, corrected outcome o reversal posteriores no reabren automáticamente el mismo Request; generan recovery work, case o nuevo Request cuando corresponda.

Completion depende de outcome criteria tipados/versionados evaluados contra facts autoritativos.

### Completion validity

`Request.status=completed` significa que una decisión autoritativa de completion ocurrió con facts/policy válidos en ese momento. No significa que evidencia futura no pueda invalidar la conclusión.

`completion_validity` es derived/projection state:

```text
valid
under_review
invalidated
```

Una correction posterior que deje unmet un required outcome NO reabre el Request. Cambia completion validity y dispara recovery/review según policy.

### RequestType

Ejemplos:

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
cancel_reservation → Reservation
reschedule_reservation → Reservation
```

No usar authoritative generic `(target_type, target_id)` sin FK real.

---

## 6. Cross-channel continuation

`ExternalCorrelation` relaciona Requests con website sessions, WhatsApp threads, voice calls, tickets u otras interaction identities.

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

```text
service
product
package
custom
```

Si fulfillment depende de inventario externo, confirmation requiere un external commitment/reference verificable o una policy explícita que acepte riesgo. Stock observado no equivale a inventory committed.

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

### ReservationItem cardinality

Un `ReservationItem` pertenece a exactamente una `OfferingSelection`. Una OfferingSelection puede producir múltiples ReservationItems y aparecer en múltiples Reservations.

```text
OfferingSelection 1 ── N ReservationItem
ReservationItem N ── 1 OfferingSelection
```

Packages deben modelarse como Offering/package semantics, no mezclando varias OfferingSelections dentro de un ReservationItem.

### FulfillmentModel

Cada Offering/version declara cómo se demuestra outcome:

```text
binary
quantity
components
external_authoritative
```

`quantity` sólo permite arithmetic remaining scope cuando la unidad es aditiva.

Para quantity se declara una `excess_policy`:

```text
reject_excess
allow_excess
```

`components` usa component keys versionadas; no porcentajes inventados.

No construir fulfillment DSL universal.

---

## 8. OutcomeScope y Fulfillment — V2.6

### OutcomeScope

Concepto técnico/domain-internal que identifica el scope solicitado contra el que compiten Fulfillments y corrections.

No necesita ser exposed como aggregate/API noun, pero debe existir una stable serialization identity para proteger:

```text
RecordFulfillment
CorrectFulfillment
requested-scope amendments
CompleteRequest
completion revalidation
```

Puede corresponder a una OfferingSelection + recipient/component scope tipado.

### Fulfillment

`ServiceSession` representa ejecución real.

`Fulfillment` representa la aplicación append-oriented de evidencia de outcome a un OutcomeScope perteneciente a exactamente un Request.

No representa la visita, sesión, trabajo físico ni pago.

```text
ServiceSession S
├─ Fulfillment F1 → Request A / OutcomeScope A
└─ Fulfillment F2 → Request B / OutcomeScope B
```

Cada Fulfillment preserva:

```text
Request
OutcomeScope
OfferingSelection when applicable
recipient/subject scope when applicable
ServiceSession or external source when applicable
FulfillmentModel/version
outcome quantity/components/result
evidence/provenance
observed_at / occurred_at when distinct
```

Correcciones no borran historia. Añaden correction/supersession lineage.

Para quantity, concurrent Fulfillments serializan sobre OutcomeScope. `reject_excess` impide que net valid contribution exceda requested quantity; `allow_excess` permite exceso explícito sin convertir remaining en arithmetic negativa autoritativa.

Refund, reversal o dispute nunca borran Fulfillment.

---

## 9. Workflow

Workflow es tipado, versionado y testeable. Puede pedir input, validar authority, determinar price, crear requirements/holds, esperar trabajo externo, confirmar Reservation, coordinar admission/dispatch, registrar Fulfillment y completar/fallar Request.

Outcome criteria materiales permanecen identificables y versionados.

No construir generic workflow DSL/BPMN/state-machine framework.

---

## 10. Pricing y PaymentRequirement

### PriceDetermination

Explica valor comercial de scope tipado:

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

Obligación monetaria concreta.

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

`open`, `partial`, `satisfied`, `overdue` son derivados/materializados.

No manual `paid=true`.

### Immutability after financial use

Una vez que un PaymentRequirement está activo y ha recibido allocation, su `required Money` histórico no se reescribe por repricing.

Repricing crea replacement/new requirement consequences con explicit supersession/reallocation/reconciliation policy. No se simula que la obligación anterior nunca existió.

---

## 11. Resources, requirements y capacity

### Resource

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

`CapacityPool` es capacity authority reservable para late binding; no es Resource ni ResourceGroup.

V1 sólo permite member-derived pools con contributors fungibles para el requirement concreto.

Reglas:

1. membership explícita/versionada;
2. contributors no alimentan reservable pools superpuestos para la misma conflict space;
3. pool capacity deriva de eligible members y live claims;
4. pool claim + concrete realization son un solo consumption;
5. contributor directo y pool claim compiten bajo el mismo serialization protocol;
6. unresolved late binding sólo cuando fungibility es demostrable;
7. si no, bind concrete Resource durante Hold/confirmation;
8. pérdida posterior de capacity produce recovery, no history rewrite.

---

## 13. CapacityHold — local atomic commitment set

`CapacityHold` es el commitment set temporal autoritativo para capacity **localmente controlada por Request Engine**.

Un Hold puede cubrir 1..N requirement intents y producir 1..N internal CapacityClaims sobre 1..N CapacityAuthorities.

> **Local atomicity:** para un mandatory commitment group bajo autoridad PostgreSQL local, todos los claims obligatorios se adquieren en una única transaction o ninguno se adquiere.

```text
Dental cleaning
CapacityHold H
├─ dentist claim
├─ chair claim
├─ room claim
└─ equipment claim
```

Está prohibido exponer como `active` un Hold cuyo required local claim set quedó parcialmente adquirido.

Partial local hold sólo existe si workflow separó independent commitment groups antes de acquisition.

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

## 14. ExternalCommitmentReference — V2.6

Cuando un Offering depende de inventory, partner capacity u otra autoridad externa, Request Engine no promete distributed atomicity.

Conserva un typed `ExternalCommitmentReference` o concepto equivalente con:

```text
provider/connection
external commitment identity
scope covered
status
verified_at
valid_until? / expires_at?
source policy/version
provenance
compensation/release capability when known
```

Una Reservation puede requerir local commitments + external commitment dependencies.

Semántica:

```text
external lease/commit first when required
→ obtain verifiable reference
→ local DB transaction revalidates snapshot validity + acquires local claims
→ commit Reservation
→ if local commit fails after external lease, compensate/release asynchronously/idempotently
```

No se afirma all-or-none entre PostgreSQL y un sistema externo.

---

## 15. CapacityAuthority, CapacityClaim y PlanningRevision

### CapacityAuthority

Stable lock/revision target de Resource o CapacityPool reservable.

### CapacityClaim

Common persistence conflict-space para Hold claims y confirmed Allocation claims.

### PlanningRevision

Monotonic revision asociada a una capacity authority/planning context que cambia cuando una mutación relevante puede invalidar external field-service feasibility.

Incluye, según dominio:

```text
new/released/replaced commitments
material interval changes
resource/vehicle binding changes
location/destination-sensitive planning changes
```

No es un business aggregate exposed a API.

Invariantes:

> live hold claims + active allocation claims nunca exceden la capacidad válida del mismo authority/interval.

> external feasibility snapshot sólo es usable si la PlanningRevision contra la que fue calculada sigue vigente al momento del commitment.

---

## 16. Reservation y ResourceAllocation

### Reservation

Compromiso confirmado de capacity/requested scope.

```text
confirmed
cancelled
closed
```

No usar global statuses `completed`, `no_show`, `checked_in`, `waiting`, `in_service` o `en_route`.

Terminal Reservation implica cero active capacity-consuming claims.

### ResourceAllocation

Domain truth que satisface CommitmentRequirement usando Resource/CapacityPool authority, quantity e interval.

```text
active
released
replaced
```

Hold confirmation transforma/realiza el complete required local claim set de forma atómica y valida required external commitments.

`Assignment` permanece fuera del core mientras Allocation/binding sea la única source of truth.

---

## 17. Reschedule — atomic replacement

Reschedule no libera primero el commitment antiguo.

Semántica V1:

```text
create replacement CapacityHold for new scope
then one local transaction:
  lock Reservation
  lock replacement Hold
  lock old/new CapacityAuthorities canonical order
  validate current state/policy/external dependencies
  confirm replacement commitments
  release/replace old allocations
  preserve lineage
  commit
```

Failure conserva el commitment original salvo policy explícita distinta.

---

## 18. Schedules, intervals, location y variable capacity

BusinessHours ≠ AvailabilitySchedule.

ScheduleException:

```text
closed
replace_hours
open_special
capacity_override
```

Todo cambio capaz de modificar reservability pertenece a stable capacity/schedule authority revision.

### Interval semantics

Capacity intervals V1 usan semántica half-open:

```text
[start_at, end_at)
start_at < end_at
```

No open-ended/infinite capacity commitments en V1.

Transition/setup/cleanup buffers que bloquean capacity forman parte del **conflict interval** aunque planned service interval se preserve separado.

### Variable capacity

Para `units`, la regla aplica en todo subintervalo relevante:

```text
sum(live claims at t) <= effective capacity at t
for every relevant t in claim interval
```

Capacity changes se evalúan por schedule change points; no basta verificar capacidad al inicio del intervalo.

### Resource ↔ Location

Un Resource puede operar en múltiples Locations a través del tiempo sin duplicarse.

Eligibility/reservability puede depender de:

```text
Resource
Location/service context
interval
capability
schedule revision
```

UTC para instantes. Local input usa IANA timezone y resolución explícita de ambiguous/nonexistent local times mediante offset/fold o rechazo.

---

## 19. Admission, queues y waitlists

### AdmissionScope

Concepto semántico que identifica subject/item/Reservation o walk-in Request scope al que aplican CheckIn, QueueEntry y no-show.

Serialization mapping V1:

```text
reservation-backed scope → ReservationItem
walk-in scope           → OfferingSelection/Request scope root
```

### CheckIn

Presence/readiness fact para AdmissionScope concreto.

### QueueEntry

Lifecycle operacional de espera. Puede existir sin Reservation.

```text
walk-in: Request/subject → QueueEntry → ServiceSession
appointment: Reservation → CheckIn → QueueEntry → ServiceSession
```

`position` absoluta no es business truth estable. El orden se deriva de ordering keys/facts/policy; estimaciones son projections.

Salvo policy explícita de requeue/multi-queue, existe como máximo un active QueueEntry por AdmissionScope + admission context.

### WaitlistEntry

```text
WaitlistEntry → match → CapacityHold → acceptance → Reservation
```

Waitlist nunca consume capacity directamente.

No-show pertenece a AdmissionScope/recipient/item, nunca a Reservation global.

---

## 20. ServiceSession

Execution real.

```text
Reservation N:M ServiceSession
```

Una ServiceSession puede contribuir a múltiples Requests/Fulfillments.

Planned timestamps nunca se sobrescriben con actual timestamps.

Cancellation/reschedule serializa contra active session linkage cuando la ejecución pueda haber comenzado.

---

## 21. Location, Destination, ServiceArea y Dispatch

`Location` es lugar operativo de la Organization.

`Destination` es lugar concreto donde una ejecución debe ocurrir.

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

Destination nunca se cambia silenciosamente después de dispatch planning. Un cambio preserva old destination + initiator + reason, invalida feasibility snapshot relevante y obliga a re-evaluar consequences.

V1 field service soporta:

```text
fixed/conservative transition buffers
OR
external feasibility snapshot bound to PlanningRevision
```

External feasibility snapshot preserva inputs, provider/source, verified_at, policy/version y PlanningRevision observada. Si revision cambió antes del commitment, snapshot es stale y no autoriza booking.

No route graph ni raw high-frequency GPS telemetry.

---

## 22. ReservationPolicy y Amendment Contract

Cancellation/reschedule/no-show decisions preservan:

```text
policy key/version
evaluated inputs
initiator/reason
recipient/item scope
override Principal/reason
```

No se crea `GenericAmendment` aggregate.

Todo post-commitment semantic change material preserva:

```text
operation identity
initiator Principal / represented Party
reason
policy/version
before authoritative refs/version
after authoritative refs/version
replaced/released/created lineage
evaluated inputs
override provenance when applicable
occurred_at
```

Aplica a:

```text
reschedule
partial cancellation
resource replacement
destination change
repricing
payer/recipient correction material
capacity recovery
external commitment replacement
```

History no se reescribe.

Operational health:

```text
valid
at_risk
blocked
```

es projection derivada.

No `ReservationDisruption` aggregate obligatorio hasta demostrar lifecycle propio.

---

## 23. Payment model V2.6

### PaymentAttempt

Intento de iniciar/capturar/cobrar mediante provider. Success no implica allocatable value.

### PaymentEvidence

Comprobante presentado. Nunca crea settlement ni eligible value por sí solo.

### PaymentTransaction

Representa una financial operation/value identity observada por Request Engine, no una única lectura mutable de su estado.

Conserva conceptualmente:

```text
direction
Money / financial identity
source/provider/account reference
external transaction identity when available
counterparty reference when known
```

### FinancialObservation

Fact append-oriented de conocimiento sobre PaymentTransaction:

```text
source/event identity
source status
normalized finality/status
observed amount/value interpretation
occurred/effective_at when known
observed_at
source policy/version
provenance
```

Current financial state y eligible value se derivan/materializan desde valid observations + corrections + reversal facts bajo policy.

### ObservationCorrection

Fact que corrige/invalida conocimiento anterior sin afirmar que ocurrió un nuevo movimiento financiero.

Ejemplos:

```text
duplicate bank feed entry
wrong manual verification
provider correction of prior status/amount
misidentified transaction
```

`ObservationCorrection` ≠ `FinancialReversal`.

### FinancialReversal / Return

Nuevo financial fact que representa value realmente retornado/revertido/invalidado por un evento financiero posterior.

### Financial finality

Normalización conceptual mínima:

```text
observed_pending
observed_available
observed_final
```

Sólo value declarado **eligible for allocation** por versioned financial-source policy satisface PaymentRequirements.

Provider webhook `payment_succeeded` no equivale automáticamente a `observed_final`.

### Manual financial verification

Puede crear FinancialObservation authoritative sólo mediante privileged command con:

```text
verifier Principal
authority/scope
source/account/cash context
observed evidence/reference
amount/currency
occurred_at/observed_at
reason
policy/version
optional second approval
```

Un screenshot analizado por IA sólo crea PaymentEvidence.

---

## 24. PaymentAllocation, adjustments, Refund y Dispute

### PaymentAllocation

Asignación positiva de current eligible PaymentTransaction value hacia PaymentRequirement.

```text
sum(net eligible allocations from transaction)
<= current eligible transaction value
```

Currencies deben coincidir salvo futuro FX explícito.

### PaymentAllocationAdjustment

Atribuye pérdida/corrección de value a allocation existente. Puede tener source lineage desde FinancialReversal u ObservationCorrection.

```text
sum(adjustments sourced from reversal) <= reversal amount
sum(invalidating adjustments against allocation) <= eligible historical contribution
```

Si attribution es ambigua → ReconciliationCase.

### Refund

Operation iniciada para devolver value.

```text
requested
processing
succeeded
failed
cancelled
```

Refund no reescribe original transaction ni business obligation disposition automáticamente.

### PaymentDispute

Lifecycle del dispute/chargeback.

Original financial facts, observations y Fulfillment permanecen históricos.

---

## 25. Reconciliation

`ReconciliationCase` existe cuando matching, attribution, treatment o financial interpretation no puede resolverse con certeza.

```text
missing_reference
ambiguous_match
partial_reversal_attribution
late_payment
unallocated_overpayment
provider_mismatch
manual_review_required
finality_mismatch
observation_correction_attribution
```

No adivinar.

---

## 26. Idempotency y operation identity

Transport idempotency protege retry de misma operation/caller.

Durable operation identity puede sobrevivir controlled handoff entre channels/principals.

Replay devuelve mismo logical outcome/reference, pero current read authorization se reevalúa. Idempotency key nunca es bearer authorization.

---

## 27. AI agents

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
- long cross-channel workflows continúan sobre Request, no conversation memory.

---

## 28. Canonical cardinalities V2.6

```text
Organization 1 ── N Principal
Organization 1 ── N Party
Organization 1 ── N Offering
Organization 1 ── N Request

Request N ── M Party via RequestParticipant
Request 1 ── 0..N typed RequestTarget links
Request 1 ── 0..N OfferingSelection
External interaction identity N ── M Request

OfferingSelection 1 ── 0..N OutcomeScope
OfferingSelection 1 ── 0..N ReservationItem
ReservationItem N ── 1 OfferingSelection
Request N ── M Reservation via ReservationItem lineage

Reservation 1 ── 1..N ReservationItem
ReservationItem N ── M CommitmentRequirement
CommitmentRequirement 1 ── 1..N ResourceAllocation
CapacityHold 1 ── 1..N local CapacityClaims
Reservation 1 ── 0..N ExternalCommitmentReference

Reservation N ── M ServiceSession
OutcomeScope 1 ── 0..N Fulfillment
Request 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment

PaymentTransaction 1 ── 1..N FinancialObservation
PaymentTransaction 1 ── 0..N ObservationCorrection
PaymentTransaction 1 ── 0..N FinancialReversal
PaymentTransaction N ── M PaymentRequirement via PaymentAllocation
PaymentAllocation 1 ── 0..N PaymentAllocationAdjustment
```

---

## 29. Canonical vocabulary V2.6

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
ExternalCommitmentReference
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
FinancialObservation
ObservationCorrection
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

### Persistence/domain-internal, not public business vocabulary

```text
OutcomeScope
AdmissionScope
CapacityAuthority
CapacityClaim
ScheduleAuthorityRevision
PlanningRevision
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

## 30. Foundation invariants V2.6

1. no cross-tenant authoritative references;
2. Principal ≠ Party and role ≠ authority;
3. ExternalCorrelation never grants authority;
4. Request terminality is monotonic;
5. completion validity can be invalidated without reopening Request;
6. OfferingSelection quantity/unit and outcome semantics are reconstructible;
7. ReservationItem belongs to exactly one OfferingSelection;
8. Fulfillment writes serialize over stable OutcomeScope where arithmetic/components conflict;
9. Fulfillment corrections preserve history and can invalidate completion validity;
10. local compound mandatory Hold is all-or-none;
11. local Holds and Allocations share capacity conflict space;
12. shared CommitmentRequirement consumes capacity once;
13. external commitments are explicit dependencies, not fake local atomic claims;
14. failed local commit after external lease requires compensation/recovery;
15. schedule/location/planning changes invalidate relevant authority revisions;
16. external field feasibility is bound to PlanningRevision;
17. `[start,end)` is canonical capacity interval semantics;
18. unit capacity holds across every relevant subinterval/change point;
19. reschedule uses atomic replacement and preserves original on replacement failure;
20. terminal Reservation has zero active local capacity-consuming claims;
21. Queue absolute position is projection, not durable truth;
22. admission races serialize on deterministic scope roots;
23. PaymentRequirement amount history is not destructively repriced after financial use;
24. PaymentEvidence and PaymentAttempt do not create eligible value;
25. PaymentTransaction identity is distinct from append FinancialObservations;
26. ObservationCorrection is distinct from FinancialReversal;
27. current eligible value derives from financial knowledge/facts under source policy;
28. allocations cannot exceed current eligible transaction value without explicit reconciliation condition;
29. allocation adjustments preserve reversal/correction lineage and budgets;
30. ambiguous financial attribution opens reconciliation;
31. manual verification requires privileged authority/provenance;
32. idempotency prevents duplicate mutation but not authorization checks;
33. no network call participates inside authoritative DB transaction;
34. all multi-authority mutations use deterministic lock ordering;
35. material post-commitment changes preserve Amendment Contract provenance.

---

## 31. Readiness gate

El dominio pasa a diseño relacional sólo cuando `docs/02-pre-sql-domain-contract.md` mapea cada critical invariant a:

```text
DB constraint
OR stable lock authority + transaction protocol
OR optimistic revision protocol
OR explicitly bounded application policy
```

No noun-to-table mapping automático. No schema freeze mientras una critical invariant dependa sólo de “the service will check first”.
