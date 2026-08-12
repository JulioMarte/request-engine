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

## Implemented V3 lifecycle

The authoritative lifecycle is deliberately small:

```text
open -> completed
open -> cancelled
open -> failed
```

Terminal states never reopen. The `Request` row is the lifecycle serialization root: result recording and all terminal commands lock the same Request row before validating current state and optional `expected_revision`.

Implemented semantic surface:

```text
CreateRequest / requests.submit
RecordRequestResult / requests.record_result
CompleteRequest / requests.complete
CancelRequest / requests.cancel
FailRequest / requests.fail
GetRequestStatus
```

Every write uses one tenant-scoped PostgreSQL transaction for authoritative state, audit, outbox facts and idempotency completion. A successful replay returns the persisted deterministic result rather than executing the command again.

`expected_revision` is an optimistic-concurrency contract for callers that need compare-and-set semantics. It supplements rather than replaces row locking.

## Requester Party authority

`requester_party_id` is the caller-facing authority anchor for a Request. It identifies the Party whose demand the Request represents.

The baseline deliberately separates business correlation from authority:

```text
requester_party_id   -> authority anchor
recipient_party_id   -> business recipient only
RequestParticipant   -> business role only
ExternalCorrelation  -> provenance/correlation only
```

`recipient_party_id`, `guardian`, `authorized_contact`, `payer`, or any other `RequestParticipant.role_key` never grant permission by themselves. Authority comes only from an authenticated Principal plus explicit capability and, where required, a current exact-scope `Representation`.

Caller-facing policy:

```text
requests.submit
  + requester_party_id present
  -> current Representation scope requests.submit
     OR explicit requests.party_override

requests.submit
  + requester_party_id absent
  -> allowed as unattributed/anonymous demand

requests.read / requests.cancel
  + requester_party_id present
  -> current Representation scope requests.manage
     OR explicit requests.party_override

requests.read / requests.cancel
  + requester_party_id absent
  -> explicit requests.party_override only
```

`requests.record_result`, `requests.complete`, and `requests.fail` are tenant-side processing capabilities. They operate on the organization's processing of the Request and do not claim to act as the requester, so they do not require requester Representation in the V3 baseline.

Authority for mutations is resolved inside the same authoritative tenant transaction as the Request write. `CancelRequest` first locks the Request serialization root, resolves the current requester authority against PostgreSQL wall-clock truth, then validates lifecycle/revision and writes. Request audit facts record whether authority came from `representation`, `operator`, or an `unattributed` submission path.

The shared PostgreSQL primitive `request_engine.resolve_current_party_authority(...)` owns the definition of a current exact-scope Representation. Requests must not duplicate Representation validity SQL.

## Versioned payload contract

V3 does **not** claim arbitrary/full JSON Schema support. Python implements and tests an explicit JSON-Schema-like subset and rejects every unsupported keyword instead of silently accepting it.

Supported assertion keywords are currently:

```text
type
properties
required
additionalProperties
enum
const
minLength / maxLength
pattern
minimum / maximum
exclusiveMinimum / exclusiveMaximum
minItems / maxItems
uniqueItems
items
minProperties / maxProperties
```

Annotation-only fields currently accepted are:

```text
$schema
$id
title
description
default
examples
```

Input payload is validated against the exact `RequestDefinitionVersion` used by the Request. The stored schema itself is also validated at submission time, so an unsupported or malformed version cannot silently admit new Requests. If a result schema exists, result payload is validated against that same version before it can be recorded or supplied atomically with completion. If a version declares a result schema, completion requires a validated result. If it declares no result schema, arbitrary result payload is rejected.

JSON values are required to be representable as real JSON; non-finite floating-point values such as `NaN` and infinities are rejected before persistence. JSON numeric equality follows JSON Schema expectations for `enum`, `const` and `uniqueItems`, so for example `1` and `1.0` compare as the same JSON number.

## Participants and external correlations

`RequestParticipant` is a business role only; it does not grant authority. Referenced Parties must be active and tenant-local when a Request is created.

`ExternalCorrelation` correlates Request demand with external identities such as a WhatsApp conversation, website form submission, provider event or call. It is not authentication or authorization.

External correlation identity is unique per tenant across:

```text
correlation_kind + provider_key + external_key
```

Creation races cannot rely only on the UNIQUE constraint because no correlation row may exist yet. `CreateRequest` therefore acquires deterministic transaction-scoped advisory locks for requested correlation identities in canonical order, then verifies the correlation rows remain free before insertion. A pre-existing correlation is considered reserved even when its `request_id` is still null; a Request may not steal it.

Idempotency identity and external-correlation identity solve different problems:

- idempotency protects replay of the **same command** by the same principal/capability;
- external correlation prevents two distinct commands from claiming the **same external business occurrence**.

## Durable integration facts

Successful commands append versioned outbox facts in the same authoritative transaction:

```text
request.created.v1
request.result_recorded.v1
request.completed.v1
request.cancelled.v1
request.failed.v1
```

n8n/provider workflows consume these durable facts and return through authenticated, tenant-bound, idempotent semantic commands. They may not mutate Request persistence directly or call a generic `set_status` endpoint.

### Decision: no separate `IntakeDefinition` / `IntakeSubmission` baseline

A form submission that represents new business demand uses the same `RequestDefinitionVersion -> Request` contract. This avoids creating a parallel intake lifecycle that immediately converts into Request.

Draft forms, partial submissions or ingestion records can become a separate capability later if product evidence requires lifecycle independent from Request.

### Decision: no baseline `OfferingSelection` / `RequestItem` abstraction

Generic Request payload can reference Offering public IDs through its validated schema when needed. Introduce relational Request items only after a concrete Request capability requires independent item identity/cardinality/invariants.

`OutcomeScope` and a universal Workflow abstraction are not V3 baseline dependencies. Introduce an outcome/execution abstraction only after a concrete production capability demonstrates independent lifecycle/concurrency requirements.
