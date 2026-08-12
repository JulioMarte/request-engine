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

Reservation state and attendance consequences remain owned by booking. The communications module may ingest a provider response and invoke booking's supported command contract; it must not mutate booking state directly.

Medication reminders execute an already-authorized ReminderPlan. This module does not infer dosage, alter treatment, or make clinical decisions.

Exactly-once external delivery is not promised. Implement duplicate-safe provider correlation, bounded retries, dead-letter state and reconciliation where provider semantics require them.
