# Current operation surface audit

Status: **current migration inventory**, subordinate to `docs/16-canonical-operation-and-tool-projection-pattern.md` and `docs/15-api-design-and-usability-standards.md`.

This document records the Stage B audit of the current HTTP/tool surface after adoption of the canonical owner-operation/tool-projection pattern. It is not a frozen endpoint catalog. The executable HTTP inventory remains under `tests/e2e/http_surface_current.py` and related files.

## 1. Audit question

For every machine-facing operation family, determine:

```text
business owner
resource method vs semantic custom method
operationId identity
capability policy
query vs command
idempotency / revision policy
public / operator / admin / system relevance
agent-tool suitability
migration disposition
```

The goal is not to rename every URL. The goal is to remove duplicate execution architectures and make owner-backed operations the reusable source for UX, SDK and agent projections.

## 2. Disposition vocabulary

```text
CANONICAL_OWNER_OPERATION
    Owner-backed HTTP operation whose semantic execution belongs directly to the owner.

CANONICAL_WITH_PROTOCOL_DEBT
    Correct owner/semantic boundary, but HTTP naming, response/error schema, pagination,
    operationId or capability granularity still needs protocol cleanup.

AGENT_SPECIFIC_ADAPTER
    A real agent-oriented read/admission capability that adds useful reference resolution,
    ambiguity handling or tool-specific composition not represented by one owner HTTP operation.

DUPLICATE_TRANSPORT_WRAPPER
    A second HTTP route that mostly wraps/delegates an already-existing owner command. Retain only
    while compatibility requires it; future tool projection should call the canonical owner operation.

HISTORICAL_TEXT_COMPATIBILITY
    Deterministic text compatibility path. Not the canonical API and not a foundation for new work.

MISSING_OWNER_OPERATION
    Product capability needed by setup/operations, but no canonical owner operation exists yet.
```

## 3. Public/customer operation family

The core public surface in `tests/e2e/http_surface.py` is directionally healthy.

### Catalog reads

Examples:

```text
GET /v1/business
GET /v1/catalog/offerings
GET /v1/catalog/offerings/{offering_key}
```

Disposition: `CANONICAL_WITH_PROTOCOL_DEBT`.

These are owner-backed queries. Tool suitability is public/operator/admin where the underlying publication/tenant policy allows it. They should be projected rather than copied into a future agent gateway.

### Appointment operations

Examples:

```text
GET  /v1/appointments/slots
POST /v1/appointments
GET  /v1/appointments/{reservation_id}
POST /v1/appointments/{reservation_id}/cancel
POST /v1/appointments/{reservation_id}/reschedule
POST /v1/appointments/{reservation_id}/attendance
```

Disposition: `CANONICAL_WITH_PROTOCOL_DEBT`.

The semantic model is correct: booking/cancel/reschedule/attendance are explicit operations rather than generic status writes. Existing `/cancel` and `/reschedule` subpaths may migrate toward one repo-wide custom-method convention only when useful; route spelling is not itself a correctness defect.

Tool suitability:

```text
find slots       public/operator/admin
book             public/operator/admin subject to Party authority
read             public/operator/admin subject to Party authority
cancel           public/operator/admin subject to Party/revision authority
reschedule       public/operator/admin subject to Party/revision authority
attendance       public/operator/admin subject to Party/revision authority
```

### Queue / waitlist operations

Examples:

```text
GET  /v1/queues
POST /v1/queues/{queue_id}/join
GET  /v1/queues/{queue_id}/status
POST /v1/queues/{queue_id}/entries/{queue_entry_id}/leave
POST /v1/queues/{queue_id}/call-next
POST /v1/waitlist
GET  /v1/waitlist/{waitlist_entry_id}
POST /v1/waitlist/{waitlist_entry_id}/leave
```

Disposition: `CANONICAL_WITH_PROTOCOL_DEBT`.

`call-next`, `join`, `leave` are semantic commands and should remain explicit. Audience differs by operation: `call-next` is staff/operator; self join/status/leave may be public under Party authority. The future authorized catalog must derive this from capability/authority policy rather than one broad Queue role.

### Requests and reminders

Disposition: `CANONICAL_WITH_PROTOCOL_DEBT`.

They are real product resources/commands and should remain owner-backed. Agent projection is selective and must preserve Party authority, idempotency and revision behavior.

## 4. Administrative setup / onboarding family

The current onboarding HTTP inventory already follows the target direction better than F6 tooling: setup commands live under their real owners.

Current examples:

```text
POST /v1/organization/bootstrap-operational-authority
POST /v1/catalog/resource-capabilities
POST /v1/catalog/offerings
PUT  /v1/catalog/offerings/{offering_version_id}/booking-policy
POST /v1/booking/resources
POST /v1/queues
PUT  /v1/communications/channel-policies/{purpose}
GET  /v1/onboarding/readiness
```

Disposition by family:

```text
organization/bootstrap authority                CANONICAL_WITH_PROTOCOL_DEBT
Catalog configuration                           CANONICAL_WITH_PROTOCOL_DEBT
Booking supply bootstrap                        CANONICAL_WITH_PROTOCOL_DEBT
Queue configuration                             CANONICAL_WITH_PROTOCOL_DEBT
Communications channel policy                   CANONICAL_WITH_PROTOCOL_DEBT
Onboarding readiness                            CANONICAL_OWNER_OPERATION
```

This is the correct ownership direction. Do **not** move these commands into Onboarding or a generic Admin module.

### Current weakness: capability granularity

Several distinct admin operations share coarse capabilities such as:

```text
catalog.manage
booking.manage_supply
queue.configure
communications.configure
```

That may be acceptable initially, but Stage C must decide whether real staff separation requires finer grants such as location management vs offering management vs schedule management. Do not split capability keys merely to make operation IDs unique; split only when authorization policy genuinely differs.

### Current weakness: trusted authority in request bodies

Some bootstrap probes still carry `authority_party_id` in the request body. Stage C must verify the production route obtains/validates this value from trusted representation/authority semantics and does not allow arbitrary authority injection. The canonical pattern requires tenant/principal identity to come from `ActorContext`; any explicitly selected Party authority must be server-validated before use.

## 5. Operational Copilot structured reads

Current F6 structured reads include:

```text
resources lookup
Offerings lookup
Queues lookup
Location clock
Assignment day-end
Queue intake state
open RecoveryIncident
at-risk Reservations
Recovery proposal read
Discovery publication read
```

Disposition is mixed.

### Lookup/reference-resolution reads

```text
resources lookup
offerings lookup
queues lookup
```

Provisional disposition: `AGENT_SPECIFIC_ADAPTER`.

Reason: these APIs intentionally provide bounded reference resolution and ambiguity semantics for agents. They may remain useful even when canonical owner reads exist, but they must not become alternate business truth. Their long-term contract should be explicitly tool/reference-resolution oriented.

### State reads that closely mirror one owner projection

```text
Location clock
Assignment day-end
Queue intake state
RecoveryIncident state
Recovery proposal read
Discovery publication state
```

Provisional disposition: `DUPLICATE_TRANSPORT_WRAPPER` unless the Stage F audit demonstrates agent-specific value beyond schema reshaping.

Preferred end state:

```text
canonical owner query
      -> HTTP/OpenAPI
      -> authorized tool projection
```

rather than maintaining a second `/operational-copilot/tools/...` read API forever.

### At-risk Reservations

Provisional disposition: `AGENT_SPECIFIC_ADAPTER` or direct Live Capacity projection, pending Stage F.

The deciding question is whether this endpoint performs a meaningful cross-owner/agent-oriented projection or only renames an existing Live Capacity read.

## 6. Operational Copilot structured writes

The current structured write surface contains:

```text
Recovery proposal creation
Recovery execution
Recovery intake control
Recovery day extension
ordinary Queue intake control
ordinary Booking day extension
Discovery publish
Discovery revoke
```

Current implementation applies `operational_copilot.execute` and then the owner capability before delegating.

Disposition: **`DUPLICATE_TRANSPORT_WRAPPER` by default**.

These are not new business operations owned by Copilot. Their owners are:

```text
Recovery proposal/execution/intake/day extension -> operational_recovery
ordinary Queue intake control                    -> queue
ordinary assignment/day extension               -> booking (+ Catalog validation where required)
Discovery publish/revoke                        -> discovery
```

The target architecture is not to preserve a second F6 HTTP command API. It is to expose each canonical owner operation through the authorized tool catalog/MCP projection.

### Compatibility rule

Do not remove these routes until all of the following are true:

1. a canonical owner HTTP/operation contract exists for the same supported action;
2. the operation has stable explicit `operationId` and complete typed schemas;
3. tool projection metadata/catalog can expose it to the same authorized callers;
4. parity tests prove owner-equivalent idempotency, revision, authority and failure semantics;
5. any real consumer of the F6 URL has a migration/deprecation path.

New admin operations MUST NOT be added first under `/operational-copilot/tools`. Implement them in the owner and project them.

## 7. Operational Copilot text surfaces

Current:

```text
POST /v1/operational-copilot/interpret
POST /v1/operational-copilot/execute
```

Disposition: `HISTORICAL_TEXT_COMPATIBILITY`.

They are deterministic bounded adapters and may remain while tests/consumers require them, but they are not the canonical operation API and must not receive new domain authority.

Retirement requires consumer evidence, not aesthetic cleanup.

## 8. Operation identity findings

The current E2E helper contains multiple explicit operation-ID overrides. That is not automatically a defect; it is evidence that capability keys and operation IDs are already distinct concepts.

Stage B rule:

- keep existing operation IDs stable while no collision/ambiguity exists;
- add explicit operation IDs where one capability backs multiple semantic operations;
- do not create artificial capability keys merely to obtain unique operation IDs;
- future tool projections require explicit operation IDs before exposure.

## 9. Highest-priority migration gaps

### B1 — owner metadata coverage

All capability-guarded operations should converge on machine-readable owner metadata. New E2E fitness checks enforce this for the current public surface registered through the canonical helper.

### B2 — eliminate new F6 command duplication

Freeze growth of `/operational-copilot/tools` as a source of new business operations. Existing routes are compatibility/migration surfaces; new commands begin at the owner.

### B3 — classify F6 reads precisely

For each structured read, prove whether it is:

```text
DIRECT_OWNER_PROJECTION
AGENT_REFERENCE_RESOLUTION
CROSS_OWNER_AGENT_PROJECTION
DUPLICATE_SCHEMA_WRAPPER
```

Only the middle two justify long-term gateway-owned implementations.

### B4 — administrative setup completeness

Continue into Stage C by proving every supported business setup journey has owner operations for all required facts, rather than adding more gateway wrappers.

### B5 — authorization granularity

Audit whether coarse `*.manage` capabilities permit realistic receptionist/operator/admin separation. Split policy only where business authority differs.

### B6 — protocol debt

Resolve gradually under doc 15:

- typed response models on remaining admin/operations routes;
- consistent status codes;
- pagination/read-model gaps;
- security metadata;
- error vocabulary;
- route addressing inconsistencies.

These should not block owner/tool architecture unless they make safe projection impossible.

## 10. Stage B conclusion

The current API does **not** need wholesale replacement.

The core public and onboarding setup APIs are directionally compatible with the canonical pattern. The main architectural outlier is F6's second structured command surface: it was a useful bridge proving that agents could operate Request Engine safely, but it should now become migration input for a generic authorized projection system rather than a permanent parallel API family.

The correct next phase is Stage C: administrative setup completeness + authority granularity, while Stage F later consumes this audit to dismantle or preserve individual Copilot adapters based on demonstrated value.
