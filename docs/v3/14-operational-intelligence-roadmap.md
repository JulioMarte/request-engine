# Request Engine — Operational Intelligence Roadmap

Status: **accepted product/design direction**. F1 is implemented/integrated. F2 is implemented on `feature/geospatial-cross-tenant-discovery` and remains subject to exact-head merge evidence. F3-F6 remain future feature scope.

This roadmap preserves the product direction discovered during the post-V3 operational-design work. Detailed normative behavior belongs to each feature contract; this document explains sequencing and product boundaries.

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
[implemented on PR #77]     [future]
                             |
                             v
                       F4 Live Capacity
                          Projection
                           [future]
                             |
                             v
                       F5 Operational
                    Recovery + Communications
                           [future]
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

F2 is no longer future-only roadmap scope. Its normative contract is `24-geospatial-cross-tenant-discovery-contract.md`.

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

Status: **implemented on `feature/geospatial-cross-tenant-discovery` / PR #77; exact-head merge evidence required**.

Normative contract:

```text
docs/v3/24-geospatial-cross-tenant-discovery-contract.md
```

## F2.1 Product goal

Allow a platform-facing agent/chatbot to ask across participating tenants:

```text
I need a cardiologist today at 5 PM within 10 km.
```

and receive concrete currently valid options such as:

```text
Dr. A
Clinic X
27 de Febrero 10, Puerto Plata
2.1 km
5:00 PM
DOP 3,500 / 45 min

Dr. B
Clinic Y
4.8 km
5:00 PM
DOP 3,000 / 30 min
```

The person chooses. Request Engine does not autonomously decide who is "best".

## F2.2 Security model

Cross-tenant discovery is not admin authority and is not generic RLS bypass.

```text
Platform Admin Authority
  taxonomy/global admin lifecycle

Tenant operations.manage_discovery
  mapping/public profile/publication configuration

Platform Discovery Authority
  search explicitly published supply through narrow functions

Booking
  authoritative commitment after normal tenant authority checks
```

`Organization` remains the tenant boundary. Cross-tenant identity correlation or knowledge of IDs never grants read authority.

## F2.3 Explicit publication

```text
exists operationally != published for platform discovery
```

`DiscoveryPublication` explicitly authorizes selected Offering + Location + optional Resource scope for an effective interval. Publication is revocable, auditable and does not copy schedule, price or capacity truth.

Broad and resource-specific publication overlap is prohibited and serialized.

## F2.4 Canonical service classification

F2 introduces platform `ServiceClassification` and explicit tenant Offering mapping. Initial F2 HTTP search consumes the canonical key; natural-language phrases such as `cardiólogo` may be resolved by the conversational/NLU layer or a later feature, but the transaction boundary does not guess classification semantics.

Mapping replacement preserves provenance and concurrent first mapping converges to one active mapping.

## F2.5 Public provider identity

F2 now supports the minimum public provider profile needed to answer "with whom":

```text
ResourcePublicProfile
  public display name
  optional role/title/specialty label
  optional public image/reference
```

A tenant maintains it through `operations.manage_discovery`.

```text
provider_visibility=hidden
  -> concrete Resource identity not returned

provider_visibility=public
  -> resource-specific publication + active public profile required
  -> only approved public provider fields returned
```

GlobalIdentity, SharedCapacityIdentity and private Resource/assignment fields remain hidden.

## F2.6 Public location identity

F2 reuses F1 Location truth and can return the approved public address projection so the agent can answer "where" without duplicating operational location data.

## F2.7 Geospatial and ranking rules

F1 persists normalized Location coordinates; F2 consumes them for objective radius queries.

Eligibility is inclusive:

```text
distance_meters <= radius_meters
```

Initial ordering is deliberately narrow:

```text
1 earliest appointment start
2 distance
3 deterministic stable tie-break
```

Popularity/reputation may later affect presentation only. It must not alter eligibility, price, capacity truth or automatically choose a provider.

## F2.8 Booking handoff

F2 returns opaque `discoopt_v1`, not a decodable normal Booking token. Internal Resource/assignment/provenance remains server-side.

Booking revalidates Publication, Mapping, current OfferingVersion and all F1 schedule/terms/assignment/capacity truth in the authoritative commitment transaction.

Discovery therefore remains advisory and stale-safe.

## F2.9 Performance follow-up

The correctness-first implementation may perform per-candidate slot reads and rejects searches broader than the safe exhaustive candidate bound.

A future `BatchPublishedSlotReader` is a desirable latency optimization provided it preserves identical authority, eligibility and ordering semantics. It is not a reason to weaken the F2 correctness contract.

---

# F3 — Live Service Operations

Status: **future**.

Planned branch:

```text
feature/live-service-operations
```

## F3.1 Core distinction

The schedule predicts; the live queue represents reality.

Keep distinct:

```text
Reservation
  planned capacity in a time window

QueueEntry
  subject actually waiting to be served now

ServiceSession
  actual execution: service really started and ended
```

A booked time is not always a promise of exact wall-clock service start for arrival-order businesses.

## F3.2 Arrival-order policy

For configured FIFO operations:

```text
queue order = admitted_at + stable tie-break
```

The appointment remains planning context; arrival determines live queue position when that explicit policy applies.

## F3.3 Staff control surface

Typical authorized actions:

```text
check in
classify expected visit
add walk-in
call next
start service
complete service
mark no-show
start/end interruption or ResourceActivity
```

The staff records real-world observations; RE derives elapsed duration, waiting time, queue position and projections.

## F3.4 Actual timestamps

Preserve authoritative timestamps rather than a browser timer:

```text
scheduled_at?
arrived_at
admitted_at
called_at
service_started_at
service_completed_at
```

Refresh/disconnect must not erase operational truth.

## F3.5 Expected vs actual service type

F1 operational visit variants may define expected workload. F3 should allow expected and actual service classifications to differ without rewriting history to make predictions look correct.

## F3.6 Walk-ins and interruptions

Walk-ins may enter the live queue when policy permits. Physician/staff interruptions such as emergency, break or administrative activity are operational facts and should not be disguised as patient consultations.

## F3.7 Clinical-data boundary

RE may know that a subject was served, by what operational service, where, by whom and for how long. It must not become an EHR/EMR containing diagnosis, clinical notes, medication or medical history.

## F3.8 Queue privacy

Staff may see identities required to operate the queue. Patient-facing status may expose counts/position/ETA, never names/private details of people ahead.

---

# F4 — Live Capacity Projection

Status: **future**.

Planned branch:

```text
feature/live-capacity-projection
```

Core rule:

> Daily live capacity is projected remaining workload against remaining operational time, not merely a slot count or patient count.

Inputs may include:

```text
remaining queue
expected visit types and configured duration
observed historical duration
service currently in progress
interruptions
remaining Resource availability
remaining Location hours
same-day Reservations
```

Keep distinct:

```text
scheduled_capacity
  future planning from schedule + commitments

live_intake_capacity
  now/today feasibility from schedule + commitments + live operational state
```

Derived projections may include:

```text
entries ahead
queue position
estimated wait/start
current delay
remaining workload
projected end-of-day
```

Observed duration may improve projections but must not silently mutate scheduling policy. The system may recommend a policy change; an authorized human decides.

---

# F5 — Operational Recovery & Communications

Status: **future**.

Planned branch:

```text
feature/operational-recovery-communications
```

F5 communicates when live operations make a planned time unrealistic and supports explicit recovery.

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
  remaining work likely does not fit effective availability
```

Material events should trigger reprojection and authorized escalation before closing time.

Potential staff actions:

```text
extend day via one-day schedule exception
stop intake
review affected Reservations
find replacement options
communicate with affected customers
reschedule after explicit selection/revalidation
```

Internal cause and public communication language are separate privacy concerns.

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
3. `Resource` remains the operational service provider/capacity concept; shared physical identity is hidden unless a specific contract says otherwise.
4. `Reservation` is planned commitment, not live queue state.
5. Live operational observations do not rewrite historical planning facts.
6. Predictions/read models never become authoritative counters merely for convenience.
7. Operational truth and editorial content remain separate.
8. Learned/observed behavior may recommend but must not silently mutate policy.
9. Public/customer projections reveal only fields explicitly approved by contract.
10. Every externally retryable mutation is authority-checked, idempotent and auditable.
11. Stale advisory state is revalidated in the authoritative commitment transaction.
12. Capacity cannot be oversold by discovery, live operations, recovery or copilot features.

## 4. Feature delivery policy

Each future feature must:

```text
branch from then-current development
write/reconcile its normative contract
inventory affected current guarantees
implement with explicit authority boundaries
add adversarial/concurrency evidence where the guarantee requires it
update current-guarantees.toml when introducing durable guarantees
map representative proofs in current-proof-map.toml
reconcile docs/README.md + this roadmap before merge
use exact-head CI as merge evidence
```

A previous feature's green CI is provenance, not evidence for a later feature's Definition of Done.

The roadmap records direction. The current feature contract defines what is actually implemented.