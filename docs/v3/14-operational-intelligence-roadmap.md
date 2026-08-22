# Request Engine — Operational Intelligence Roadmap

Status: accepted product/design direction; only F1 is implementation scope of `feature/operational-profile-contextual-supply`.

This document preserves the complete product and architecture direction discovered during the exploratory design session that produced the first post-V3 operational-profile feature.

It exists for two reasons:

1. prevent later work from losing or silently changing decisions already reached;
2. keep F1 implementation scope narrow while documenting the downstream features that depend on it.

This is **not** permission to implement F2–F6 in the F1 branch. Each later feature must branch from the then-current `development`, reconcile its own normative contracts and prove its own invariants.

---

## 1. North star

Request Engine is the authoritative operational system that lets an agent or application answer and execute questions such as:

```text
I want a cardiologist today at 5 PM near me.
What options are actually available, where, with whom, and at what price?
```

The answer must be assembled from operational truth, not from marketing content or learned conversational memory.

The intended authority split is:

```text
Request Engine
  structured operational truth + deterministic execution

Directus / CMS
  presentation/editorial content, SEO, biographies, imagery, long-form FAQ

Memory
  dynamically learned customer context and conversational preferences

External providers
  provider-owned facts/integrations that RE consumes through explicit contracts
```

Core rule:

> If a fact is necessary to determine whether, where, when, with whom, for how long or under what commercial/operational conditions an operation can be executed, that fact belongs in Request Engine or an explicit authoritative provider contract consumed by Request Engine.

Request Engine must not become a CRM, CMS, universal RAG store, EHR, universal pricing engine or recommendation engine.

---

## 2. Roadmap structure

```text
F1 Operational Profile / Contextual Supply
        |
        +--------------------+
        v                    v
F2 Geospatial          F3 Live Service
Cross-Tenant Discovery    Operations
                             |
                             v
                       F4 Live Capacity
                          Projection
                             |
                             v
                       F5 Operational
                    Recovery + Communications
                             |
                 +-----------+
                 v
          F6 Operational Copilot
```

Two product lines are intentionally unlocked by F1:

```text
Discovery:
F1 -> F2

Clinic/live operations:
F1 -> F3 -> F4 -> F5

Assisted configuration:
F1 + semantic configuration/recovery commands -> F6
```

---

# F1 — Operational Profile & Contextual Supply

Implementation branch:

```text
feature/operational-profile-contextual-supply
```

F1 makes RE authoritative for the minimum structured facts required to resolve concrete operational supply inside one tenant.

Detailed active scope is defined in:

```text
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Normative post-V3 contract is defined in:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
```

F1 establishes at minimum:

```text
Organization operational profile defaults
Location operational identity/hours/contact points/geospatial coordinates
Resource-at-Location availability
Offering/OfferingVersion operational terms
Resource + Location + Offering contextual terms
planned duration
contextual price/effective dating
schedule exceptions
historical Reservation commercial commitment
```

F1 does not perform platform-wide discovery, live queue prediction or natural-language mutation.

---

# F2 — Geospatial Cross-Tenant Discovery

Planned branch:

```text
feature/geospatial-cross-tenant-discovery
```

## 2.1 Product goal

Allow a platform-facing agent/chatbot to ask across participating tenants:

```text
I need a cardiologist today at 5 PM within 10 km.
```

and receive concrete currently valid options such as:

```text
Dr. A
Clinic X
2.1 km
5:00 PM
DOP 3,500

Dr. B
Clinic Y
4.8 km
5:00 PM
DOP 3,000
```

The person chooses the provider. Request Engine does not autonomously decide who is “best”.

## 2.2 Security model

Cross-tenant discovery must **not** be implemented by giving a public chatbot `request_engine_admin` or generic RLS bypass authority.

Required separation:

```text
Platform Admin Authority
  control-plane/global identity/admin operations

!=

Platform Discovery Authority
  search explicitly published supply
  read explicitly public operational fields
  request availability
  book the option selected by the user under an authorized capability
```

`Organization` remains the tenant security/administrative boundary.

Cross-tenant identity correlation or knowledge of IDs never grants read authority.

The discovery service sees only supply explicitly authorized for publication.

## 2.3 Discovery publication

Operational existence is not the same as marketplace/public discovery visibility:

```text
exists operationally
!=
published for platform discovery
```

A tenant must be able to expose only selected combinations of:

```text
Offering
Location
Resource/provider when policy permits
availability
price
```

without exposing unrelated tenant state.

The exact persisted concept may be named `DiscoveryPublication` or another accepted term, but publication must be explicit, revocable, tenant-authorized and auditable.

## 2.4 Geospatial rules

F1 persists normalized Location coordinates. F2 consumes them for objective proximity queries.

Input may contain:

```text
origin latitude/longitude
radius
location/city constraints
```

Output may include:

```text
distance_meters
```

Distance can filter or order results but does not modify booking truth.

Fixed-location proximity is not `ServiceArea`.

Future `ServiceArea` means a geographic area where a mobile service can actually be delivered.

## 2.5 Ranking rule

Initial ranking is deliberately narrow:

> The user chooses. Popularity may change presentation order only.

Popularity must not:

```text
automatically select a doctor
hide otherwise valid options merely for being less popular
change eligibility
change price
change capacity truth
```

Popularity should be derived from objective operational data rather than an arbitrary editable score when enough data exists.

Examples of future source metrics:

```text
completed bookings / completed service in a bounded time window
```

The exact score is a read/projection concern, not Resource master data.

## 2.6 Future enrichment

Google Business URL, ratings and reviews may later enrich discovery results.

They are not transactional truth and must not initially live as authoritative fields on Resource merely for convenience.

Conceptually:

```text
RE operational option
+
external reputation/profile enrichment
->
presentation result
```

---

# F3 — Live Service Operations

Planned branch:

```text
feature/live-service-operations
```

## 3.1 Core distinction

The schedule predicts. The live queue represents reality.

Do not collapse:

```text
Reservation
QueueEntry
ServiceSession
```

Their intended semantics are:

```text
Reservation
  planned capacity in a time window

QueueEntry
  subject actually waiting to be served now

ServiceSession
  actual execution: service really started and ended
```

A booked time is therefore not necessarily a promise that service begins at the exact wall-clock instant for clinics that use arrival-order operations.

## 3.2 Arrival-order policy

For physicians/clinics configured as arrival FIFO:

```text
queue order = admitted_at, stable id tie-breaker
```

Example:

```text
Juan reservation 15:00, arrives 14:54
Maria reservation 15:30, arrives 14:50

live FIFO order:
1. Maria
2. Juan
```

The appointment remains planning/capacity context; arrival determines the live queue when this policy applies.

The system must not reorder people merely because one expected visit is shorter unless an explicit future queue policy authorizes that behavior.

## 3.3 Secretary/staff control surface

The staff UI should require minimal operational input. Typical actions:

```text
check in
classify expected visit
add walk-in
call next
start service
complete service
mark no-show
start interruption/activity
end interruption/activity
```

The secretary supplies real-world observations. RE calculates durations, waiting time, queue position and projections.

## 3.4 Important timestamps

The system should preserve actual timestamps rather than storing a frontend timer as authoritative state:

```text
scheduled_at?
arrived_at
admitted_at
called_at
service_started_at
service_completed_at
```

A timer displayed in a staff panel is derived from authoritative timestamps.

Browser refresh, disconnect or UI failure must not erase actual service timing.

## 3.5 Expected vs actual service classification

Operational visit variants established in F1 can classify expected workload, for example:

```text
new consultation
follow-up
results review
procedure
```

The vocabulary is tenant/Offering-owned, not a universal clinical taxonomy.

The live system should eventually distinguish:

```text
expected_visit_type
actual_service_type when operationally recorded
```

because an expected “results review” may become a full consultation.

Do not rewrite historical expectations to make the prediction appear correct.

## 3.6 Walk-ins

A person may enter the live queue without a prior Reservation when policy allows.

Walk-in acceptance remains an authorized operation and later consumes F4 live-capacity projections.

## 3.7 Resource operational activities / interruptions

The physician may temporarily stop ordinary patient service for reasons such as:

```text
emergency
medical representative visit
break
administrative interruption
other
```

These are operational facts and should not be disguised as ordinary patient consultations.

A conceptual model may include `ResourceActivity` or an equivalent timeline concept.

It must be possible to record:

```text
resource
location
category
started_at
completed_at
recorded_by
public communication classification when applicable
```

The exact model is a future F3 design decision.

## 3.8 Clinical-data boundary

Live operations may know operational facts such as:

```text
subject/patient was served
service type
resource
location
start/end
operational duration
```

They must not turn RE into an EHR/EMR.

Out of scope:

```text
diagnosis
clinical notes
symptoms
medications
medical history
clinical test interpretation
```

An external EHR may be integrated later through an explicit boundary.

## 3.9 Privacy of queue information

Staff may see identities required to operate the queue.

A patient-facing status must not expose the names or private details of people ahead in line.

External output may say:

```text
3 people ahead
approximate position #4
estimated wait 50 minutes
```

not the identity of those people.

---

# F4 — Live Capacity Projection

Planned branch:

```text
feature/live-capacity-projection
```

## 4.1 Core rule

> Daily clinical capacity is not just a slot count or patient count. It is projected remaining workload against remaining operational time.

The engine should use:

```text
remaining queue
expected visit classifications
configured planned durations
observed historical durations
current service in progress
interruptions
remaining Resource availability
remaining Location hours
existing future same-day reservations
```

to calculate operational projections.

## 4.2 Scheduled capacity vs live intake capacity

Keep two meanings distinct:

```text
scheduled_capacity
  future planning using schedules + commitments

live_intake_capacity
  same-day/now feasibility using schedules + commitments + live operational state
```

For a future date, normal booking availability may primarily use schedule + claims.

For “today at 5 PM”, RE should eventually also consider:

```text
current queue
service currently in progress
interruptions
remaining workload
observed/expected durations
```

A mathematically free future slot may therefore stop being offered for same-day intake when the day is already operationally overloaded.

## 4.3 Queue projections

Derived information may include:

```text
entries ahead
queue position
estimated wait
estimated service start
current delay
remaining workload
projected end-of-day
```

Position and ETA are projections/read models, not mutable counters or transactional capacity ledgers.

## 4.4 Duration estimation

Initially the system may use configured values:

```text
new consultation = 45m
follow-up = 20m
results review = 10m
```

As observations accumulate, estimates may combine:

```text
configured baseline
historical observations
recent same-day behavior
```

Useful aggregates include:

```text
count
median / p50
p75
p90
recent weighted estimate when justified
```

Do not rely only on a mean when long-tail consultations exist.

Observed data may improve projections, but it must not silently mutate authoritative scheduling policy.

## 4.5 Human control of learned recommendations

If observed data shows that a physician configured 30-minute appointments but normally takes 40+ minutes, RE may later recommend a change.

Example:

```text
Your last 60 cardiology consultations had a median duration of 41 minutes.
Your configured planned duration is 30 minutes.
Would you like to review the future appointment duration?
```

The physician/admin decides.

No autonomous ML policy mutation in the initial roadmap.

## 4.6 Same-day intake decision support

When staff tries to accept another Reservation or walk-in, RE may project its effect:

```text
current time: 16:15
normal end: 18:00
remaining workload: 1h27
new follow-up: ~20m
projected finish: 18:12
```

Staff/policy can then decide whether intake is allowed.

F4 may support both:

```text
hard configured daily limits
projected operational limits
```

A hard count alone must not replace workload projection.

---

# F5 — Operational Recovery & Communications

Planned branch:

```text
feature/operational-recovery-communications
```

## 5.1 Patient communication goal

Patients should be informed when live operations make the original planned time unrealistic.

Distinguish:

```text
Reservation planned time
recommended arrival time/window
queue admission
estimated service start
actual service start
```

They are not the same fact.

## 5.2 Dynamic arrival recommendation

A physician/clinic may configure an `ArrivalPolicy` or equivalent, for example:

```text
normal lead = 30 minutes
maximum early arrival = 60 minutes
minimum lead = 15 minutes
```

Live projections can then produce a changing `recommended_arrival_at` or window.

Example patient message:

```text
Your appointment remains confirmed.
The doctor is currently approximately 25 minutes behind.
We recommend arriving between 4:10 and 4:25 PM.
We will update you if this changes materially.
```

The planned Reservation does not need to be rewritten every time the ETA changes.

## 5.3 Delay vs capacity shortfall

Keep two states distinct:

```text
delay
  patient likely still served today, but later

capacity shortfall risk
  remaining work likely cannot fit inside effective remaining availability
```

A shortfall can be detected when, for example:

```text
projected completion of remaining work
>
effective Resource end time
```

## 5.4 Early escalation to staff

Do not wait until closing time.

Relevant events can trigger reprojection:

```text
service completed
new check-in
walk-in admitted
new same-day reservation
no-show
cancellation
emergency starts/ends
medical representative visit starts/ends
other interruption starts/ends
schedule extension
```

When shortfall risk becomes material, notify authorized staff/physician.

The control surface may offer:

```text
[ extend day ]
[ stop intake ]
[ reschedule affected ]
[ review manually ]
```

## 5.5 Extraordinary extension

If the physician decides to work later for one day, represent this as an effective schedule exception/additional availability, not a rewrite of the recurring weekly schedule.

Then recalculate remaining ETA/capacity.

## 5.6 Recovery when patients cannot be served

If the day will not be extended, RE should identify the Reservations at risk and support explicit recovery.

Conceptual process:

```text
affected Reservation
-> find valid replacement options
-> optionally hold/materialize bounded offers when policy allows
-> transactional communication
-> patient chooses
-> appointments.reschedule revalidates and commits
```

Do not silently choose a new appointment for the patient unless a future explicit business policy authorizes that behavior.

## 5.7 Communication privacy

Internal cause and public message are separate concerns.

Internally RE may know:

```text
medical_representative_visit
```

while public policy may only say:

```text
The doctor is temporarily delayed.
```

An emergency may have a different approved public message.

The patient does not automatically receive private operational details.

## 5.8 Operational metrics unlocked

From F3/F4/F5 facts the system can derive weekly operational metrics such as:

```text
patients served
time serving patients
median/p75/p90 service duration
medical representative visits
time with representatives
emergencies
emergency time
break time
median/p90 patient wait
overtime
patients that required recovery/rescheduling
```

The purpose is operational improvement, not clinical judgement.

---

# F6 — Operational Copilot / Control Plane

Planned branch:

```text
feature/operational-copilot-control-plane
```

## 6.1 Product goal

Give each physician/clinic an assistant capable of configuring authorized operational state through natural language while retaining deterministic Request Engine authority.

Examples:

```text
I will not work next Monday.

This Friday I stop at 2 PM.

Block 12 to 1 for lunch.

Starting next month my cardiology consultation costs DOP 4,000.

On Tuesdays I work at Clínica Brugal.

Patients should normally arrive 30 minutes early.

If I am more than 20 minutes behind, notify the remaining patients.
```

## 6.2 Non-negotiable execution boundary

```text
natural language
-> intent/entities
-> proposed semantic command
-> authority validation
-> invariant validation
-> explicit confirmation when risk requires it
-> Request Engine command
-> audit
```

Never:

```text
LLM -> SQL
LLM -> direct table mutation
LLM -> arbitrary operational_config JSONB
```

The LLM interprets. Request Engine determines whether the mutation is authorized and valid.

## 6.3 Confirmation for material changes

High-impact mutations should generally require explicit confirmation unless a trusted workflow has another accepted safety mechanism.

Examples:

```text
pricing changes
large availability changes
cancellation/recovery actions
publication changes
permission changes
```

Example confirmation:

```text
I will set cardiology at Clínica Brugal to DOP 4,000 effective September 1.
Confirm?
```

## 6.4 Role/authority direction

Do not prebuild a universal RBAC suite, but preserve these product roles as separate authorities:

```text
Physician
  permitted self/resource schedule and exceptions
  permitted policies
  pricing only when clinic policy delegates it

Secretary / operational staff
  check-in
  queue operations
  classification
  service/interruption timing actions
  rescheduling under permitted clinic policy

Clinic admin
  locations
  offerings
  staff/resource association
  pricing
  operational policies
  discovery publication

Platform discovery service
  published cross-tenant search
  selected-option booking capability
  no generic tenant enumeration/admin authority

Platform admin
  trusted control-plane/global identity/admin operations
```

Concrete permissions must be introduced only with real commands and tested authorization semantics.

---

# 7. Shared cross-feature principles

## 7.1 User choice

The system presents valid options. The person chooses the doctor/provider unless a later explicit product flow asks for a deterministic objective filter such as “cheapest” or “closest”.

Do not introduce subjective “best doctor” selection into the RE core.

## 7.2 Operational truth vs derived intelligence

Keep four conceptual planes distinct:

```text
1. Configuration
   profiles, schedules, exceptions, prices, policies, publication

2. Transactional/live operation
   reservations, capacity, queue, service execution

3. Operational observation
   arrival, called, started, completed, interruptions

4. Derived intelligence
   duration distributions, ETA, projected delay, popularity, utilization
```

Planes 1–3 may contain authoritative operational facts.

Plane 4 is derived/read-model intelligence unless a human-authorized command promotes a recommendation into configuration.

## 7.3 No clinical practice

RE operationalizes authorized business rules. It does not diagnose, prescribe or infer clinical treatment.

## 7.4 No external I/O under authoritative DB locks

Geocoding, messaging, Google enrichment and other provider calls occur outside authoritative lock-held transactions.

## 7.5 History must remain explainable

Effective-dated configuration and historical commitments must permit reconstruction of why an operation was valid and what commercial terms were committed at the time.

## 7.6 Existing shared-capacity safety remains valid

A physician represented in more than one Organization may already be bound to hidden shared capacity. New contextual supply and discovery must not weaken the cross-tenant mutex or leak foreign appointment metadata.

---

# 8. Explicitly deferred ideas

These are not part of F1–F6 unless separately justified:

```text
subjective provider recommendation engine
universal ranking/auction engine
route optimizer
travel-time scheduler
EHR/EMR
clinical notes/diagnosis/medications
universal pricing expression engine
insurance adjudication
full CRM
full CMS/RAG platform
autonomous ML changes to booking policy
```

A future travel/transition buffer for itinerant Resources may be justified because a doctor cannot physically finish at one city and instantly start in another. Do not implement route optimization merely to solve that future problem; first prove whether a simple explicit transition buffer satisfies real requirements.

---

# 9. Feature acceptance discipline

Each feature after F1 must:

1. branch from current `development` after prior dependencies merge;
2. update or add a post-V3 normative contract before schema code;
3. explicitly identify module ownership;
4. define authority and tenant isolation;
5. define transaction/race semantics;
6. add append-only production migrations only when needed;
7. preserve V3 baseline history and previously proven invariants;
8. prove behavior with adversarial tests, not only happy paths;
9. remain independently mergeable without implementing the next feature prematurely.

The roadmap preserves direction. It does not waive feature-level design proof.