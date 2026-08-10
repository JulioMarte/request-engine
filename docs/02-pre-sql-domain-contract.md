# Request Engine V2.1 — contrato de dominio pre-SQL

> **Estado:** normativo para el diseño PostgreSQL.
>
> Este documento no diseña tablas. Define las **cardinalidades, state semantics, concurrency guarantees e invariantes** que el futuro schema debe poder garantizar.
>
> Documentos relacionados:
>
> - `docs/00-product-definition.md` — producto/vocabulario/boundaries.
> - `docs/01-architecture-v2.md` — decisiones técnicas.
>
> El SQL no debe comenzar traduciendo nouns a tablas. Debe comenzar asignando cada invariante de este documento a una garantía concreta de DB/transaction/application policy.

---

## 1. Criterio de readiness

El modelo está listo para SQL porque se han cerrado explícitamente los blockers encontrados en el stress test:

1. pricing provenance;
2. ResourceRequirement → ResourceAllocation traceability;
3. Hold/Reservation capacity conflict equivalence;
4. partial fulfillment/mixed attendance;
5. refund/reversal/chargeback semantics;
6. amendment/history semantics;
7. Request/Reservation/payment lifecycle independence;
8. agent authorization vs scope;
9. DST/local-time ambiguity;
10. concurrency ownership.

El diseño físico sigue teniendo libertad, pero no puede cambiar estas semánticas accidentalmente.

---

## 2. Cardinalidades normativas

### Identity / request

```text
Organization 1 ── N Principals
Organization 1 ── N Contacts
Organization 1 ── N Offerings
Organization 1 ── N Requests

Request N ── M Contact
    via RequestParticipant

Request 1 ── 0..N OfferingSelection
Offering 1 ── 0..N OfferingSelection
```

`RequestParticipant` representa rol, no authentication authority.

Una OfferingSelection pertenece a un Request.

### Request / reservation

```text
Request N ── M Reservation
```

La relación se deriva mediante:

```text
Request
→ OfferingSelection
→ ReservationItem
→ Reservation
```

No imponer `Reservation.request_id NOT NULL` como ownership source of truth.

Puede existir provenance `created_from_request_id` nullable, pero no define cardinalidad.

### Reservation

```text
Reservation 1 ── 1..N ReservationItem
ReservationItem N ── 0..1 OfferingSelection
Reservation 1 ── 0..N ServiceSession
Reservation 1 ── 0..N Dispatch
Reservation 1 ── 0..N ResourceAllocation
```

ReservationItem sin OfferingSelection sólo se permite para creación administrativa/directa y debe conservar Offering/snapshot suficiente.

### Capacity requirements

```text
ReservationItem 1 ── 0..N EffectiveResourceRequirement
EffectiveResourceRequirement 1 ── 0..N ResourceAllocation
Resource 1 ── 0..N ResourceAllocation
```

La implementación puede materializar requirement snapshot dentro de otra estructura si preserva identidad/trazabilidad equivalente.

### Fulfillment

Preferencia normativa para mantener records pequeños:

```text
Request 1 ── 0..N Fulfillment
OfferingSelection 1 ── 0..N Fulfillment
ServiceSession 1 ── 0..N Fulfillment
```

Un Fulfillment pertenece a un Request concreto.

Una ServiceSession que satisface dos Requests crea dos Fulfillments.

### Payments

```text
PriceDetermination 1 ── 0..N PaymentRequirement
PaymentRequirement 1 ── 0..N PaymentAttempt
PaymentAttempt 1 ── 0..N PaymentEvidence

PaymentTransaction N ── M PaymentRequirement
    via PaymentAllocation

PaymentTransaction 1 ── 0..N Refund scope/reference
PaymentTransaction 1 ── 0..N FinancialReversal/Return
PaymentTransaction 1 ── 0..N PaymentDispute
```

Una ReconciliationCase puede involucrar múltiples financial facts/candidates si el caso lo exige; no imponer 1:1 prematuramente.

---

## 3. Request lifecycle contract

Request representa work, no Reservation/payment.

Estados exactos pueden refinarse durante SQL design, pero semánticamente debe distinguir:

```text
active
waiting
completed
cancelled
failed_terminal
```

`waiting` puede ser projection/substate del workflow; no es obligatorio como columna.

### Request completion invariant

Un Request sólo puede considerarse completed cuando el workflow versionado determina que sus outcome obligations fueron satisfechas/terminalmente resueltas.

No basta:

```text
Reservation.closed
PaymentRequirement.satisfied
ServiceSession.completed
```

por separado.

---

## 4. Reservation commitment state contract

Estados canónicos:

```text
confirmed
cancelled
expired
closed
```

Allowed semantic transitions:

```text
confirmed → cancelled
confirmed → expired       only when explicit policy supports expiry
confirmed → closed
```

No reopen in-place después de terminal state. Una nueva commitment genera nueva Reservation o explicit reschedule/replacement semantics.

### Meaning

`confirmed`: capacity commitment activo/futuro o ejecución asociada todavía abierta.

`cancelled`: commitment terminado por cancel operation.

`expired`: commitment terminó por explicit expiry policy sin execution/admission required.

`closed`: ya no queda capacity commitment pendiente; outcomes viven en Fulfillment/admission facts.

### Forbidden global states

No persistir como commitment state:

```text
no_show
completed
checked_in
waiting
in_service
en_route
```

---

## 5. Admission/no-show contract

No-show se registra sobre scope operacional suficientemente específico.

Debe poder representar:

```text
Reservation with recipients A,B,C
A attended
B no_show
C attended
```

sin contradicción.

NoShowPolicy recibe scope + timing + initiator/system observation y produce consequences.

Una ausencia no se deduce permanentemente sólo porque `now > start`; debe existir una transición/job/observation autoritativa cuando la policy requiera marcarla.

---

## 6. Fulfillment contract

Fulfillment es append-oriented business outcome evidence.

Debe conservar:

```text
request
optional offering_selection
optional recipient/admission scope
fulfilled quantity/scope
outcome/status
service_session/evidence reference
recorded_at
principal/source
```

### Partial fulfillment

Debe poder existir:

```text
requested quantity = 10
Fulfillment #1 = 6
Fulfillment #2 = 2
remaining = 2
```

sin declarar toda la Selection fulfilled.

El cálculo de remaining scope debe ser determinista.

No borrar Fulfillment por refund/chargeback posterior.

---

## 7. Pricing contract

Toda obligación monetaria creada por Request Engine debe tener provenance suficiente.

`PriceDetermination` debe responder:

```text
what scope was priced?
which inputs/quantity?
which policy/source/version?
which adjustments?
what final Money?
who overrode it, if anyone?
when?
```

### Price immutability

Una determination utilizada históricamente no se modifica para cambiar el pasado.

Correcciones generan nueva revision/determination y consecuencias explícitas.

### External pricing

Permitido:

```text
source = external_system
external_reference
validated final Money
relevant snapshot/hash/version
```

No se exige replicar el pricing engine externo.

---

## 8. PaymentRequirement contract

PaymentRequirement representa obligation, no invoice.

Debe tener:

```text
Money required
purpose
payer when known
pricing provenance
policy snapshot/reference
due_at optional
explicit business disposition: active/waived/cancelled
```

Satisfaction financiera es derivada/materializada desde PaymentAllocations elegibles.

### Net satisfaction

Conceptualmente:

```text
eligible allocated value
- value invalidated by reversal/return/refund semantics as applicable
= net satisfied value
```

La implementación exacta puede usar counter-facts/adjustment allocations, pero nunca un boolean manual sin financial support.

---

## 9. PaymentTransaction / financial facts contract

Un original settlement sigue siendo un hecho histórico aunque luego sea devuelto/revertido.

Forbidden semantic mutation:

```text
settled transaction
UPDATE status = reversed
therefore pretend settlement never existed
```

El modelo debe conservar original fact + related reversing/refund/dispute facts.

Provider lifecycle observations pueden actualizar metadata/status de una operación mientras todavía representa el mismo hecho; una vez que un nuevo movimiento económico existe, debe representarse separadamente.

---

## 10. Refund contract

Refund es una operation intent/lifecycle para devolver financial value.

```text
requested → processing → succeeded
                       ↘ failed
requested → cancelled
```

Debe conocer:

```text
amount/currency
reason
original financial scope
provider reference
principal/policy provenance
```

### Refund invariant

Concurrent successful/pending refundable claims no pueden superar el refundable amount permitido por policy/financial facts.

Void de uncaptured authorization no es Refund.

---

## 11. Reversal / return contract

Representa un nuevo financial fact que reduce value previamente elegible.

Debe referenciar original transaction cuando se conozca.

Examples:

```text
bank return
provider reversal
ACH return
cash correction only if independently authoritative and audited
```

No borrar PaymentAllocation histórica; eligibility/net projections reflejan el reversal.

---

## 12. PaymentDispute contract

Lifecycle mínimo:

```text
opened
under_review
won
lost
closed
```

Dispute no es Refund.

`lost` puede producir/estar asociado a reversing financial fact.

Dispute posterior a Fulfillment no cambia operational history.

---

## 13. Capacity contract

### Common claim space

CapacityHold y confirmed ResourceAllocation compiten por la misma capacidad.

No puede existir una ventana donde:

```text
Hold removed
Reservation not yet committed
```

permita que otro actor robe capacity durante confirmation.

Transformation debe ser atomic bajo transaction/lock.

### Exclusive invariant

Para Resource exclusive:

> No existen dos live capacity claims incompatibles sobre intervals que se solapan.

### Units invariant

Para Resource/pool units:

> Para cualquier capacity authority/interval relevante, suma(live hold claims + active confirmed claims) <= effective capacity.

### Capacity changes

Reducir capacity/schedule después de confirmation no invalida historia. Identifica Reservations afectadas y abre/requires disruption handling.

---

## 14. CapacityHold state contract

Estados:

```text
active
confirmed
released
expired
```

Allowed:

```text
active → confirmed
active → released
active → expired
```

Terminal states no vuelven a active.

Confirmation y expiry deben serializarse.

Payment settled después de `expired` no cambia Hold state.

---

## 15. ResourceAllocation contract

Allocation debe identificar:

```text
reservation
effective requirement
resource/pool
quantity
interval
status
lineage/replacement when applicable
```

Estados:

```text
active
released
replaced
```

### Requirement satisfaction

Una confirmed Reservation que no tiene allocations suficientes para un required requirement debe ser detectable inmediatamente como invalid/at-risk y originar disruption/recovery; no puede permanecer silenciosamente `valid`.

### Replacement

```text
allocation A active
→ A replaced
→ allocation B active
```

No UPDATE A.resource_id = B como si A nunca existiera.

---

## 16. Pool binding contract

Pool claim y concrete member binding son un solo commitment económico de capacity, no dos.

El SQL design debe escoger y documentar una estrategia que pruebe:

```text
pool total not oversold
member not double-booked
binding not double-counted
lineage preserved
```

No introducir una tabla Assignment que permita contradicción con ResourceAllocation.

---

## 17. Schedule/time contract

Persisted authoritative instants: UTC.

Interpretation schedules: IANA timezone.

Local input stores/resolves enough information to disambiguate when required.

### Ambiguous local time

Debe exigir offset/fold o selección explícita.

### Nonexistent local time

Debe rechazarse o resolverse mediante policy explícita comunicada al caller.

### Schedule mutation

ScheduleException posterior no muta Reservation existente.

---

## 18. Destination amendment contract

Destination confirmado es historical snapshot.

ChangeDestination:

```text
lock/revision check
validate new Destination
validate ServiceArea
re-evaluate pricing if relevant
re-evaluate capacity/dispatch if relevant
preserve old snapshot
commit new version/state
emit event
```

Si Dispatch está en_route, la operación puede requerir explicit acceptance/rejection/human override.

---

## 19. Amendment contract

Material fields no se cambian mediante generic CRUD después de commitment.

Material:

```text
offering
quantity
recipient scope
planned interval
Destination
price
ResourceRequirements
policy version
```

Cada command define compensation/replacement consequences.

No aggregate `Amendment` universal en V2.1.

---

## 20. Idempotency contract

Para operation scope `S`, key `K`, payload canonical hash `H`:

```text
(S,K) unseen → execute and persist H/result
(S,K) seen with H → replay same logical result
(S,K) seen with different H → conflict
```

DB debe tener uniqueness para `(scope,key)` equivalente.

Keys no son authorization tokens.

---

## 21. Provider callback contract

Provider event identity/fingerprint debe deduplicarse.

Duplicate event:

```text
→ same logical financial/domain effect once
```

Out-of-order event:

```text
→ may append new fact
→ may update same provider operation if semantically valid
→ must not regress authoritative domain state blindly
```

Signatures/anti-replay en adapter boundary.

---

## 22. Multi-tenancy contract

Para cada tenant-owned relation:

```text
child.organization_id == parent.organization_id
```

Debe protegerse en DB para relaciones críticas, no sólo mediante ORM filters.

No query pública debe resolver entity por public_id global y luego confiar en authorization tardía si puede resolver tenant+public_id conjuntamente.

Provider external identifiers se scoped por provider connection/organization cuando corresponda.

---

## 23. Agent authorization contract

Una mutación necesita todas:

```text
authenticated Principal
organization match
required scope
subject/on-behalf-of authority where applicable
resource/entity authorization
valid current state
policy approval
idempotency
```

LLM text nunca constituye authority.

A tool retry no debe duplicar operation.

A hallucinated ID debe producir not-found/not-authorized dentro del tenant boundary, nunca leakage descriptivo de otro tenant.

---

## 24. Derived state contract

Derived/projection examples:

```text
Reservation operational_health
PaymentRequirement satisfaction label
PaymentRequirement overdue
Request progress
availability
current queue estimate
```

Si se materializan:

- deben ser reconstruibles;
- no son arbitrary write endpoints;
- authoritative facts ganan en caso de disagreement.

---

## 25. Audit contract

Toda privileged mutation registra:

```text
organization
principal
action
entity/reference
before/after revision or relevant facts
reason
policy/version
override flag when applicable
on_behalf_of context when relevant
correlation/causation
source
occurred_at
```

Payments manual verification/refund/reconciliation requieren audit obligatorio.

---

## 26. Outbox contract

Domain mutation + outbox append = misma DB transaction.

Worker delivery puede ser at-least-once.

Consumer debe ser idempotente.

Two workers no deben ejecutar simultáneamente el mismo claim lógico sin claiming protocol.

---

## 27. Required concurrency proofs

El SQL design document debe explicar exactamente qué ocurre en estas carreras.

### C1 — Last unit

Two concurrent holds for final capacity unit.

Expected: máximo uno commits a valid claim.

### C2 — Hold confirmation vs expiry

Expected: sólo una terminal transition gana.

### C3 — Payment vs Hold expiry

Expected: payment remains financial fact; expired capacity not resurrected.

### C4 — Cancellation vs CheckIn

Expected: serialized policy-valid result; no lost update.

### C5 — Resource unavailable vs Reservation confirmation

Expected: either confirmation fails/recomputes or confirmation commits first and subsequent change creates disruption.

### C6 — Two concrete assignments/bindings

Expected: exclusive Resource cannot be double-booked.

### C7 — Duplicate webhook

Expected: one logical effect.

### C8 — Refund vs reversal

Expected: cannot create economic return greater than eligible amount.

### C9 — Two PaymentAllocations

Expected: transaction cannot be overspent.

### C10 — Two reconciliations

Expected: incompatible resolutions cannot both commit.

### C11 — Two outbox workers

Expected: safe claim; duplicate delivery still harmless.

### C12 — Same idempotency key, different payload

Expected: conflict, never silent replay.

---

## 28. DB-vs-application ownership matrix

### Must have DB-level participation

```text
cross-tenant referential integrity
unique public IDs within tenant
idempotency uniqueness
provider event dedupe
exclusive capacity overlap prevention where representable
unit capacity serialization authority
PaymentAllocation overspend prevention protocol
refundability serialization
revision/lost-update detection
foreign keys/history integrity
Money/basic quantity checks
```

### Application/domain policy

```text
which Offering is compatible
which ResourceCapability satisfies requirement
cancellation consequence
no-show consequence
price policy selection
workflow selection
whether destination change is allowed
whether refund should be requested
agent on-behalf-of business rule
```

### Both

```text
Reservation confirmation
CapacityHold confirmation
Resource replacement
PaymentAllocation
Refund
Reconciliation
amendments
```

Application decides; DB prevents invalid concurrent result.

---

## 29. Impossible-state checklist

The schema/application contract must make these impossible or explicitly transitional:

```text
PaymentRequirement satisfied with zero net eligible allocations
Refund succeeded above refundable amount
Allocation references requirement from another Reservation/tenant
Reservation considered operationally valid with required capacity missing and no disruption
expired Hold later confirmed
exclusive Resource double-booked
unit Resource oversold
PaymentEvidence directly creates satisfied Requirement
cross-tenant participant
cross-tenant payment allocation
Fulfillment references Selection from unrelated Request
Reservation global no_show while some recipients fulfilled
silent overwrite of replaced allocation
silent overwrite of committed Destination
same provider event creates two transactions
same idempotency key executes two different payloads
```

Transitional distributed states such as `Reservation cancelled` while external dispatch cancellation is still pending must be represented as pending compensation/projection, not mistaken for impossible history.

---

## 30. Required scenario acceptance tests

Before calling schema V2.1 stable, automated tests must cover at least:

1. single barber appointment;
2. haircut + beard requiring different resources;
3. dental staged X-ray + dentist;
4. child + guardian + payer;
5. technician pool → concrete technician;
6. field-service diagnostic leading to additional work;
7. agency quote without Reservation;
8. group class unit capacity;
9. group pricing with participant categories through external/internal price determination;
10. product + installation with external inventory reference;
11. resource moving between locations with buffers/policy;
12. business requester + multiple employee recipients;
13. multiple recipients;
14. shared Resource across Offerings;
15. employee sick after confirmation;
16. equipment failure;
17. overbooking race;
18. concurrent Holds;
19. appointment + queue coexistence;
20. waitlist promotion through Hold;
21. late customer;
22. mixed participant no-show;
23. business cancellation;
24. customer cancellation;
25. destination change after dispatch;
26. vehicle failure/redispatch;
27. delayed ServiceSession affecting later commitments;
28. partial fulfillment;
29. one ServiceSession satisfying two Requests;
30. bank transfer missing reference;
31. fake PaymentEvidence;
32. late payment after Hold expiry;
33. partial payment;
34. overpayment;
35. several transactions → one Requirement;
36. one transaction → several Requirements;
37. partial refund after cancellation;
38. chargeback after Fulfillment;
39. duplicate webhook;
40. out-of-order webhook;
41. manual verification with audit;
42. cross-tenant identifier attack;
43. unauthorized agent mutation;
44. holiday exception after Reservations exist;
45. DST ambiguous/nonexistent local time;
46. recurring plan represented as individual Reservations;
47. Selection amendment after payment/confirmation;
48. Requirement price reduction after partial payment;
49. card authorization larger than final capture represented without conflating authorization and settlement;
50. concurrent refund/reversal.

---

## 31. Deferred concepts

These are explicitly NOT required for SQL V2.1:

```text
ReservationSeries
Agreement
Subscription
ReservationSegment
Delivery
Order
Invoice
GeneralLedger
InventoryLedger
WorkforceOptimizer
RouteOptimizer
GenericParty
GenericRelationshipGraph
GenericAmendment
BPMN
RulesDSL
PricingDSL
```

If SQL design requires one merely to make the current model work, revisit the model first.

---

## 32. SQL design deliverable required next

The next artifact should be a PostgreSQL schema/design that maps every critical invariant to one of:

```text
FOREIGN KEY / composite tenant FK
UNIQUE constraint/index
CHECK constraint
EXCLUDE constraint
transaction + row lock protocol
optimistic revision check
append-only/history rule
application policy with DB-backed preconditions
```

For every invariant, document:

```text
Invariant
Tables involved
DB mechanism
Transaction boundary
Concurrency behavior
Failure returned to application
Test proving it
```

Only after that mapping should Alembic/SQLAlchemy models be treated as implementation-ready.
