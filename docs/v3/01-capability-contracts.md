# Request Engine V3 — capability contracts

> **Estado:** normativo pre-SQL para las primeras superficies públicas/application-facing.
>
> Este documento define **qué promete Request Engine a bots, formularios, aplicaciones y automatizaciones**. No define tablas ni obliga a exponer cada command directamente por HTTP. `02-pre-sql-contract.md` define las garantías transaccionales que sostienen estas capacidades.

---

## 1. Contract philosophy

Request Engine expone capacidades de negocio, no CRUD sobre entidades internas.

Una capability pública debe responder claramente:

```text
¿Qué intenta lograr el caller?
¿Qué authority necesita?
¿Qué estado autoritativo puede cambiar?
¿Qué resultado estable recibe?
¿Cómo reintenta sin duplicar efectos?
¿Qué debe hacer si el estado cambió?
```

La misma capability puede exponerse por:

```text
REST/OpenAPI
MCP/tool schema
Python/TypeScript SDK
n8n node
internal application contract
```

sin cambiar su semántica.

### 1.1 Public identifiers

Los contratos públicos usan IDs opacos/estables. Ningún ID concede authority por posesión.

### 1.2 Mutation envelope

Todo write retryable desde red/agente debe aceptar una identidad idempotente equivalente a:

```text
Idempotency-Key
```

El scope mínimo de la key es:

```text
organization + authenticated Principal + capability + key
```

La misma key con payload semánticamente distinto es error, no un segundo comando.

### 1.3 Expected revision

Commands sobre aggregates existentes aceptan `expected_revision` cuando el caller necesita detectar stale intent explícitamente. El servidor todavía revalida invariantes aun cuando no se use optimistic revision.

### 1.4 Error contract

Errores machine-readable usan un envelope conceptual:

```json
{
  "code": "booking.capacity_conflict",
  "message": "The requested appointment is no longer available.",
  "retryable": false,
  "category": "conflict",
  "current_revision": 7,
  "suggested_action": "appointments.find_slots"
}
```

Campos internos/sensibles no se filtran al caller.

Categorías iniciales:

```text
validation
authentication
authorization
not_found
conflict
stale_state
expired
rate_limited
provider_unavailable
internal
```

---

## 2. Business information

### `business.get_info` — Query

Objetivo: responder información estructurada operacional del tenant sin consultar una CMS universal.

Input conceptual:

```text
organization context
optional location
optional locale
```

Output puede incluir:

```text
display name
public contact information
locations
opening/business hours
supported channels
basic operational policies explicitly marked public
```

No incluye secretos, internal notes, authority data ni arbitrary tenant metadata.

### `catalog.search_offerings` — Query

Input:

```text
text/category filters?
location?
active_at?
```

Output:

```text
offering public id
name/description summary
current bookable/requestable flags
location availability hints when safe
```

No promete availability de capacity concreta.

### `catalog.get_offering` — Query

Devuelve información estructurada/version-aware suficiente para que un agent explique y seleccione un Offering.

---

## 3. Appointment capabilities

El baseline define:

```text
1 Reservation = 1 OfferingVersion + 1 recipient/subject + 1 time interval
```

Un package que el negocio vende como una sola cita debe ser un Offering/package versionado. V3 baseline no modela una Reservation como un carrito universal de múltiples OfferingSelections.

### `appointments.find_slots` — Query

Objetivo: devolver opciones concretas que **parecen reservables ahora**.

Input:

```text
offering_id
recipient/subject when eligibility depends on it
location_id?
date/time window
timezone for presentation
optional resource/provider preference
```

Output:

```text
AppointmentOption[]
```

Cada option contiene al menos:

```text
option_id/token opaque
start_at
end_at
location
human-display timezone
optional provider/resource display information allowed by policy
expires_at? only if the option itself is server-materialized
```

`find_slots` no crea commitment y su respuesta no garantiza que el slot siga disponible al reservar.

`option_id/token` puede encapsular/firmar el concrete resource plan y revisions observadas, pero siempre es advisory. `appointments.book` revalida estado autoritativo.

### `appointments.hold` — Command, optional public capability

Se expone sólo si el canal/product flow necesita una ventana temporal antes de confirmar.

Input:

```text
AppointmentOption or equivalent desired scope
hold duration bounded by server policy
```

Output:

```text
hold_id
expires_at
resolved appointment scope
```

La duración solicitada por caller es una sugerencia; policy del servidor fija el máximo.

### `appointments.book` — Command

Dos modos aceptados:

```text
direct book from desired option/scope
confirm an existing active CapacityHold
```

Input mínimo:

```text
offering/version or option token
recipient Party
start/end or held scope
location when relevant
hold_id? when confirming a hold
```

Output:

```text
reservation_id
status = confirmed
start_at/end_at
location
revision
attendance_status
```

Guarantee: success significa que la Reservation y todos sus mandatory local capacity claims quedaron comprometidos atómicamente.

Failure por capacity conflict no deja Reservation parcial.

### `appointments.cancel` — Command

Input:

```text
reservation_id
reason code/text according to policy
expected_revision?
```

Output:

```text
reservation_id
status
revision
released_capacity = true/false
```

Success libera todos los active capacity claims de la Reservation en la misma local transaction.

Una cancelación puede producir después de commit una waitlist opportunity y comunicaciones, pero esas integraciones no extienden la transacción de cancelación.

### `appointments.reschedule` — Command

Input:

```text
reservation_id
new AppointmentOption or desired interval/location/resource preference
expected_revision?
```

Output:

```text
reservation_id
new start/end/location
new revision
```

Guarantee principal:

> Si el reschedule falla, la Reservation anterior permanece válida y conserva su capacidad.

Reschedule puede solaparse con su propia Reservation vieja sobre el mismo Resource. La validación excluye los claims que esa misma operación va a reemplazar, pero no excluye claims de terceros.

### `appointments.confirm_attendance` — Command

Input:

```text
reservation_id
response = accepted | declined
actor/subject authority
expected_revision?
```

Output:

```text
attendance_status
reservation_status
revision
```

`accepted` no cambia por sí mismo capacity commitment.

`declined` tampoco cancela automáticamente salvo que la versioned booking policy aplicable diga explícitamente que una declinación produce cancelación. Si la policy requiere esa consecuencia, cambio de attendance + cancel/release son una sola authoritative transaction.

### `appointments.get` — Query

Devuelve status/current interval/attendance y next actions permitidas para el caller. No expone internal claim rows.

---

## 4. ServiceQueue capabilities

`ServiceQueue` representa trabajo/personas esperando ser atendidos **ahora**.

Policy baseline:

```text
FIFO by admitted_at, then stable id as tie-breaker
```

### `queue.join` — Command

Input:

```text
queue_id
subject Party
optional reservation_id
optional Offering reference
```

Output:

```text
queue_entry_id
status = waiting
admitted_at
position estimate when available
```

Baseline impide más de una entry activa para el mismo subject en la misma queue.

### `queue.status` — Query

Output puede incluir:

```text
entry status
entries ahead / approximate position
called_at?
service_started_at?
```

La posición es projection/advisory, no un número autoritativo que se decrementa manualmente.

### `queue.call_next` — Command

Normalmente staff/system capability, no customer-facing.

Guarantee:

> Dos callers concurrentes sobre la misma ServiceQueue no pueden obtener el mismo siguiente QueueEntry.

Selecciona el earliest eligible `waiting` entry por FIFO y la cambia a `called` dentro de una transaction serializada por ServiceQueue.

### `queue.start_service` — Command

Transición inicial:

```text
called → serving
```

Puede permitir `waiting → serving` sólo si policy explícita lo autoriza; no inferir bypass silenciosamente.

### `queue.complete` — Command

```text
serving → completed
```

Completion de QueueEntry significa sólo que dejó la live queue. No demuestra un universal Fulfillment ni completa un Request implícitamente.

### `queue.leave` — Command

Permite salida/cancelación de una waiting/called entry según policy.

### `queue.mark_no_show` — Command

Estado operacional independiente de Reservation lifecycle.

---

## 5. Waitlist and released-slot recovery

Waitlist representa interés futuro y **no consume capacidad**.

### `waitlist.join` — Command

Input baseline:

```text
offering_id
subject Party
location_id?
earliest_start?
latest_start?
provider/resource preference?
```

Output:

```text
waitlist_entry_id
status = active
created_at
```

V3 baseline evita un DSL arbitrario de preferencias. Multiple disjoint time windows, ranking avanzado y scoring quedan fuera hasta necesidad real.

### `waitlist.leave` — Command

Cierra la entry activa. No toca capacity.

### `waitlist.status` — Query

Devuelve estado de la entry y active offer cuando exista. No promete posición exacta si filtros de elegibilidad hacen que el orden dependa del slot.

### Released-slot recovery process

Cuando una Reservation libera capacidad:

```text
booking commit
→ outbox event
→ queue creates/gets idempotent SlotOpportunity
→ selects earliest eligible WaitlistEntry
→ asks booking to acquire a short CapacityHold
→ creates SlotOffer
→ communications notifies candidate
```

V3 introduce dos conceptos diferentes:

```text
SlotOpportunity = coordination root for one released appointment opportunity
SlotOffer       = one expiring offer to one candidate
```

`SlotOpportunity` no es capacity truth. Booking siempre revalida Resource capacity.

### `waitlist.accept_offer` — Command

Input:

```text
slot_offer_id
expected offer revision?
```

Guarantee:

```text
active/unexpired SlotOffer
+ active/unexpired CapacityHold
→ Reservation confirmed
+ SlotOffer accepted
+ SlotOpportunity filled
```

como una sola local atomic operation.

Duplicate retry devuelve el mismo resultado por idempotency.

### `waitlist.decline_offer` — Command

Decline releasea el short Hold y deja Opportunity disponible para intentar el siguiente candidato.

### `waitlist.expire_offer` — internal ScheduledAction target

Expiry idempotente. Libera Hold y puede desencadenar offer al siguiente candidato después de commit.

### Baseline selection policy

Entre candidates elegibles:

```text
oldest active WaitlistEntry first
```

No scoring/auction/ML optimizer.

---

## 6. Durable business Requests

### Request definition

Un tenant puede habilitar tipos de demanda nuevos sin crear una tabla de dominio por formulario.

Conceptos:

```text
RequestDefinition
RequestDefinitionVersion
Request
```

`RequestDefinitionVersion` contiene un schema/version contract para input genérico. El payload validado de un Request referencia exactamente la versión usada.

Este JSON/document boundary está permitido porque representa **input extensible antes de que exista un native bounded context**.

### `requests.submit` — Command creating a Request

Input:

```text
request_definition key/id
payload
requester/recipient context
external correlation?
```

Output:

```text
request_id
request_type/key
status = open
revision
```

Ejemplos:

```text
request_quote
request_callback
request_service
website_contact
```

### `requests.get` — Query

Devuelve status, safe result summary y allowed next actions.

### `requests.record_result` — Command

Normalmente integration/human/native-worker capability, no unrestricted public caller.

Usado por un n8n workflow o integration principal para registrar resultado tipado contra el Request correcto.

Require:

```text
authenticated integration Principal
tenant binding
idempotency
expected/current Request state
result schema validation when configured
```

### `requests.complete` — Command

`open → completed` monotonic for the baseline.

### `requests.cancel` — Command

Cancela la demanda durable, no entidades generadas automáticamente. Si un Request ya produjo una Reservation, cancelar Request no cancela Reservation salvo una explicit domain policy/command composition.

### Generic n8n extension flow

```text
requests.submit
→ Request committed
→ outbox request.created.v1
→ n8n
→ external systems/human work
→ requests.record_result (idempotent)
→ requests.complete
```

No generic `PATCH /requests/{id}`.

---

## 7. Transactional communications

Communications are usually internal/admin/application capabilities rather than arbitrary end-user CRUD.

### `communications.create_task` — internal Command

Creates a durable communication intent with:

```text
purpose
recipient Party/contact target
template key/version or content policy ref
source business reference
channel policy
not_before/expiry when applicable
dedupe key
```

Typical purposes:

```text
appointment_created
appointment_reminder
attendance_confirmation_request
reservation_rescheduled
reservation_cancelled
queue_turn_approaching
slot_offer_available
request_completed
medication_reminder
```

### `communications.deliver_due` — worker operation

Not a public business API. Worker:

```text
claims due ScheduledAction
commits claim
loads CommunicationTask
creates provider attempt/idempotency identity
calls provider OUTSIDE authoritative DB transaction
records CommunicationDelivery result
completes/reschedules/dead-letters ScheduledAction using fencing token
```

External exactly-once delivery is not promised.

### `communications.record_provider_event` — adapter Command

Dedupe provider callback/event, normalize allowed delivery facts and update only the related communication delivery state.

Provider callback does not gain authority to mutate Reservation/Request/Queue directly.

If an inbound user action means `confirm attendance`, the adapter invokes `appointments.confirm_attendance` as a separate authorized semantic command.

---

## 8. Reminder plans

### `reminders.create_plan` — Command

Baseline recurring reminders support a deliberately small typed schedule family rather than arbitrary workflow/cron execution.

Initial schedule type:

```text
daily_times
```

Input conceptually:

```text
subject Party
purpose
timezone (IANA)
local times[]
start date
end date?
channel policy
template/content reference
acknowledgement mode = none | optional
```

The plan is versioned when schedule/content materially changes.

Medication reminder is an initial use case, but Request Engine only executes an authorized plan. It does not calculate dosage, change treatment or infer medical instructions.

### `reminders.update_plan` — Command

Material schedule change creates a new plan revision/version and cancels/regenerates pending future ScheduledActions idempotently.

Already completed communication history is never rewritten.

### `reminders.cancel_plan` — Command

Stops future materialization/execution and cancels pending actions that belong to the plan when still safely cancellable.

### `reminders.acknowledge` — Command

Optional acknowledgement fact such as “taken/acknowledged”. It records what the user reported; it does not prove clinical adherence.

---

## 9. Capability discovery

V3 should expose a machine-readable capability catalog per tenant/runtime Principal.

Conceptual Query:

### `capabilities.list`

Output:

```text
capability id
schema/version
whether enabled for tenant
whether caller is authorized / or authorization scope required
human-safe description
```

The catalog can drive LLM tool selection, OpenAPI filtering or n8n integration.

Important:

> Capability discovery is not authorization. Every execution revalidates current Principal/Representation/policy/state.

---

## 10. Event contracts

External integration events are versioned contracts, not raw table-change notifications.

Initial candidates:

```text
request.created.v1
request.completed.v1
reservation.created.v1
reservation.rescheduled.v1
reservation.cancelled.v1
reservation.attendance_changed.v1
queue.entry_called.v1
slot_opportunity.created.v1
slot_offer.created.v1
slot_offer.expired.v1
communication.delivery_changed.v1
```

Each event envelope includes at least:

```text
event_id
schema_version/event_type
organization_id
occurred_at
public aggregate/reference ids
correlation ids when relevant
minimal safe payload
```

Do not expose internal DB row dumps as event schemas.

---

## 11. Capability composition rules

### Synchronous local composition

Use one local transaction when correctness requires simultaneous state change across module boundaries.

Examples:

```text
waitlist.accept_offer
  → consume SlotOffer + booking Hold
  → create Reservation
  → mark Opportunity filled
```

Do not split this merely to preserve module aesthetic purity.

### Eventual composition

Use outbox/events when the downstream action is a consequence that does not need to be atomic with the source transaction.

Examples:

```text
reservation created → confirmation/reminder tasks
reservation cancelled → SlotOpportunity
request created → n8n
queue called → notification
```

### External side effects

Never pretend PostgreSQL + WhatsApp/LiveKit/n8n/provider form a distributed ACID transaction.

Use:

```text
idempotency
provider correlation
retry/reconciliation
compensation when business-required
```

---

## 12. Explicitly unsupported V3-baseline promises

The capability surface intentionally does not promise:

```text
universal workflow definitions
arbitrary workflow graph execution
multi-offering shopping-cart reservations
capacity pools / late binding
route optimization / dispatch planning
universal fulfillment/outcome accounting
financial ledger/reconciliation platform
marketing campaign journeys
arbitrary cron code execution
clinical decision support
```

A future capability may introduce one of these only with a concrete use case, explicit domain contract and migration.
