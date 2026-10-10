# Requests module

> **Current Requests business owner.** Historical V3 labels below describe provenance.

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

## Implemented lifecycle

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

Every demand lifecycle write uses one tenant-scoped PostgreSQL transaction for authoritative state, audit, outbox facts and idempotency completion. A successful replay returns the persisted deterministic result rather than executing the command again.

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

## Definition administration and operator inbox

The module now owns API-first definition setup; runtime demand does not require SQL
fixtures or a second admin-only execution path. `0018_request_definition_admin`
adds the mutable definition revision without changing immutable version history.

| HTTP operation | Stable operationId | Capability |
| --- | --- | --- |
| POST `/v1/request-definitions` | `request_definition_create` | `requests.create_definition` |
| POST `/v1/request-definitions/{id}/versions` | `request_definition_version_publish` | `requests.publish_definition_version` |
| POST `/v1/request-definitions/{id}:set-active` | `request_definition_set_active` | `requests.set_definition_active` |
| GET `/v1/request-definitions` | `request_definitions_list` | `requests.read_definitions` |
| GET `/v1/request-definitions/{id}?version=1` | `request_definition_read` | `requests.read_definitions` |
| GET `/v1/requests?status=open` | `requests_list_inbox` | `requests.read_inbox` |

The first three are semantic Commands. They require an explicit capability,
`Idempotency-Key` and current exact-scope Representation
`operations.manage_profile` for `authority_party_id`, checked and locked inside
the same tenant transaction as the definition write. They
use this existing organizational-configuration authority scope. It is provisioned
by `/v1/organization/bootstrap-operational-authority`; Requests does not add an
ungrantable private scope or pretend these operator commands are public customer
Party operations. Their owning capability remains Requests-specific.
Publishing/activation also
require `expected_revision`. The definition row serializes changes; conflicting
revisions return 409 with `current_revision`, not a silent last-write-wins result.
Keys are stable URL-safe ASCII: first character alphanumeric, then alphanumeric,
dot, underscore or hyphen, at most 160 characters. Invalid keys are rejected, not
silently renamed or case-folded; existing legacy keys are not rewritten.
Creation starts active at version/revision 1. Publishing appends a version and
increments revision; setting active increments revision but preserves versions.
Commands append audit facts and deterministic idempotency receipts atomically.
They do not emit Request lifecycle events because definition configuration is
not new demand. No provider network calls occur in the transaction.

Schemas remain the supported subset above, with a combined UTF-8 encoded limit
of 65536 bytes, maximum nesting depth 64 and 4096 nodes. Unsupported caller schemas are
422 input errors, not 500 runtime
configuration errors. Referencing absent/foreign definitions returns 404. Current
authority is required even for configuration-command receipt replay.

Queries have explicit capability checks and `Cache-Control: no-store`. Collections
return `{items, next_cursor}` with `limit` 1–200 (default 50), deterministic keyset
ordering, and cursors bound to tenant/collection/filters. Unknown filters and
invalid or mismatched cursors are 422. The inbox is an operator-wide tenant
metadata view, not a requester-party read: it deliberately excludes payload and
result. Individual reads still enforce their original requester authority rules.
Schema discovery can read an inactive historical version to support receipts.
Each inbox item exposes `definition_id`, `request_key` and `definition_version`
alongside its original `definition_version_id`. To reconstruct its input contract,
read `/v1/request-definitions/{definition_id}?version={definition_version}`;
never substitute the latest version after publication. Both joins used to supply
this metadata include the tenant identity. Owner OpenAPI responses describe the
actual `ErrorEnvelope` for validation, missing resources and command conflicts,
only where each status is possible; collection reads do not promise command conflicts.
These new capabilities are **not implicitly granted** by older staff policies.
Fresh native roots receive the explicitly reviewed v6 manifest after migration
`0021_tenant_controller_v6`. Older controllers cannot obtain missing grants through
the current ceiling-bound staff or policy-upgrade APIs; existing-root adoption is
pending governance in proposed ADR 0016, not an implemented workaround.

### Explicit pre-production submission adaptation

HTTP submission now requires positive `definition_version`. Clients first discover
the version/schema, then submit using the returned `request_key` and version at
the existing `/v1/requests/definitions/{request_key}/submit` business entry point.
This CONTROLLED contract change rejects omitted versions with 422; it prevents
the same idempotency key from resolving to a different version after publication.
Exact-version resolution does not hide an inactive definition before replay.
Fresh submissions acquire a shared definition lock and reject inactive definitions
with 409; a completed identical receipt returns its original Request even after
publication or deactivation. A successful replay does not create demand, outbox
or another receipt. The activation command cannot race past the shared lock.

No generic definition CRUD, arbitrary schema dialect, payload-bearing bulk inbox,
definition deletion, or automatic capability-policy upgrade is claimed here.
### Bounded schema-pattern adaptation (pre-production)

The `pattern` keyword now uses the explicitly supported
[RE2 syntax](https://github.com/google/re2/wiki/Syntax), not Python's backtracking
engine. This is a CONTROLLED pre-production contract adaptation: backreferences,
lookaround, Python-only flags/escapes (including `\\Z`) and other unsupported RE2
constructs are rejected with `RequestPayloadInvalid` (422 at publication).
Use RE2 `\\z` for an absolute end anchor. Search semantics remain substring search,
not full match; use explicit anchors when required. RE2 shorthand character
classes such as `\\w`/`\\d` are ASCII; use explicit Unicode properties such as
`\\p{L}` when a Unicode category is intended. No normalization or silent pattern
rewriting occurs. Publication rejects unsupported patterns before its transaction;
already stored incompatible schemas fail closed on fresh demand/result validation
with `UnsupportedRequestSchema` (`request_definition_invalid`, 500,
`operator_intervention`, not a caller-fixable payload error). Do not blindly retry;
an authorized operator must publish a supported schema version and the client
must deliberately select that version for new demand.
Existing schema rows and successful command receipts are not rewritten.

Each expression is limited to 2048 UTF-8 bytes. Each validation admits at most
32 distinct expressions and 16384 aggregate expression-source bytes. Every
compiled expression receives an explicit 1 MiB RE2 memory budget and suppresses
compiler stderr; compiler exhaustion is a typed input failure, not acceptance.
Schemas are admitted once per document validation, not recursively recompiled
for each array item. RE2's parser/compiler/matcher use bounded memory and avoid
recursive/backtracking execution; this protects compilation as well as matching.
See the [upstream safety contract](https://github.com/google/re2#readme).

Both document and schema trees are bounded before recursive traversal, including
legacy schemas: depth 64, 4096 nodes, and 1 MiB aggregate UTF-8 string/key bytes.
Invalid Unicode surrogates are typed input failures. These structural and aggregate
limits bound repeated matching work; they are not a wall-clock service-level
guarantee, HTTP rate limit, or full JSON Schema implementation. The existing
publication-specific combined encoded schema limit of 65536 bytes still applies.
`uniqueItems` uses type-tagged structural identities in a set, rather than an
all-pairs comparison. JSON numeric equivalence (`1` equals `1.0`), boolean/number
distinction, unordered object keys and ordered arrays remain explicit semantics.
This does not claim every supported schema keyword has linear worst-case cost.

Evidence: `tests/modules/requests/test_schema_pattern_safety.py` exercises the real
owner validator in a watchdog-isolated process with an exponential-backtracking
attack, plus admission, aggregate budgets, legacy rejection, Unicode and depth
cases. It proves owner CPU/input safety, not authenticated HTTP or PostgreSQL
rollback. Canonical lane: Python quality/module tests. No migration is needed.

### Decision: no baseline `OfferingSelection` / `RequestItem` abstraction

Generic Request payload can reference Offering public IDs through its validated schema when needed. Introduce relational Request items only after a concrete Request capability requires independent item identity/cardinality/invariants.

`OutcomeScope` and a universal Workflow abstraction are not V3 baseline dependencies. Introduce an outcome/execution abstraction only after a concrete production capability demonstrates independent lifecycle/concurrency requirements.
