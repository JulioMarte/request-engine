# V3 public API, capability, and error contract freeze

Status: Phase 6 G16 implementation inventory. G16 remains `PARTIAL` until this branch passes canonical exact-head CI and its candidate artifact is inspected.

Base for this closure: `development@5cfa0858eabd888e9e65092b480660122d9b280d`.

This freeze defines the externally reviewable V3 contract that must stop drifting before performance/index freeze and `0001_initial` equivalence. It does not make V3 release-ready and does not prevent a future versioned API from changing these contracts deliberately.

## 1. HTTP operation surface

The V3 public HTTP surface is exactly the 24 operations in `tests/e2e/http_surface.py`.

`tests/architecture/test_v3_public_contract_freeze.py` carries an independent literal baseline for each operation's:

- stable logical operation name;
- HTTP method;
- path template;
- canonical capability key, or the one explicit discovery exception `capabilities.list`.

`tests/e2e/test_public_surface_contract.py` requires runtime FastAPI OpenAPI to contain exactly the classified `/v1/` method/path set. A new route, removed route, method change, path change, or capability reassignment therefore requires an intentional contract-baseline change.

## 2. OpenAPI machine metadata

For every capability-backed operation, OpenAPI must expose metadata generated from the canonical capability definition and verified at runtime:

- `operationId`;
- `x-request-engine-capability`;
- `x-request-engine-schema-version`;
- `x-request-engine-idempotency`;
- `x-request-engine-expected-revision`;
- `x-request-engine-exposure`;
- `x-request-engine-party-scope` when present;
- `x-request-engine-override-capability` when present.

The current V3 capability schema version is `1` for every canonical capability. A semantic input/output contract change that cannot remain compatible with schema version 1 must not silently mutate that version; it requires an explicit versioning decision.

The existing HTTP contract tests also require every POST operation to advertise a required `Idempotency-Key` and every classified GET operation to remain non-mutating and non-idempotent.

## 3. Capability registry freeze

The canonical registry currently contains 34 capability definitions. The architecture freeze records, in order, each definition's:

- canonical key;
- exposure (`public`, `operator`, `internal`);
- kind (`query`, `command`);
- idempotency policy;
- revision policy;
- Party authority scope;
- operator override capability;
- accepted legacy aliases;
- runtime availability.

Legacy aliases remain accepted authorization inputs only where already declared. They do not become new canonical capability keys and do not create additional public OpenAPI operations.

Operator capabilities may appear on explicitly operator-facing runtime operations such as `queue.call_next`; internal capabilities remain excluded from OpenAPI. Capabilities marked `runtime_available=False` are authorization grants/overrides, not directly invocable HTTP operations.

## 4. Public error contract freeze

All installed HTTP error handlers are required to use the common `ErrorEnvelope` / `ErrorBody` shape. The Phase 6 freeze inventories literal public error codes emitted by:

- shared HTTP entrypoint handlers;
- Booking;
- Queue/Waitlist;
- Communications/Reminders;
- Requests.

The two Request result-state conflict codes produced through the shared `_conflict()` helper are frozen explicitly as well.

The frozen contract is the machine code and recovery classification, not arbitrary English prose. Error messages may be clarified without becoming a new machine contract only when code, HTTP status semantics, retryability/resolution behavior, security opacity, and required structured details remain compatible.

Cross-tenant and authority failures must continue to preserve the opaque/error-normalization rules already proven by G06; G16 does not weaken those security contracts.

## 5. What counts as contract drift

Any of the following requires an explicit V3 contract review and a deliberate update to the freeze baseline:

1. adding/removing/renaming a `/v1/` operation;
2. changing HTTP method or path template;
3. changing operation capability assignment;
4. changing capability exposure/kind/idempotency/revision/Party authority/override/runtime availability;
5. adding/removing/reassigning a legacy capability alias;
6. changing OpenAPI machine metadata for a capability-backed operation;
7. adding/removing/renaming a public machine error code;
8. changing a public error from retryable/recoverable semantics to incompatible terminal semantics or vice versa;
9. changing request/response semantics in a way incompatible with capability schema version 1.

A deliberate future V4 or other versioned surface may change these contracts without pretending to be V3-compatible.

## 6. Release evidence required for G16 PASS

G16 may move to `PASS` only after one exact branch head proves:

- the literal 24-operation baseline matches the E2E registry;
- the literal 34-capability baseline matches the production capability registry;
- the installed public error-code inventory matches the frozen baseline;
- runtime OpenAPI contains exactly the classified `/v1/` surface;
- runtime OpenAPI metadata converges with the frozen capability definitions;
- existing authentication, tenant isolation, authority, idempotency, revision and error-envelope tests remain green;
- canonical CI produces a `VALID`, clean-tree candidate evidence bundle bound to the exact branch head.

Promotion of G16 does not change global `release_status: NOT_READY`. G05, G15, G17-G20 and any remaining incomplete race/invariant work retain their current status.
