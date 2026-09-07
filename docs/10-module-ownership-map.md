# Request Engine — current module ownership map

> **Estado:** normativo para ownership del backend actual.
>
> Este documento describe el sistema que existe hoy. No usa V2/V3/F1–F7 como autoridad arquitectónica. La semántica que debe preservarse proviene de `docs/testing/current-guarantees.toml` y de los contratos actuales de cada capability; la evolución estructural se rige por `docs/architecture/continuous-evolution-policy.md`, `docs/architecture/system-optimization-mode.md` y `docs/09-python-module-architecture.md`.

## 1. Current architecture

Request Engine is a modular monolith. Business truth lives in explicit business modules; technical cross-cutting mechanics live in `platform`; process composition lives in `bootstrap` and `entrypoints`.

Current active business-module inventory:

```text
tenancy
catalog
requests
booking
queue
communications
discovery
delivery
live_capacity
operational_recovery
operational_copilot
```

`payments` and `dispatch` are **not current Python modules**. They remain future domain areas only. If either becomes real product scope, it must enter the module inventory through an explicit ownership/dependency decision rather than pre-created scaffolding.

## 2. Ownership summary

| Module | Primary ownership |
|---|---|
| `tenancy` | Organization, Principal, Party, PartyContactPoint identity/normalization, Representation and tenant/subject authority truth |
| `catalog` | Location, Offering/OfferingVersion, ResourceCapability vocabulary, OfferingResourceRequirement and structured operational configuration |
| `requests` | RequestDefinition/Version, durable new business Request, participants/correlation and bounded generic request-extension payload/result boundary |
| `booking` | Resource planning, contextual Resource-at-Location supply, availability, BookingContextTerms/commercial provenance, CapacityHold/CapacityClaim, Reservation, AttendanceResponse and commitment/revalidation |
| `queue` | ServiceQueue/QueueEntry waiting/calling/no-show/check-in/walk-in/FIFO plus WaitlistEntry/SlotOpportunity/SlotOffer recovery interest |
| `communications` | transactional communication intent, CommunicationTask/Delivery, reminder/acknowledgement and provider-delivery lineage |
| `discovery` | explicitly published cross-tenant supply projection, canonical mapping/publication and opaque Booking handoff |
| `delivery` | ReservationAccess plus actual ServiceSession/Interruption/ResourceActivity execution truth |
| `live_capacity` | advisory live-capacity/ETA/intake projection over published Booking/Queue/Delivery facts |
| `operational_recovery` | immutable recovery proposal/provenance and one-shot recovery execution composition over owner contracts |
| `operational_copilot` | bounded typed external operational-tool/admission surface; owns no underlying business truth or conversational runtime |
| `platform` | technical DB/idempotency/outbox/scheduling/audit/events/observability/security mechanics only |

The table is an ownership map, not a mandate to retain today’s filesystem forever. Moving ownership is allowed only through an explicit architecture change that preserves or supersedes the affected guarantees and updates the executable dependency policy.

## 3. Hard ownership boundaries

### Tenancy

Owns identity and authority truth. A caller-supplied tenant, principal, Party or Representation identifier never manufactures authority. Party/contact-point records are not a generic CRM profile.

### Catalog

Owns stable/versioned service vocabulary and operational configuration such as Location, Offering/OfferingVersion, ResourceCapability and OfferingResourceRequirement. Catalog describes what can be configured/offered; it does not own concrete committed capacity.

### Requests

Owns durable new business demand requiring later processing. `Request` is not a universal mutation envelope for Booking, Queue, Delivery, Recovery or other capabilities.

### Booking

Owns planning and committed capacity truth:

```text
Resource
ResourceCapability assignment
ResourceLocationAssignment + contextual availability
BookingContextTerms / commercial commitment provenance
AvailabilitySchedule / ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Core rules:

```text
Resource      = booking capacity serialization root
CapacityClaim = Hold/Reservation consumption truth
Reservation   = planned commitment/history
```

Live execution does not rewrite planning history merely because reality differed from plan. Live Capacity is advisory and Operational Recovery must delegate legal Reservation/capacity changes back to Booking.

### Queue

Owns waiting/calling/admission/no-show state through ServiceQueue/QueueEntry. FIFO selection and customer/staff queue projections remain Queue semantics.

Queue also owns waitlist/released-slot interest through WaitlistEntry/SlotOpportunity/SlotOffer. Waitlist interest never becomes capacity authority; Booking remains the CapacityHold/CapacityClaim owner.

### Communications

Owns transactional communication intent and delivery lineage. Provider outcomes cannot directly become Booking, Queue, Delivery, Discovery, Live Capacity or Recovery authority.

### Discovery

Owns tenant-authorized publication/search projection and opaque handoff. Existence of Organization/Catalog/Booking data does not imply discoverability. Booking revalidates authoritative truth at commitment time.

### Delivery

Owns actual service execution truth:

```text
ReservationAccess
ServiceSession
ServiceSessionInterruption
ResourceActivity
actual Resource / Location used
actual workload classification
actual execution timestamps
```

Boundary:

```text
Reservation    = planned commitment/capacity history -> booking
QueueEntry     = arrival/wait/call state              -> queue
ServiceSession = what actually happened               -> delivery
```

Queue compatibility state and Delivery execution state may commit atomically when the lifecycle invariant requires one transaction; that does not transfer ownership.

### Live Capacity

Owns projection semantics only. It may combine published Booking, Queue and Delivery facts into deterministic live-capacity/ETA/intake results, but it does not own committed capacity, QueueEntry lifecycle, ServiceSession truth or recovery mutation.

Hard rules include:

- one coherent DB observation instant/snapshot;
- scheduled capacity and live intake headroom remain distinct;
- one real workload contributes at most once across Reservation/QueueEntry/ServiceSession representations;
- observed history may inform a projection but must not silently rewrite configured policy;
- uncertainty remains explicit instead of fabricated precision;
- reads/evaluations do not mutate authoritative source facts.

### Operational Recovery

Owns recovery composition and authorization lineage, not the underlying authorities. It may consume Live Capacity checkpoints, Booking alternatives and Communications contracts, but Booking remains Reservation/capacity authority and Communications remains delivery authority.

Proposal creation is immutable/idempotent and side-effect free with respect to Booking/Communications. Execution is one-shot, attributable to the authorizing Principal, stale-guarded by owner truth and resumable through stable idempotency identities.

### Operational Copilot

`operational_copilot` is a historical package name for the bounded external operational-tool boundary. It is not an embedded LLM/copilot and owns no conversational state.

It may expose typed reads/commands and deterministic admission/refusal over registered owner contracts. Model/tool arguments cannot create tenant, principal, Party, capability or revision authority. Ambiguous authoritative lookup fails closed rather than guessing.

### Platform

`platform` owns cross-cutting technical mechanics only: database/transaction support, idempotency, outbox/events, worker scheduling/fencing/retry/dead-letter mechanics, audit, observability and security plumbing.

Business meaning must not be moved into `platform`, `shared`, `common` or generic helpers merely to reduce visible module coupling.

## 4. Current synchronous dependency permission map

The executable source of truth for allowed synchronous Python edges is `tests/architecture/dependency_policy.py`; `docs/14-architecture-fitness-functions.md` describes the same policy.

```text
tenancy              -> none
catalog              -> none
requests             -> tenancy
booking              -> catalog, tenancy
queue                -> booking, tenancy
communications       -> booking
discovery            -> booking
delivery             -> none
live_capacity        -> booking, delivery, queue
operational_recovery -> booking, communications, live_capacity
operational_copilot  -> booking, catalog, discovery, live_capacity,
                        operational_recovery, queue, tenancy
```

Permission is not usage and does not transfer ownership. Every cross-module import must still use the target module’s supported `contracts` surface. The actual dependency graph must remain acyclic.

## 5. Current composition examples

### BookAppointment

Owner: Booking. Reservation and CapacityClaim effects commit atomically; advisory Discovery/Live Capacity data never substitutes for commitment-time validation.

### CheckIn / WalkIn / CallNext

Owner: Queue. Reservation-backed check-in validates planning without rewriting it. Walk-in creates waiting truth without fabricating a Reservation. CallNext serializes deterministic Queue selection.

### StartService / CompleteService

Composition: Queue + Delivery; execution truth owner: Delivery. The transaction may update Queue compatibility state together with ServiceSession state because the lifecycle invariant requires coherence.

### BuildLiveCapacityProjection / EvaluateIntake

Owner: Live Capacity. Read-only composition over published Booking/Queue/Delivery facts; does not create Reservation, CapacityClaim, QueueEntry or ServiceSession.

### CreateRecoveryProposal

Owner: Operational Recovery. Immutable idempotent snapshot over published owner contracts; no Booking/Communications mutation.

### ExecuteRecovery

Composition:

```text
Operational Recovery
    -> Live Capacity freshness/checkpoint semantics
    -> Booking guarded idempotent legal mutation
    -> Communications transactional intent
```

Each owner retains final authority over its own facts.

## 6. Future domain areas are not current modules

Payments/reconciliation and field-service dispatch/feasibility/routing remain possible future product areas. They intentionally have no package, dependency-policy node or current persistence ownership.

Activation requires:

1. an accepted product capability and explicit business owner;
2. a connection-surface/transaction design;
3. an explicit dependency-policy decision;
4. current guarantee/evidence disposition;
5. only then, the minimum package structure required by real code.

Do not recreate empty `payments`/`dispatch` packages as placeholders.

## 7. Ownership change gate

Moving a concept between modules, adding a new module or materially changing a connection surface requires one coherent change that updates, as applicable:

- the current capability/domain contract;
- this ownership map;
- `docs/09-python-module-architecture.md`;
- `docs/13-connection-surfaces.md`;
- `docs/14-architecture-fitness-functions.md` and `tests/architecture/dependency_policy.py`;
- affected module READMEs/contracts/tests;
- PostgreSQL ownership/read/cmd surfaces when persistence changes;
- `docs/testing/current-guarantees.toml` evidence disposition when a protected guarantee changes;
- an ADR when the ownership decision is difficult to reverse.

Historical V2/V3/Fx documents may explain provenance, but they do not override this current map solely because they described an earlier implementation shape.
