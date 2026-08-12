# Communications module

> **V3 baseline module.**

Owns the durable business intent and outcome of **transactional communications**. It does not own provider transport infrastructure and it is not a marketing automation platform.

Core concepts:

```text
CommunicationTask
CommunicationDelivery
CommunicationTemplate / TemplateRef
CommunicationPreference
ContactEndpoint reference/contract
ReminderPlan
ReminderAcknowledgement when required
```

Typical purposes:

```text
appointment_confirmation
appointment_reminder
attendance_confirmation_request
reservation_changed
reservation_cancelled
queue_turn_approaching
slot_offer_available
request_completed
medication_reminder
```

The originating business transaction commits before provider I/O occurs. Communications are derived/created after authoritative facts are durable, then scheduled/claimed and delivered through adapters such as n8n, WhatsApp, SMS, email or voice providers.

`ScheduledAction` lease/retry/fencing mechanics belong to `platform/scheduling`; this module owns why a communication/reminder exists, its policy, delivery semantics and business acknowledgement.

## Baseline execution semantics

- `CommunicationTask` is durable intent. Creating a new task and its first `dispatch_task` ScheduledAction is one tenant-scoped transaction.
- Idempotency-key replay and domain `dedupe_key` are distinct. Reusing a dedupe key is legal only when it identifies the exact same communication intent; differing payload/recipient/template is a conflict.
- Provider/network I/O never occurs while the authoritative task transaction is open.
- A provider delivery is at-least-once from Request Engine's perspective; provider idempotency/correlation must prevent duplicate external effects where supported.
- Exactly-once external delivery is not promised. Ambiguous provider outcomes require query/reconciliation rather than blind resend.

## ReminderPlan baseline

The initial recurrence type is deliberately narrow:

```json
{
  "type": "daily_times",
  "times": ["08:00:00", "20:00:00"],
  "max_lateness_minutes": 60
}
```

- Times are local wall-clock values interpreted in the plan's explicit IANA timezone.
- A nonexistent DST wall-clock time is skipped for that date.
- An ambiguous DST fold emits exactly once at the first chronological UTC instant.
- `max_lateness_minutes` prevents catch-up storms: if an occurrence is too old when a worker handles it, no CommunicationTask is created for that occurrence and the recurrence advances to the next future occurrence.
- Materializing one occurrence and scheduling the next occurrence happen in the same tenant transaction.
- The scheduler lease is completed only after that transaction commits. If the worker crashes before lease completion, deterministic dedupe keys make replay safe.
- Reprocessing an older leased occurrence first checks whether a later occurrence was already scheduled, so a delayed replay does not fork the recurrence chain.
- Cancelling a ReminderPlan cancels its pending future reminder ScheduledActions. A concurrently leased occurrence rechecks plan status under the ReminderPlan lock and becomes a no-op if the plan is no longer active.

Reservation state and attendance consequences remain owned by booking. The communications module may ingest a provider response and invoke booking's supported command contract; it must not mutate booking state directly.

Medication reminders execute an already-authorized ReminderPlan. This module does not infer dosage, alter treatment, or make clinical decisions.
