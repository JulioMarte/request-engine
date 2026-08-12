# V3 PostgreSQL disposition inventory

> **Estado:** arquitectura de transición, pre-implementation.
>
> Este inventario clasifica los objetos del design chain V2.6→V2.10 que ya fueron inspeccionados durante la revisión arquitectónica. No es una migración y no obliga a conservar nombres/columnas existentes. Su propósito es evitar que el candidato V3 herede objetos por accidente.

Disposition vocabulary:

```text
KEEP_PATTERN        keep the proven PostgreSQL idea/guarantee, not necessarily the exact table shape
KEEP_REWORK         concept belongs in V3 but schema/API should be redesigned
RE_EVALUATE         plausible baseline concept; prove necessity/simpler representation first
DEFER               valid future design knowledge, not first V3 baseline
DROP_FROM_BASELINE  no V3 baseline object unless a later concrete capability reintroduces it
NEW_V3              new concept justified by the capability-first product
```

---

## 1. Tenancy and authority

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `organizations` | KEEP_REWORK | hard tenant root remains foundational |
| `principals` | KEEP_REWORK | authenticated actor identity remains required |
| `parties` | KEEP_REWORK | minimal business/contact identity remains useful across channels |
| `representations` | KEEP_REWORK | on-behalf-of authority/revocation remains distinct from participant role |
| composite `organization_id` FK patterns | KEEP_PATTERN | preserve DB-provable tenant lineage |

V3 must additionally decide runtime role/RLS isolation before production baseline.

---

## 2. Catalog and structured business information

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `offerings` | KEEP_REWORK | agent/app capability discovery needs structured services/products |
| `offering_versions` | KEEP_REWORK | historical operational configuration should remain explainable |
| `resource_requirement_templates` | RE_EVALUATE | retain only if appointment/resource matching needs reusable requirement configuration |
| location/operating-location structures | KEEP_REWORK | business info + appointment location require a clear V3 Location model |

V3 likely needs structured business-profile/hours read surfaces, but should not become a CMS/RAG store.

---

## 3. Requests and intake

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `requests` | KEEP_REWORK | Request remains, with narrowed semantics |
| request participants | KEEP_REWORK | requester/recipient/authorized-party relationships remain useful |
| request targets | RE_EVALUATE | generic mutation Requests are no longer default; keep only for real demand targeting |
| external correlations | KEEP_REWORK | cross-channel continuation/correlation remains useful and non-authoritative |
| `offering_selections` | RE_EVALUATE | may become a smaller `RequestItem`/selection concept |
| `outcome_scopes` | DROP_FROM_BASELINE | no demonstrated independent outcome lifecycle in initial verticals |
| workflow key/version columns/concepts | DROP_FROM_BASELINE | replace universal Workflow semantics with typed handlers/policies/extensions |
| completion-validity machinery tied to OutcomeScope | DROP_FROM_BASELINE | reintroduce only with a real execution/outcome domain |
| generic intake storage | NEW_V3 | `IntakeDefinition` + `IntakeSubmission`, with versioned JSONB at ingestion boundary |

V3 Request types begin with durable business demand such as quote/callback/service/intake. Cancel/reschedule remain commands unless approval workflow is explicitly required.

---

## 4. Booking and local capacity

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `resources` | KEEP_REWORK | concrete reservable resources remain core |
| `resource_capabilities` | RE_EVALUATE | keep only if initial matching needs explicit capability qualification |
| resource capability assignments | RE_EVALUATE | follows capability decision |
| `availability_schedules` | KEEP_REWORK | local availability remains core |
| `schedule_exceptions` | KEEP_REWORK | closures/overrides remain required |
| `capacity_authorities` | RE_EVALUATE | stable serialization row is useful, but naming/shape may be simplified |
| `capacity_holds` | KEEP_REWORK | temporary local commitment remains useful |
| hold requirement intent tables | RE_EVALUATE | simplify unless multi-resource atomic holds are proven in first vertical |
| `capacity_claims` | KEEP_REWORK | common conflict/consumption truth remains the strongest V2 idea |
| `reservations` | KEEP_REWORK | confirmed booking commitment remains core |
| `reservation_items` | RE_EVALUATE | keep only if one Reservation must contain independent offering items in first vertical |
| `commitment_requirements` and joins | RE_EVALUATE | avoid generic requirement graph until multi-resource commitments prove it |
| `resource_allocations` | RE_EVALUATE | likely merge reservation capacity consumption into `CapacityClaim`; retain only if it represents independent operational assignment truth |
| `capacity_pools` | DEFER | no initial product requirement |
| capacity-pool memberships | DEFER | follows pool deferral |
| `planning_contexts` | DEFER | field-service planning is outside baseline |
| PlanningRevision | DEFER | follows planning/dispatch deferral |
| external commitment references | DEFER | no initial external capacity authority requirement |
| external commitment requirement links | DEFER | follows external commitment deferral |

### V3 capacity objective

Prefer a model close to:

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim(kind = hold | reservation)
Reservation
```

while preserving exclusive/unit capacity safety and canonical locking.

### Mandatory reschedule change

Do not carry forward the V2 protocol that universally acquires a replacement Hold before releasing the Reservation being replaced.

V3 must prove:

```text
lock Reservation
lock old/new capacity sources in canonical order
validate final desired state excluding claims replaced by same operation
replace claims atomically
rollback leaves original reservation intact
```

---

## 5. Queue and waitlist

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| V2 `queue_entries` | KEEP_REWORK | becomes explicit ServiceQueue/QueueEntry capability |
| AdmissionScope/admission abstraction | DROP_FROM_BASELINE | too broad for initial FIFO queue unless concrete case proves need |
| mixed waitlist behavior in delivery | DROP_FROM_BASELINE | replaced by explicit Waitlist semantics |
| `service_queues` | NEW_V3 | stable queue identity/configuration |
| `waitlist_entries` | NEW_V3 | future capacity interest; does not consume capacity |
| `slot_offers` | NEW_V3 | expiring deterministic offer when capacity becomes available |

ServiceQueue and Waitlist must have separate invariants despite sharing a V3 module.

---

## 6. Execution / fulfillment

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `service_sessions` | DEFER | not required for first booking/queue/customer-service verticals |
| `fulfillments` | DEFER | no baseline outcome-proof requirement yet |
| fulfillment corrections | DEFER | follows Fulfillment deferral |
| correction/supersession triggers | DEFER | do not port known quantity-correction ambiguity into V3 |

If execution later becomes real product scope, redesign it from concrete use cases rather than resurrecting OutcomeScope automatically.

---

## 7. Payments / financial domain

All inspected V2 financial tables are **DEFER** for the first baseline, including concepts equivalent to:

```text
price_determinations
payment_requirements
payment_attempts
payment_evidence
payment_transactions
financial_observations
observation_corrections
financial_reversals
payment_allocations
payment_allocation_adjustments
refunds
disputes
reconciliation_cases
```

The V2 distinctions remain useful future design knowledge. Re-entry begins only with concrete product policies such as deposit-before-confirm or reserve-now/pay-before-deadline.

Do not delete historical V2 SQL files; simply do not reproduce these objects in the first clean V3 candidate.

---

## 8. Dispatch / field service

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| dispatch tables | DEFER | no first-vertical need |
| destination-change lineage | DEFER | follows dispatch |
| field-service feasibility snapshots | DEFER | follows dispatch |
| planning revision links | DEFER | follows dispatch |

No route optimizer/GPS scope enters V3 core.

---

## 9. Communications — NEW V3

New baseline concepts:

```text
communication_tasks
communication_deliveries
communication_templates OR template references
communication_preferences/contact endpoint references as narrowly required
reminder_plans
reminder_acknowledgements when a use case requires acknowledgement
```

### CommunicationTask

Authoritative durable intent:

```text
organization
purpose
recipient/Party or endpoint reference
source/subject typed reference
template/version
channel policy
not_before / expires_at where needed
dedupe identity
business status
```

### CommunicationDelivery

Append/attempt-oriented provider execution facts:

```text
task
channel/provider
attempt number
provider message/call id
status
started/completed timestamps
error/result classification
```

Provider callbacks dedupe by provider event identity and never directly mutate unrelated business aggregates.

---

## 10. Durable scheduling — NEW V3

New technical baseline concept:

```text
scheduled_actions
```

Required mechanics:

```text
execute_at
pending/leased/completed/cancelled/dead lifecycle
lease_until
claim_token/fencing
attempt_count
max_attempts
next_attempt_at
last_error_class
owner module/action type
dedupe identity
payload/reference
```

Claim transaction and external execution are separate. Stale worker completion must be rejected by fencing token.

Do not overload `outbox_messages` to become a generic delayed scheduler unless a proof shows the semantics remain clean; outbox delivery and future business scheduling have different lifecycles.

---

## 11. Platform objects

| V2 object/concept | Disposition | V3 rationale |
|---|---|---|
| `provider_events` | KEEP_REWORK | dedupe/correlation for external callbacks remains required |
| `idempotency_records` | KEEP_REWORK | critical for retried agent/API commands |
| `audit_records` | KEEP_REWORK | durable mutation audit remains required |
| `domain_events` | RE_EVALUATE | keep if internal event log has a concrete role separate from outbox |
| `outbox_messages` | KEEP_REWORK | after-commit integrations/communications remain core |
| outbox lease/fencing from V2.10 | KEEP_PATTERN | proven worker safety pattern |
| outbox infinite/unbounded retry behavior | REPLACE | add max-attempt/dead-letter/manual replay semantics |
| `request_read.*` views | REPLACE | recreate only capability-oriented V3 read contracts |
| `request_cmd.*` capacity/idempotency/outbox functions | KEEP_PATTERN | preserve only narrow primitives required by V3 objects |
| V2 planning-revision command functions | DEFER | follows planning deferral |
| `request_admin.*` diagnostic concept | KEEP_PATTERN | useful operational boundary; recreate only for V3 objects |

---

## 12. New read/API surfaces to target

Do not preserve V2 views simply because clients do not yet exist.

Candidate V3 read contracts should follow capability needs:

```text
business_info_v1
catalog_offering_v1
appointment_availability_v1
reservation_status_v1
service_queue_status_v1
waitlist_status_v1
request_status_v1
communication_delivery_status_v1   # admin/operational, not necessarily public agent tool
scheduled_action_health_v1          # admin/operational
```

Names are provisional until HTTP/application contracts are specified.

---

## 13. Required PostgreSQL proof carried forward

Even though many V2 objects are removed, these correctness patterns survive:

- tenant equality enforced structurally on critical lineage;
- typed FKs rather than authoritative polymorphic strings where correctness depends on reference integrity;
- stable lock rows/serialization roots for hot conflict spaces;
- canonical lock order;
- range/interval semantics explicit and race-tested;
- no capacity oversell under concurrency;
- idempotency acquisition/completion race safety;
- append-oriented provider/audit/delivery facts;
- outbox/scheduled-worker lease and fencing;
- `SKIP LOCKED` for worker batch claiming when appropriate;
- no external I/O while authoritative DB locks are held;
- deny-by-default database interface privileges for app roles;
- real PostgreSQL race tests rather than in-memory approximations.

---

## 14. Objects intentionally not decided yet

Do not force a schema decision before the first vertical slice answers it:

```text
Do appointments need ReservationItem at all?
Do offerings need reusable ResourceRequirementTemplate in the first vertical?
Does CapacityAuthority deserve a separate row or can Resource be the lock authority in V1?
Can one CapacityClaim represent both hold/reservation consumption cleanly?
Does AttendanceResponse need its own append/history table or a small reservation child state?
Does generic IntakeDefinition need relational schema metadata or only version/key + validated JSON schema reference?
Should SlotOffer reserve capacity with a short Hold or only revalidate on accept for the first business policy?
```

Resolve these with executable verticals/races, not abstract completeness.

---

## 15. Exit criterion for this inventory

This inventory is complete enough to start a clean V3 candidate only when every table/function/view in the V2 design chain has been mechanically checked against one of these dispositions and the remaining `RE_EVALUATE` items required by the first verticals have explicit decisions/tests.

The final candidate should be much smaller than V2.10 by design. A smaller schema is a success if it defends all promises the actual product makes.
