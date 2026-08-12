# Requests module

> **V3 baseline module.**

Owns `Request` as a durable envelope of **new business demand that requires later processing**.

Typical definitions:

```text
request_quote
request_callback
request_service
website_contact
```

Cancel/reschedule/attendance/queue mutations are semantic Commands owned by their domains by default; they are not new Requests merely because they originated in chat, voice or a form.

Owns:

```text
RequestDefinition
RequestDefinitionVersion
Request
RequestParticipant
ExternalCorrelation
```

`RequestDefinitionVersion` supplies the exact versioned generic input contract and optional result contract. A validated Request payload may be stored as JSONB at this extensibility boundary because it represents demand that has not yet earned its own native bounded context.

### Decision: no separate `IntakeDefinition` / `IntakeSubmission` baseline

A form submission that represents new business demand uses the same `RequestDefinitionVersion → Request` contract. This avoids creating a parallel intake lifecycle that immediately converts into Request.

Draft forms, partial submissions or ingestion records can become a separate capability later if product evidence requires lifecycle independent from Request.

### Decision: no baseline `OfferingSelection` / `RequestItem` abstraction

Generic Request payload can reference Offering public IDs through its validated schema when needed. Introduce relational Request items only after a concrete Request capability requires independent item identity/cardinality/invariants.

Initial commands/queries:

```text
CreateRequest / requests.submit
RecordRequestResult
CompleteRequest
CancelRequest
GetRequestStatus
```

n8n/provider workflows consume versioned outbox events and return through authenticated, tenant-bound, idempotent semantic commands. They may not mutate persistence directly or call a generic `set_status` endpoint.

`OutcomeScope` and a universal Workflow abstraction are not V3 baseline dependencies. Introduce an outcome/execution abstraction only after a concrete production capability demonstrates independent lifecycle/concurrency requirements.
