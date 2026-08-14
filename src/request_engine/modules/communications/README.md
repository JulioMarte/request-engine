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
- A concrete endpoint is resolved and the `CommunicationDelivery(status=attempting)` fact is committed before provider I/O begins.
- Each delivery attempt receives a deterministic provider idempotency key derived from `CommunicationTask + attempt_no`.
- The worker executes three phases: `prepare DB transaction -> provider I/O -> finalize DB transaction`.
- A crashed/leased replay that finds the latest Delivery in `attempting`, `accepted` or `ambiguous` performs provider lookup/reconciliation before any new send.
- A send-side exception is treated conservatively as `ambiguous`; it is never interpreted as proof that the provider did not accept the request.
- `accepted` and `ambiguous` results schedule a fenced `reconcile_delivery` action. Repeated `accepted` lookups may schedule another future reconciliation, but replay first reuses already-scheduled future work.
- `delivered` completes the CommunicationTask.
- A non-retryable provider failure fails the CommunicationTask.
- A retryable provider failure returns the task to `pending` and schedules a **new** future `dispatch_task` keyed by the Delivery that failed. An old/reclaimed lease observes that future retry and cannot bypass its backoff.
- Lookup infrastructure failures retry the lookup action; they do not trigger a send.
- Exactly-once external delivery is not promised. The contract is duplicate-resistant, provider-correlated and reconciliation-first after uncertainty.

The initial `channel_policy` surface is intentionally small:

```json
{
  "channels": ["whatsapp", "sms"],
  "provider_key": "provider-name",
  "retry_after_seconds": 60,
  "reconcile_after_seconds": 300
}
```

`channels` is ordered. `sms` and `voice` resolve against a `phone` ContactPoint; `email` and `whatsapp` resolve against matching endpoint types. An explicit ContactPoint must still match the policy and remain active. Automatic endpoint selection only uses active, verified ContactPoints.

## Reservation-relative communications

Appointment communications are derived from a committed Booking lifecycle snapshot. They are not `ReminderPlan` recurrences.

The initial reservation purposes are:

```text
appointment_confirmation
appointment_reminder
attendance_confirmation_request
```

Their semantic dedupe keys include the Reservation and its scheduled start. A reschedule therefore creates a new generation while pending work from the old start becomes cancelled. Replaying the same Reservation lifecycle event reconciles a desired set and reuses the existing generation instead of cancelling and recreating it.

A cancellation cancels pending Reservation communication intents and their pending dispatch actions. A delivery already in provider reconciliation remains governed by normal delivery reconciliation; Communications does not claim exactly-once external delivery.

Booking owns Reservation and attendance state. Communications may translate an authenticated provider response into Booking's public attendance command contract, but it must never update Booking tables directly.

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

Medication reminders execute an already-authorized ReminderPlan. This module does not infer dosage, alter treatment, or make clinical decisions.
