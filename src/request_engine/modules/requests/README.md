# Requests module

> **V3 baseline module.**

Owns `Request` as a durable envelope of **new business demand that requires later processing**.

Typical Request types:

```text
request_quote
request_callback
request_service
submit_intake
```

Cancel/reschedule/attendance/queue mutations are semantic Commands owned by their domains by default; they are not new Requests merely because they originated in chat, voice or a form.

Owns:

```text
Request
RequestType
RequestParticipant
ExternalCorrelation
OfferingSelection / RequestItem when required
IntakeDefinition
IntakeSubmission
Request result/status semantics for extension workflows
```

Initial commands/queries include:

```text
CreateRequest
SubmitIntake
RecordRequestResult
CompleteRequest
CancelRequest
GetRequestStatus
```

Generic intake may use a versioned JSONB payload at the ingestion boundary. That does not make arbitrary JSON the authoritative model for native business domains.

n8n/provider workflows consume outbox events and return through authenticated, tenant-bound, idempotent semantic commands. They may not directly mutate Request Engine persistence or call a generic `set_status` endpoint.

`OutcomeScope` and a universal Workflow abstraction are not V3 baseline dependencies. Introduce an outcome/execution abstraction only after a concrete production capability demonstrates independent lifecycle/concurrency requirements.
