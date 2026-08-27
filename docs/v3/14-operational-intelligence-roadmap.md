# Request Engine — Operational Intelligence Roadmap

Status: **accepted product/design direction**. F1-F4 are implemented feature slices. F5 has an implemented explicit-recovery core under active closure/hardening; the broader original recovery capability set is **not** fully delivered and remains explicitly disposed in `33-operational-recovery-old-new-disposition.md`. F6 remains future feature scope.

This roadmap preserves the product direction discovered during the post-V3 operational-design work. Detailed normative behavior belongs to each feature contract; this document explains sequencing and product boundaries. A later feature contract may split a roadmap item into delivery tranches, but it MUST preserve the original capability as explicit remaining scope rather than redefining it away.

## 1. North star

Request Engine is the authoritative operational system that lets an agent or application answer and execute questions such as:

```text
I want a cardiologist today at 5 PM near me.
What options are actually available, where, with whom, and at what price?
```

The answer must come from operational truth, not marketing content or learned conversational memory.

Authority split:

```text
Request Engine
  structured operational truth + deterministic execution

Directus / CMS
  presentation/editorial content, SEO, biographies, long-form FAQ

Conversation memory
  learned customer context and preferences

External providers
  provider-owned facts/integrations consumed through explicit contracts
```

Core rule:

> If a fact is necessary to determine whether, where, when, with whom, for how long or under what commercial/operational conditions an operation can be executed, that fact belongs in Request Engine or an explicit authoritative provider contract consumed by Request Engine.

Request Engine must not become a CRM, CMS, universal RAG store, EHR, universal pricing engine or opaque recommendation engine.

## 2. Roadmap structure and current status

```text
F1 Operational Profile / Contextual Supply     [implemented]
        |
        +--------------------+
        v                    v
F2 Geospatial          F3 Live Service
Cross-Tenant Discovery    Operations
[implemented]             [implemented]
                             |
                             v
                       F4 Live Capacity
                          Projection
                         [implemented]
                             |
                             v
                       F5 Operational
                    Recovery + Communications
                  [core implemented / broader scope open]
                             |
                             v
                    F6 Operational Copilot
                           [future]
```

Two product lines are unlocked by F1:

```text
Discovery:
F1 -> F2

Clinic/live operations:
F1 -> F3 -> F4 -> F5

Assisted configuration:
F1 + semantic commands -> F6
```

F2 normative behavior lives in `24-geospatial-cross-tenant-discovery-contract.md`.
F3 normative behavior lives in `26-live-service-operations-contract.md` with its current-state inventory in `27-live-service-operations-current-state-inventory.md`.
F4 normative behavior lives in `29-live-capacity-projection-contract.md` with its old-to-new implementation inventory in `30-live-capacity-projection-current-state-inventory.md`.
F5 core normative behavior lives in `32-operational-recovery-communications-contract.md`; `33-operational-recovery-old-new-disposition.md` preserves the original roadmap delta and records delivered, reused, partial and deferred capabilities; `34-operational-recovery-acceptance-evidence.md` records only evidence that has actually been demonstrated.

---

# F1 — Operational Profile & Contextual Supply

Status: **implemented/integrated foundation**.

Historical implementation branch:

```text
feature/operational-profile-contextual-supply
```

Normative contract:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
```

F1 makes RE authoritative for the minimum structured facts required to resolve concrete operational supply inside one tenant:

```text
Organization operational defaults
Location operational identity, address, contacts, coordinates and hours
Location schedule exceptions
Resource-at-Location assignment
Resource/assignment availability and exceptions
OfferingVersion operational terms
Resource + Location + Offering contextual price/duration
historical Reservation commercial commitment
```

F1 intentionally does not perform platform-wide discovery or live queue prediction.

---

# F2 — Geospatial Cross-Tenant Discovery

Status: **implemented predecessor feature**.

Normative contract:

```text
docs/v3/24-geospatial-cross-tenant-discovery-contract.md
```

F2 provides explicitly published, least-privilege cross-tenant discovery over F1 operational truth. It preserves `Organization` as tenant boundary, uses canonical service classification, exposes approved public provider/location identity, performs objective geospatial eligibility/ranking, and hands an opaque option to Booking for authoritative revalidation and commitment.

---

# F3 — Live Service Operations

Status: **implemented predecessor feature**.

Normative contract:

```text
docs/v3/26-live-service-operations-contract.md
```

F3 keeps Reservation planning, QueueEntry waiting state and ServiceSession execution distinct. It persists authoritative arrival/admission/call/service timestamps, expected versus actual workload, walk-ins and interruptions, while keeping clinical data outside Request Engine. These factual ingredients feed F4 without making prediction authoritative in F3.

---

# F4 — Live Capacity Projection

Status: **implemented predecessor feature**.

Normative contract:

```text
docs/v3/29-live-capacity-projection-contract.md
```

Implementation inventory:

```text
docs/v3/30-live-capacity-projection-current-state-inventory.md
```

F4 projects remaining workload against remaining effective operational time over Booking, Queue and Delivery facts. It is advisory: Booking remains schedule/Reservation/CapacityClaim authority; Queue remains live waiting-state authority; Delivery remains actual execution authority.

The first F4 slice uses an explicit `ServiceQueue + Resource + Location` scope, deterministic workload estimation/provenance, deduplication across planned/live/executing representations, coherent PostgreSQL observation time, explicit uncertainty, staff/customer projections and read-only intake evaluation.

F4 may expose projected overrun, insufficient headroom, affected commitments and indeterminate projection. It does not itself stop intake, notify customers, extend hours, replace providers or reschedule Reservations. Recovery composition belongs to F5.

---

# F5 — Operational Recovery & Communications

Status: **explicit recovery core implemented on `feature/operational-recovery-communications`; broader original recovery roadmap still open**.

Normative core contract:

```text
docs/v3/32-operational-recovery-communications-contract.md
```

Original-scope disposition:

```text
docs/v3/33-operational-recovery-old-new-disposition.md
```

Acceptance evidence:

```text
docs/v3/34-operational-recovery-acceptance-evidence.md
```

The implemented F5 core consumes the canonical F4 projection, including deduplicated Booking/Queue/ServiceSession workload and blockers, persists immutable recovery proposals, and supports explicit guarded one-shot execution while leaving authoritative Reservation/capacity mutation in Booking. Successful execution may create a bounded Communications intent; Communications owns durable delivery, retries, leases/fencing, provider-result ordering and reconciliation.

Keep distinct:

```text
Reservation planned time
recommended arrival time/window
queue admission
estimated service start
actual service start
```

Also distinguish:

```text
delay
  service probably still occurs today, later

capacity shortfall risk
  remaining active + queued + planned work likely does not fit effective availability
```

The original F5 product direction included more than the current explicit-recovery core. Its status is:

```text
live workload participates in recovery materiality       delivered
one-shot supported Reservation reschedule                delivered
customer communication after successful recovery         delivered
natural Booking rejection of unavailable new intake      reused
contextual/cadence-backed reschedule                      deferred
explicit operator stop-intake policy                      deferred
extend-day via ScheduleException                          deferred
general/contextual replacement provider/resource          partial/deferred
automatic event-triggered reprojection/escalation         deferred
generalized multi-action recovery workflow                not in v1 / future decision
```

Therefore the phrase `F5 implemented` must not be used without the qualifier **core slice**. The broader recovery roadmap is complete only when the deferred rows above are delivered or explicitly superseded by a later accepted product decision.

Internal cause and public communication language remain separate privacy concerns.

---

# F6 — Operational Copilot

Status: **future**.

Planned branch:

```text
feature/operational-copilot
```

F6 lets an assistant inspect operational truth and propose/execute supported semantic configuration commands under explicit authority.

Examples:

```text
"Dr. A will work until 7 PM today"
"stop accepting walk-ins for the rest of the day"
"publish Dr. B for cardiology discovery"
"show me which Reservations are at risk"
```

The copilot must call typed semantic commands; it must not generate arbitrary SQL or gain authority merely because a human described an intent in natural language.

Every mutation still requires the normal authority, validation, optimistic concurrency, idempotency and audit contracts of the underlying command.

---

## 3. Cross-feature invariants

Across F1-F6:

1. `Organization` remains the tenant security boundary.
2. Cross-tenant behavior is explicit and least-privilege; platform scope is not admin/RLS bypass.
3. `Resource` remains the operational service provider identity; public/discovery identity is an approved projection, not authority.
4. Booking owns authoritative planning commitments and capacity consumption.
5. Queue/Delivery facts describe live reality without rewriting planning history.
6. Projection is derived/advisory and must preserve uncertainty/provenance rather than fabricate truth.
7. Recovery composes owner-controlled contracts; it does not create shadow schedule, Reservation, capacity or delivery authorities.
8. Communications owns durable delivery semantics; upstream business success is not rolled back because downstream notification fails.
9. Unsupported product states fail closed and must not be presented as actionable.
10. Every mutation remains capability-gated, tenant-scoped, auditable, idempotent where required and protected by the owning module's concurrency contract.
11. Historical evidence remains exact-head evidence; a green run for an older SHA does not prove a later branch head.
12. A narrower implementation slice may defer roadmap capability, but documentation must preserve that remaining scope rather than redefine it as delivered.
