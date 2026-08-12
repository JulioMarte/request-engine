# Request Engine — adversarial V3 architecture review

> **Status:** normative review record for the pre-baseline V3 candidate.
>
> This review treats the current V3 documentation, Python and SQL as a hypothesis. It does not grant schema-freeze status. Findings are evidence-driven and intentionally prefer deletion/simplification over adding patterns.

## 1. Executive assessment

Request Engine is no longer best described as a universal Request/workflow engine. The strongest product model present in the repository is a **headless, multi-tenant operational capability API**: stable machine-facing capabilities backed by deterministic tenant-scoped transactional domains.

The V3 reduction is directionally sound. In particular, removing universal `Workflow`, `OutcomeScope`, `ResourceAllocation`, `CapacityAuthority`, `ReservationItem`, advanced dispatch/payment/fulfillment machinery from the baseline materially reduced accidental complexity.

The remaining architectural risk is different: the repository now has **strong written contracts ahead of complete vertical proof**. The next failure mode would be freezing a sophisticated schema because the documents are coherent rather than because each expensive concept survived executable product/race proof.

### Current rating

| Area | Rating | Reason |
|---|---|---|
| Product/domain thesis | GREEN | capability-first product boundary is substantially clearer than V2 |
| Bounded-module ownership | YELLOW | mostly coherent; some cross-module DB knowledge bypasses semantic module surfaces |
| Request semantics | GREEN | narrowed to durable new demand rather than universal mutation wrapper |
| Workflow model | GREEN | universal workflow aggregate removed; extension path remains bounded |
| Transactional correctness | GREEN/YELLOW | booking/request/queue protocols are unusually explicit, but not every baseline vertical is implemented |
| Booking/capacity | GREEN/YELLOW | minimal model and lock protocol are strong; implementation concentration needs clearer ownership semantics |
| ServiceQueue | GREEN/YELLOW | implemented FIFO vertical exists; remaining lifecycle/race breadth should grow with product evidence |
| Waitlist | ORANGE | schema and contracts exist before the Python vertical and complete race proof |
| Communications/reminders | YELLOW | useful vertical exists; temporal ownership between task/plan/scheduled action must remain explicit |
| Payments | GREEN as deferred | correct decision is still not to reactivate without product policy |
| Multi-tenancy | YELLOW | RLS design is strong defense-in-depth; privileged worker claim surface remains security-critical |
| Public/API contracts | YELLOW | HTTP exists, but capability identifiers drifted from normative public names |
| Python ↔ PostgreSQL boundary | YELLOW | correctness is strong, but large DB adapters currently contain application-like transaction scripts |
| Reliability | YELLOW | leases/fencing/bounded retries are designed; worker/runtime topology remains incomplete |
| Observability | ORANGE | architecture promises it, but `platform/observability` is still effectively scaffolding |
| Security | YELLOW | tenant/RLS model is thoughtful; capability-vs-permission semantics require clarification |
| Agent readiness | YELLOW | machine-readable errors and capability-oriented API are good; no canonical executable capability manifest yet |
| Evolutionary architecture | YELLOW/GREEN | no production Alembic baseline is an advantage; freeze must stay blocked until proof gates pass |

## 2. Reconstructed system

### Actors

- tenant Organization;
- authenticated Principal: human, service, agent, integration, provider, worker;
- Party/subject/recipient;
- staff/operator;
- external applications/forms;
- AI agent/tool caller;
- n8n/integration worker;
- communication provider;
- database/runtime operator.

### Four application semantics

```text
Query           = read current/advisory state
Command         = execute an immediate semantic authoritative mutation
Request         = create durable new business demand requiring later processing
ScheduledAction = durable future execution mechanics
```

Transport does not change semantic type.

### Baseline business owners

```text
tenancy        identity + authority facts
catalog        operational/catalog configuration
requests       durable new demand
booking        local reservation + capacity truth
queue          live FIFO queue + future standby coordination
communications durable communication/reminder intent and delivery evidence
```

`platform` remains technical mechanics only.

## 3. Critical findings

### P0 — schema freeze is not justified yet

**Problem**

The SQL candidate already persists `waitlist_entries`, `slot_opportunities` and `slot_offers`, while the current Python `queue` module implements ServiceQueue only. There is no corresponding waitlist vertical in `src/request_engine/modules/queue`.

**Why it matters**

`SlotOpportunity` is not a cheap table. It is a coordination/serialization concept whose existence is justified by duplicate release events, sequential candidate offers and cross-module atomicity with booking Holds. Freezing it before exercising the complete vertical would turn an unproven coordination hypothesis into migration debt.

**Failure scenario**

We discover during implementation that released-capacity recovery needs a materially different coordination identity, broadcast policy, no-hold mode, or ownership split. A production baseline would then require data/API/event migration for a concept that never earned stability.

**Decision**

Keep the SQL candidate experimental. Do **not** create `0001_initial` until waitlist join → opportunity → offer → accept/decline/expire is implemented and its critical races run against PostgreSQL.

### P1 — public capability identity drifted into implementation identity

**Problem**

Normative contracts use stable capability names such as:

```text
appointments.find_slots
appointments.book
appointments.cancel
appointments.reschedule
```

The HTTP/DB implementation used internal strings such as:

```text
booking.find_slots
booking.book_appointment
booking.cancel_reservation
booking.reschedule_reservation
```

Authorization and idempotency therefore risk depending on implementation naming rather than the public semantic contract.

**Why it matters**

Capability identity is a one-way-ish contract. It can appear in permissions, idempotency records, audit records, SDK/tool schemas and agent configuration. A refactor from `booking.book_appointment` to another internal handler name must not change retry/authorization semantics.

**Decision**

Stable public capability IDs are now defined by the owning module contract and must be consumed at transport/application connection surfaces. Internal handler/class/database names remain free to change.

**Remaining work before baseline**

Existing persistence code still uses some internal command strings for idempotency/audit. These must be deliberately classified as either stable capability identity or a separate internal operation identity; the two may not remain accidentally conflated.

### P1 — capability and permission are currently conflated

**Problem**

`ActorContext.capabilities` is used as an authorization set. Some values are public executable capabilities (`queue.join`), while others (`queue.read`) behave like permission scopes rather than public capability identities.

**Why it matters**

A capability catalog answers “what operation exists?”. Authorization answers “may this Principal execute/read it now?”. Treating these as one vocabulary makes capability discovery ambiguous and encourages over-broad permissions.

**Decision**

Architecture will distinguish:

```text
capability_id        stable operation identity
permission_required  authorization requirement
```

They may intentionally be equal for simple V1 cases, but equality is a choice, not a definition.

### P1 — transaction ownership terminology does not match the Python shape

**Problem**

Docs say the application layer owns orchestration and DB adapters implement persistence ports. In actual booking/request code, application command functions are deliberately thin while PostgreSQL adapter classes contain the full transactional script: idempotency, load/plan, lock, validation, writes, audit and outbox.

**Why it matters**

Calling this merely a “repository adapter” hides where the transaction protocol really lives. Moving all code upward mechanically would be worse: it would require leaking `AsyncSession`, inventing a broad UnitOfWork facade, or splitting a race-sensitive protocol across shallow layers.

**Decision**

Do **not** refactor for layering aesthetics. Treat these classes explicitly as **deep transactional executors/adapters**: a module-owned implementation of one semantic command protocol whose data-centric steps must stay close to one PostgreSQL transaction. Pure policy/domain calculations remain outside. External I/O remains forbidden inside.

A future split is justified only when application policy can move outward without exposing transaction mechanics or duplicating lock/revalidation logic.

### P1 — cross-module database knowledge needs a rule, not denial

**Problem**

A modular monolith sharing one relational database inevitably has cross-module FK relationships and some atomic commands spanning multiple owners. Python import rules alone do not define the `module |-| PostgreSQL |-| module` surface.

Example: a Reservation may correlate to a Request through a tenant-safe FK even though booking must not import request internals.

**Decision**

Distinguish:

1. **relational integrity references** — allowed in SQL when they preserve a documented invariant/correlation;
2. **semantic reads/commands across modules** — must use supported module contracts;
3. **direct mutation of another module's authoritative rows** — forbidden except an explicitly documented shared atomic protocol with ownership and lock order.

Do not create Python service calls merely to replace an FK existence check when the database constraint is the stronger and simpler invariant.

### P1 — observability is promised before it exists

**Problem**

`platform/observability` is effectively empty while the architecture treats observability as a baseline production concern.

**Decision**

Do not build a metrics framework prematurely, but schema freeze/production readiness must require minimum structured logs/traces/metrics for command latency, DB/lock latency, retries, outbox/scheduler lag, dead work and provider attempts. Audit remains separate.

### P2 — deferred source packages are transitional scaffolding

`delivery`, `payments` and `dispatch` contain little/no runtime implementation but remain physically present. This contradicts the general “do not create empty architecture folders” rule, although the transition docs intentionally retained them as reminders of V2 knowledge.

**Decision**

Do not let baseline code import them. After the V3 review lands, prefer preserving deferred knowledge in docs/ADRs and removing empty runtime scaffolding unless a near-term vertical reactivates it. This is cheap and reversible; it is cleanup, not a blocker.

### P2 — communications has three temporal nouns that must not collapse

```text
ReminderPlan       recurring business intent
CommunicationTask one durable intent to communicate
ScheduledAction    technical future execution lease/retry record
```

`not_before` on a CommunicationTask is an eligibility guard, not a second scheduler. `ScheduledAction.execute_at` is execution mechanics. `ReminderPlan` generates occurrences. Keep this semantic separation explicit and test it.

## 4. Boundary-surface model

Every important vertical must identify both boxes and `|-|` contracts:

```text
Transport
   |
  |-| authentication + capability/permission
   |
Application semantic operation
   |
  |-| transaction executor contract
   |
Domain policy + PostgreSQL adapter
   |
  |-| SQL/constraint/lock protocol
   |
PostgreSQL authoritative state
   |
  |-| outbox/scheduled consequence
   |
Worker/provider
```

Horizontal examples:

```text
queue |-| booking
booking |-| communications
requests |-| n8n
communications |-| scheduling
```

For every new surface record owner, input/output, trust context, transaction boundary, idempotency, failure/retry semantics, versioning and forbidden knowledge.

## 5. Proof verticals required before freeze

### Proven enough to continue hardening

- structured business/catalog query;
- direct booking;
- cancel/reschedule/hold booking flows;
- FIFO ServiceQueue;
- durable Requests;
- communications/reminders/provider delivery.

### Still required

- complete Waitlist/SlotOpportunity/SlotOffer recovery vertical;
- cross-module atomic AcceptSlotOffer proof;
- complete provider/webhook inbound semantic-command proof where provider responses affect another domain;
- production worker composition/recovery surface;
- minimum observability proof.

## 6. Schema-freeze gates

`0001_initial` remains prohibited until all are true:

- [ ] every baseline persisted coordination concept has a real vertical owner;
- [ ] every P0/P1 semantic contradiction is resolved;
- [ ] public capability identifiers are stable and machine-readable;
- [ ] capability identity vs permission semantics are explicit;
- [ ] all critical tenant relationships are DB-provably same-Organization;
- [ ] lock graph has no contradictory acquisition order;
- [ ] booking exclusive/units races pass on real PostgreSQL;
- [ ] waitlist opportunity/offer acceptance races pass on real PostgreSQL;
- [ ] queue `CallNext` races pass on real PostgreSQL;
- [ ] ScheduledAction/outbox stale-worker fencing is proven;
- [ ] cross-tenant claim primitive has explicit threat-model tests;
- [ ] no external I/O occurs under authoritative DB locks;
- [ ] minimum production observability exists;
- [ ] elimination pass has removed or explicitly deferred speculative runtime concepts;
- [ ] a final adversarial pass fails to find a materially simpler design with the same guarantees.

## 7. Evolution rule

Classify changes before implementation:

```text
Reversible              local layout/refactor/internal helper
Expensive but reversible aggregate/module/schema ownership
One-way-ish              public IDs, capability semantics, event schemas,
                         tenant identity, temporal/audit/idempotency semantics
```

Delay one-way-ish decisions until evidence exists. The absence of a production Alembic baseline is currently an architectural asset; do not spend it merely to make the repository feel finished.
