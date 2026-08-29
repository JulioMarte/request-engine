# F5 Operational Recovery and Communications Contract

Status: **normative full F5 contract**. `14-operational-intelligence-roadmap.md` is the product authority for F5. A prior implementation tranche narrowed execution to immutable proposal + one-shot reschedule; that tranche did not supersede the roadmap. F5 is complete only when every capability required below is implemented and proven.

## 1. Purpose

F4 answers what live capacity remains. F5 turns that truth into durable, auditable operational recovery.

F5 MUST support the full recovery loop:

```text
material operational event
  -> automatic reprojection
  -> RecoveryIncident open/update
  -> affected commitments + impact classification
  -> authorized escalation / customer communication
  -> one or more explicit recovery actions
  -> authoritative owner mutations
  -> reprojection after each action
  -> resolve only when risk is actually cleared
```

F5 coordinates recovery but does not become a shadow owner of schedules, Reservations, Queue admission, capacity or Communications delivery.

## 2. Required recovery capabilities

The following are required F5 behavior, not optional future scope:

1. automatic event-triggered reprojection and escalation;
2. explicit operator stop-intake even when theoretical capacity remains;
3. extend-day recovery through one-day ScheduleException/additional-hours authority;
4. contextual/cadence-backed Reservation reschedule;
5. general Resource/provider replacement using authoritative contextual supply;
6. a durable, recovery-specific multi-action workflow;
7. impact communication for delay/at-risk state as well as post-reschedule communication.

A narrower implementation may be useful during development, but documentation MUST NOT redefine any item above as a non-goal, deferred capability, or completed-by-reuse substitute.

## 3. Authority boundaries

`operational_recovery` owns:

- `RecoveryIncident` lifecycle and recovery-specific workflow state;
- recovery assessment/proposal provenance;
- action intent and orchestration state;
- escalation policy/state;
- lineage between incident, action and Communications intent.

Owning modules remain authoritative:

- `live_capacity`: F4 projection and recovery source snapshot;
- `queue`: explicit ServiceQueue intake policy and admission enforcement;
- `catalog`: Location operational hours and Location-hours exceptions;
- `booking`: Resource/assignment schedule exceptions, contextual availability, Reservation/capacity mutation and contextual reschedule;
- `communications`: CommunicationTask, outbox, provider attempts and delivery results;
- platform scheduler/outbox: durable technical execution.

F5 MUST call public owner contracts. Reverse imports from owning modules into F5 domain code remain forbidden.

## 4. RecoveryIncident

A RecoveryIncident is the durable recovery-specific workflow aggregate for one operational context.

Minimum identity/state:

```text
organization_id
service_queue_id
resource_id
location_id
status = open | mitigating | resolved
source_revision
source_fingerprint
impact_kind = delay | capacity_shortfall | indeterminate
severity / escalation_level
current_proposal_id?
opened_at
last_assessed_at
resolved_at?
```

There MUST be at most one unresolved incident for the same authoritative recovery scope. Repeated source events update/reproject that incident rather than producing an unbounded set of unrelated incidents.

An incident MUST NOT be marked resolved merely because an action succeeded. Resolution requires a fresh F4 assessment showing the material risk no longer exists or an explicit, auditable terminal disposition for every affected commitment.

## 5. Event-triggered reprojection

Every material source change that advances F4 recovery truth MUST durably request reprojection. At minimum this includes changes to:

- QueueEntry admission/status/workload classification relevant to the ServiceQueue;
- ServiceSession state/progress facts and interruption state;
- ResourceActivity blockers;
- F4 projection/workload-estimate policy;
- Resource/assignment availability and ScheduleException state;
- Location operational hours/exceptions;
- Booking commitments that enter, move or leave the assessed scope.

The trigger path MUST be durable and deduplicated. It MUST use the existing ScheduledAction/outbox worker reliability model rather than process-local callbacks.

The scheduled handler MUST:

1. read the current recovery source revision;
2. rebuild the canonical F4 assessment;
3. ignore obsolete scheduled revisions safely;
4. open/update/resolve the RecoveryIncident transactionally with idempotent semantics;
5. create/update an immutable proposal when material action is required;
6. evaluate escalation/communication policy.

A burst of events may coalesce, but the latest authoritative revision MUST eventually be assessed.

Per superseded revision the scheduled handler may short-circuit with a cheap advisory freshness read (O(1) stale no-op) before rebuilding F4; the fenced commit above remains the authority that a revision is obsolete.

## 6. Materiality and affected commitments

F5 continues to use canonical F4 semantics:

```text
scheduled_shortfall = max(scheduled_committed_workload - executable_capacity, 0)
live_shortfall      = max(projected_remaining_workload - executable_capacity, 0)
material_shortfall  = max(scheduled_shortfall, live_shortfall)
live_pressure       = max(material_shortfall - scheduled_shortfall, 0)
```

Structural affected Reservations are only those whose captured commitment no longer fits authoritative remaining intervals. F5 MUST NOT numerically fill a shortfall by marking still-executable commitments.

Live QueueEntry/ServiceSession workload participates in materiality, source provenance and escalation, but it MUST NOT by itself identify or fabricate an affected Reservation. A live-only shortfall is therefore a valid risk-only recovery state with zero affected Reservations until Booking/F4 authority provides evidence that a specific commitment is no longer executable.

F5 must also classify delay when work still plausibly fits today but the recommended arrival/start window has materially moved. Delay is a communication/escalation input even when `material_shortfall == 0`.

## 7. Replayable provenance and stale safety

Every proposal/action authorization MUST retain the canonical source snapshot required to explain and re-hash the decision, including intervals, commitments, live work/progress, blockers, authoritative revisions and selected targets.

Before any irreversible mutation:

- F5 validates its expected incident/proposal source revision;
- the owning mutation authority locks and revalidates the relevant recovery source revision in its transaction;
- Reservation/configuration expected revisions are checked;
- target availability/context/commercial provenance is revalidated by Booking/Catalog/Queue as applicable.

Stale execution fails with conflict semantics and produces no successful action or downstream communication claiming success.

## 8. Explicit stop-intake

F5 MUST expose an explicit recovery action that changes the Queue-owned intake policy for the affected `ServiceQueue` even if capacity would otherwise permit admission.

Queue owns a typed, revisioned, tenant-scoped intake control with at least:

```text
accepting | stopped
reason
expected revision
optional effective_until
actor/audit/idempotency
```

`queue.check_in` MUST lock/read this policy inside the same authoritative transaction used to admit a QueueEntry. A stopped policy MUST reject walk-in/new admission with a machine-readable conflict and zero QueueEntry creation.

Stopping intake does not cancel existing Reservations or QueueEntries. Reopening intake is an explicit owner-controlled command.

## 9. Extend-day recovery

F5 MUST support an explicit `EXTEND_DAY` action for a concrete operational context.

The action composes existing owner commands:

- Catalog Location additional-hours exception when the physical Location would otherwise be closed;
- Booking Resource-wide or ResourceLocationAssignment additional-availability exception as appropriate.

The requested interval is timezone-aware, one-day bounded and explicit. It MUST NOT rewrite recurring schedules.

Because these facts have separate owners, orchestration is a durable recovery saga: each owner step is idempotent and recorded. Partial completion is visible and retriable; F5 MUST NOT report the action as succeeded until every required owner step is committed and a fresh F4 reprojection confirms the additional executable capacity.

## 10. Contextual/cadence-backed reschedule

Booking MUST provide a contextual recovery reschedule authority equivalent in safety to F1 contextual booking.

It MUST revalidate inside one Booking transaction:

- Reservation expected revision/status/subject authority;
- selected ResourceLocationAssignment identity/revision/effective interval;
- Location operational revision/hours/exceptions;
- Resource and assignment recurring schedules and exceptions;
- Resource availability revision;
- OfferingVersion/context terms and committed commercial semantics;
- contextual configuration fingerprint/staleness;
- capacity/shared-capacity claims;
- F5 recovery source revision guard.

A contextual Reservation MUST no longer be marked non-actionable merely because the target carries assignment provenance.

## 11. General Resource/provider replacement

Recovery alternatives MUST be generated from Booking's authoritative contextual slot planner, not by editing Resource IDs on an existing Reservation.

Replacement may choose another eligible Resource and/or ResourceLocationAssignment that satisfies Offering requirements, Location constraints, context terms and capacity.

Cross-Organization provider replacement, where discovery policy permits it, is a two-boundary operation: F2 discovery may find an explicitly published external supply option, but execution must use the owning Booking handoff/commitment authority and must explicitly dispose the old commitment only after the new authoritative commitment is secured under the documented recovery transaction/saga semantics. F5 never gains cross-tenant RLS bypass.

Disposition note (current tranche): `feature/f5-roadmap-authoritative-recovery` delivers and proves intra-Organization replacement (see `34-operational-recovery-acceptance-evidence.md`). Cross-Organization execution via F2 discovery + Booking handoff remains conditional scope and is not implemented in this tranche; the requirement above stands unchanged.

## 12. Multi-action recovery workflow

F5 MUST implement a domain-specific recovery workflow, not a generic BPM engine.

Supported action kinds are a closed set:

```text
STOP_INTAKE
REOPEN_INTAKE
EXTEND_DAY
RESCHEDULE
REPLACE_RESOURCE
COMMUNICATE_IMPACT
```

Each `RecoveryAction` records:

```text
incident_id
action_kind
actor/system principal
canonical payload + fingerprint
expected source revision
status = prepared | running | succeeded | rejected | partially_applied
owner-step state
idempotency identity
failure code
timestamps
```

Actions may be executed in sequence. Every successful capacity/schedule/Reservation/intake mutation schedules a fresh reprojection. The next action must be authorized against the refreshed incident truth; an earlier authorization cannot silently carry across a materially changed source revision.

## 13. Escalation and communications

Material events trigger escalation evaluation before closing time.

At minimum F5 distinguishes:

```text
delay
capacity shortfall risk
confirmed recovery action result
```

Policy may request:

- operator escalation for newly material shortfall or worsening severity;
- customer impact notification when a planned/recommended time becomes unrealistic;
- updated notification after successful reschedule/replacement;
- resolution/update notification when appropriate.

Communications owns delivery. Stable dedupe identity derives from incident/action + recipient + purpose + source revision so worker retry and repeated reprojection do not create duplicate logical intents. Recovery communication purpose is explicit and typed: impact/risk communication (delay or shortfall, no mutation claimed) is distinct from post-reschedule confirmation, and the persisted purpose MUST match what actually happened.

The delivered default policy evaluates inside the scheduled assessment transaction and records a durable, immutable escalation outcome per incident and source revision: operator escalation is required when a material incident is newly opened or its severity worsens, and customer-impact notification is requested only for identified affected commitments whose planned commitment stopped being realistic. Delivering that notification remains the explicit `COMMUNICATE_IMPACT` action unless a later accepted policy grants a system actor that authority (section 14).

Internal cause/provenance MUST remain separate from public-safe communication payload.

## 14. Automation actor

Automatic reprojection may run without human authorization because it is read/assessment orchestration. Any automatic irreversible action requires an explicit system Principal with capability/Representation appropriate to that action and must be auditable. F5 MUST NOT impersonate a human operator.

The default recovery policy does not autonomously reschedule or extend the day. Those actions require explicit operator authorization unless a later policy explicitly grants a system actor that authority.

## 15. Required acceptance proof

The PostgreSQL-backed suite MUST directly prove:

A. **event-driven incident** — a material Queue/ServiceSession/schedule change automatically schedules and processes reprojection, opens/updates one incident, coalesces duplicate events, and resolves only after truth is restored;

B. **explicit stop-intake** — with remaining theoretical capacity, STOP_INTAKE prevents a concurrent/new walk-in admission transactionally; REOPEN_INTAKE restores admission; replay and different-payload same-key semantics are proven;

C. **extend day** — a shortfall caused by closing time is mitigated by one-day Location + assignment/resource additional-hours exceptions, F4 executable capacity increases, the incident is reprojected, and no recurring schedule is rewritten;

D. **contextual reschedule** — an affected contextual Reservation is successfully moved with assignment/configuration provenance preserved; stale assignment/location/price/capacity races fail closed;

E. **replacement resource** — Booking proposes and commits an eligible alternate Resource/context while preserving Offering/subject/commercial/capacity invariants;

F. **multi-action workflow** — one incident executes at least two different action kinds sequentially, persists each action/owner-step outcome, reprojects between them, and converges under retry/concurrency;

G. **delay communication** — a material delay with no capacity shortfall can create a deduped customer-impact CommunicationTask without requiring a Reservation reschedule;

H. **tenant/security** — all new tables/functions/actions remain FORCE-RLS/least-privilege safe and no SECURITY DEFINER path accepts caller-supplied foreign tenant authority.

A green aggregate suite without identifiable assertions for A-H is not completion evidence.

## 16. Completion gate

F5 is complete only when the roadmap, this contract, implementation, owner contracts, migrations, module ownership docs, direct PostgreSQL A-H evidence and exact-head CI agree.

There is no separate "core complete / broader scope later" completion definition. The original roadmap capability set above is the F5 completion boundary.
