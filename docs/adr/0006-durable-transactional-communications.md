# 0006 — Durable transactional communications and scheduling
Status: Accepted

## Context

The initial product use cases require communications that are consequences of authoritative business state: appointment confirmations, reminders, reservation changes, attendance confirmation requests, queue notifications, waitlist slot offers and recurring reminders such as medication reminders.

These actions may happen seconds, hours or days after the originating transaction. Provider calls can fail, time out, be duplicated, rate limited or return callbacks later. n8n, WhatsApp providers, SMS, email and voice systems must remain replaceable integration choices rather than owners of reservation or reminder truth.

## Decision

Request Engine owns the **durable intent and state of transactional communications**, while external systems own transport delivery.

Business transactions never perform external communication I/O before commit. They persist authoritative state and emit durable facts/outbox records. Communications are created/claimed/delivered after commit.

The architecture distinguishes:

- `CommunicationTask` — why/who/what/when should be communicated;
- `CommunicationDelivery` — a concrete provider/channel delivery attempt/result;
- `ScheduledAction` — durable future technical work with lease/fencing/retry semantics;
- `ReminderPlan` — recurring business intent that may generate scheduled actions;
- business policies — decide which communications are created and consequences of responses.

Provider adapters may initially delegate delivery/orchestration to n8n. n8n callbacks must invoke authenticated, idempotent semantic commands; they may not write Request Engine state directly.

Scheduled workers require bounded retries, dead-letter state, manual replay, leases/fencing and observable scheduling lag. External I/O occurs outside the DB transaction used to claim work.

Reservation confirmation and customer attendance confirmation are separate states. A lack of attendance response does not cancel capacity unless an explicit business policy authorizes that consequence.

ServiceQueue and Waitlist are separate concepts. Waitlist slot offers may use short CapacityHolds only when the business policy requires temporary exclusivity.

## Consequences

Positive:

- communications survive process restarts and provider outages;
- channels/providers can be replaced without changing booking logic;
- duplicate delivery/callback behavior becomes testable and auditable;
- reminders are not mis-modeled as Requests;
- voice agents can call semantic booking/attendance tools instead of owning workflow state;
- n8n remains useful without becoming a transactional authority.

Costs/trade-offs:

- additional worker/scheduler state is required;
- exactly-once external delivery cannot be promised; idempotency, reconciliation and duplicate-safe handling are required;
- template, preference and endpoint ownership must remain intentionally narrow to avoid growing into CRM/marketing automation;
- provider-specific compliance constraints remain adapter/policy concerns and require explicit implementation per channel/jurisdiction.

## Rejected alternatives

### Call providers synchronously inside booking transactions

Rejected because network I/O would extend locks, create ambiguous commit/provider outcomes and couple local correctness to external availability.

### Let n8n own reminder schedules and business state

Rejected because critical schedules, cancellations, idempotency and audit would become split-brain with Request Engine.

### Model every reminder as a Request

Rejected because reminders are derived or recurring future actions, not new customer business demand.

### Build a marketing automation platform

Rejected because transactional operational communication is sufficient for the current product thesis and a broader campaign/journey system would repeat the universal-platform overreach.
