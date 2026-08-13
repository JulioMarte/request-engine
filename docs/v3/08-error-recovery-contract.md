# V3 HTTP error and recovery contract

Status: normative for the pre-baseline V3 public HTTP surface.

## Purpose

Request Engine errors are machine-facing operational contracts. Human-readable text is useful for diagnostics, but agents, SDKs and automations must not infer recovery behavior from prose.

Every public HTTP failure uses the same envelope:

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "the aggregate changed since it was read",
    "retryable": false,
    "resolution": "refresh_and_retry",
    "details": {}
  }
}
```

FastAPI/Pydantic validation errors, authentication failures, capability denials, module domain errors, residual HTTP exceptions and database-integrity translation all converge on this envelope.

## Closed recovery vocabulary

`resolution` is one of:

```text
none
retry_same_request
refresh_and_retry
choose_alternative
fix_request
reauthenticate
request_authority
operator_intervention
```

The value describes the next semantic action, not whether an HTTP client library should automatically retry.

### `retry_same_request`

The same semantic request may be retried without first changing business input. This should be reserved for explicitly transient conditions; the current baseline does not assign it broadly.

### `refresh_and_retry`

The caller's view of authoritative state may be stale. Re-read the aggregate/context, reconsider whether the requested mutation is still valid, then issue a new command using the refreshed revision/idempotency contract.

Typical example: `revision_conflict`.

### `choose_alternative`

The requested option/state is no longer usable, but another business option may be valid.

Typical example: `appointment_unavailable`.

### `fix_request`

The operation input or target is invalid and should be corrected before another attempt.

Typical examples: `validation_failed`, malformed target identifiers, unsupported caller input.

### `reauthenticate`

The caller must establish a valid authenticated Principal context.

Typical example: `authentication_required`.

### `request_authority`

The Principal is authenticated but lacks either the required technical capability or Party authority. The caller must obtain an appropriate grant/Representation or use an explicitly permitted operator path; blindly retrying is incorrect.

Typical examples: `capability_required`, `party_authority_required`.

### `operator_intervention`

The problem is configuration/invariant/runtime administration, not something an end-user or agent should repair by changing ordinary business input.

Typical examples: `booking_configuration_error`, unsupported configured Request schema, unexpected database integrity failure.

### `none`

No generally safe automatic recovery action is defined.

## `retryable` versus `resolution`

`retryable` and `resolution` answer different questions.

`retryable=true` means the same semantic request can reasonably succeed later without a business decision/input change. `resolution` tells the caller what action class is required.

A stale revision therefore uses:

```text
retryable = false
resolution = refresh_and_retry
```

because replaying the same stale command is intentionally rejected; the caller must refresh state and make a new concurrency decision.

## Party authority normalization

All caller-facing Party-authority failures use:

```text
code = party_authority_required
resolution = request_authority
```

Details preserve the semantic anchor:

```json
{
  "party_id": "...",
  "authority_anchor": "subject | requester",
  "scope_key": "appointments.manage"
}
```

`party_id` may be `null` for an unattributed Request that is operator-managed only.

Technical capability denial remains a distinct code:

```text
capability_required
```

Authentication, technical permission and Party authority remain separate layers.

## Validation boundary

FastAPI's default `{"detail": [...]}` validation response is not part of the V3 contract.

`RequestValidationError` is translated to:

```text
422 validation_failed
resolution = fix_request
```

with normalized field entries containing only stable location/message/type facts. Provider/library-specific exception objects are not exposed.

## Residual HTTP exceptions

Module surfaces should prefer semantic domain errors where the module owns a useful machine-readable distinction. A process-level HTTPException handler remains as a safety net so transport/framework errors cannot escape the common envelope.

The fallback does not replace module domain modeling. For example, a missing Reservation uses `reservation_not_found`; an unmodeled transport-level 404 may use generic `not_found`.

## Compatibility rule

V3 is pre-baseline. New code must use the canonical error codes and recovery vocabulary. Agents and SDKs should branch on `code` and `resolution`, never on English `message` text.
