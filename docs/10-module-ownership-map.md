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
onboarding
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
| `operational_recovery` | immutable recovery proposal/provenance plus recovery-action orchestration over Booking/Catalog/Communications/Live Capacity/Queue owner contracts |
| `operational_copilot` | bounded typed external operational-tool/admission surface; owns no underlying business truth or conversational runtime |
| `onboarding` | cross-domain setup/readiness projection over owner-published Tenancy/Catalog/Booking/Queue/Communications facts; owns no source truth |
| `platform` | technical DB/idempotency/outbox/scheduling/audit/events/observability/security mechanics only |

The table is an ownership map, not a mandate to retain today’s filesystem forever. Moving ownership is allowed only through an explicit architecture change that preserves or supersedes affected guarantees and updates executable dependency policy.

## 3. Hard ownership boundaries

### Tenancy
Owns identity and authority truth. Caller-supplied tenant, principal, Party or Representation identifiers never manufacture authority. It publishes the minimal business-Party fact used by Onboarding; it does not own aggregate setup readiness.

### Catalog
Owns stable/versioned service vocabulary and operational configuration such as Location, Offering/OfferingVersion, ResourceCapability and OfferingResourceRequirement. Catalog describes what can be configured/offered; it does not own concrete committed capacity.

### Requests
Owns durable new business demand requiring later processing. `Request` is not a universal mutation envelope for Booking, Queue, Delivery, Recovery or other capabilities.

### Booking
Owns planning and committed capacity truth: Resource, ResourceCapability assignment, contextual ResourceLocationAssignment/availability, BookingContextTerms, AvailabilitySchedule/ScheduleException, CapacityHold, CapacityClaim, Reservation and AttendanceResponse.

```text
Resource      = booking capacity serialization root
CapacityClaim = Hold/Reservation consumption truth
Reservation   = planned commitment/history
```

Live execution does not rewrite planning history merely because reality differed from plan. Live Capacity is advisory and Operational Recovery delegates legal Reservation/capacity changes back to Booking.

### Queue
Owns ServiceQueue/QueueEntry waiting/calling/admission/no-show state and WaitlistEntry/SlotOpportunity/SlotOffer recovery interest. Queue publishes an explicit intake-control contract used by Operational Recovery; Recovery does not acquire Queue authority by coordinating that action.

### Communications
Owns transactional communication intent and delivery lineage. Provider outcomes cannot directly become Booking, Queue, Delivery, Discovery, Live Capacity or Recovery authority.

### Discovery
Owns tenant-authorized publication/search projection and opaque handoff. Existence of Organization/Catalog/Booking data does not imply discoverability. Booking revalidates authoritative truth at commitment time.

### Delivery
Owns actual service execution truth: ReservationAccess, ServiceSession, ServiceSessionInterruption, ResourceActivity, actual Resource/Location and execution timestamps. Queue compatibility state and Delivery execution state may commit atomically when the lifecycle invariant requires it; that does not transfer ownership.

### Live Capacity
Owns projection semantics only. It combines published Booking, Queue and Delivery facts into deterministic live-capacity/ETA/intake results without becoming commitment, queue or execution authority.

### Operational Recovery
Owns recovery composition and authorization lineage, not the underlying authorities. Its real synchronous owner dependencies are Booking, Catalog, Communications, Live Capacity and Queue. Stop/reopen intake goes through Queue's published intake contract; extend-day uses Catalog's Location schedule contract plus Booking assignment schedule semantics; other actions similarly retain owner validation.

These edges are intentionally visible inside `operational_recovery/adapters/` and the executable dependency graph rather than hidden in `bootstrap`.

### Operational Copilot
`operational_copilot` is a historical package name for the bounded external operational-tool boundary. It owns no conversational state or underlying business truth and may operate only through registered owner contracts.

### Onboarding
Owns the read-only `onboarding.read` readiness composition and `/v1/onboarding/readiness` projection. It consumes narrow facts from Tenancy, Catalog, Booking, Queue and Communications and derives blockers/readiness. It never provisions missing state or mutates source owners.

The fan-out is deliberate: onboarding is itself the cross-domain product capability. Hiding this composition in `entrypoints` or assigning it nominally to Tenancy would make the dependency graph inaccurate.

### Platform
`platform` owns cross-cutting technical mechanics only: database/transaction support, idempotency, outbox/events, worker scheduling/fencing/retry/dead-letter mechanics, audit, observability and security plumbing. Business meaning must not move there merely to reduce visible module coupling.

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
operational_recovery -> booking, catalog, communications, live_capacity, queue
operational_copilot  -> booking, catalog, discovery, live_capacity,
                        operational_recovery, queue, tenancy
onboarding            -> booking, catalog, communications, queue, tenancy
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
Owner: Live Capacity. Read-only composition over published Booking/Queue/Delivery facts.

### ExecuteRecovery
Composition:

```text
Operational Recovery
    -> Live Capacity freshness/checkpoint semantics
    -> Booking guarded idempotent legal mutation
    -> Catalog / Queue owner actions when the selected RecoveryAction requires them
    -> Communications transactional intent
```

Each owner retains final authority over its own facts.

### ReadOnboardingReadiness
Owner: Onboarding.

```text
Tenancy business-Party fact
+ Catalog supply facts
+ Booking resource supply
+ Queue active supply
+ Communications configuration facts
-> Onboarding readiness/blockers projection
```

No source mutation occurs.

## 6. Future domain areas are not current modules

Payments/reconciliation and field-service dispatch/feasibility/routing remain possible future product areas. They intentionally have no package, dependency-policy node or current persistence ownership.

Activation requires accepted product scope, explicit ownership, connection-surface/transaction design, dependency-policy decision, guarantee/evidence disposition and only then minimum package structure required by real code.

## 7. Ownership change gate

Moving a concept between modules, adding a new module or materially changing a connection surface requires one coherent change that updates, as applicable:

- current capability/domain contract;
- this ownership map;
- `docs/09-python-module-architecture.md`;
- `docs/13-connection-surfaces.md`;
- `docs/14-architecture-fitness-functions.md` and `tests/architecture/dependency_policy.py`;
- affected module READMEs/contracts/tests;
- PostgreSQL ownership/read/cmd surfaces when persistence changes;
- `docs/testing/current-guarantees.toml` evidence disposition when a protected guarantee changes;
- an ADR when the ownership decision is difficult to reverse.

Historical V2/V3/Fx documents may explain provenance, but they do not override this current map solely because they described an earlier implementation shape.
