# V3 public API, capability, and error contract freeze

Status: Phase 6 G16 implementation inventory. G16 remains `PARTIAL` until the rebuilt post-G15 branch passes canonical exact-head CI, emits its machine-readable contract proof, and the release manifest validates that artifact.

Base for this closure: `development@6c86fd4d57e5845428650700249897f6e1ef51f0`, after G15 query-plan/index evidence was integrated.

This freeze defines the externally reviewable V3 contract that must stop drifting before the candidate is frozen and before `0001_initial` is blessed. It does not make V3 release-ready and does not prevent a future versioned API from changing these contracts deliberately.

## 1. HTTP operation surface

The V3 public HTTP surface is exactly the 24 operations in `tests/e2e/http_surface.py`.

`scripts/release/v3_public_api_contract_baseline.py` carries the independent review baseline for each operation's stable logical name, HTTP method, path template, and canonical capability key. `tests/architecture/test_v3_public_contract_freeze.py` compares the runtime registry against that baseline.

`tests/e2e/test_public_surface_contract.py` independently requires FastAPI/OpenAPI to contain exactly the classified `/v1/` method/path set. A new route, removed route, method change, path change, or capability reassignment therefore requires an intentional contract-baseline diff.

## 2. OpenAPI machine metadata

For every capability-backed operation, runtime OpenAPI must expose metadata generated from the canonical capability definition and verified independently:

- `operationId`;
- `x-request-engine-capability`;
- `x-request-engine-schema-version`;
- `x-request-engine-idempotency`;
- `x-request-engine-expected-revision`;
- `x-request-engine-exposure`;
- `x-request-engine-party-scope` when present;
- `x-request-engine-override-capability` when present.

Every current V3 capability remains on schema version `1`. A semantic request/response change incompatible with schema version 1 requires an explicit versioning decision; it must not silently mutate the frozen V3 contract.

## 3. Capability registry freeze

The canonical registry contains 34 capability definitions. The baseline records, in order, each definition's canonical key, exposure, kind, idempotency policy, revision policy, Party authority scope, override capability, legacy aliases, and runtime availability.

Legacy aliases remain accepted authorization inputs only where already declared. They are not new canonical capability keys. Internal capabilities remain excluded from the public HTTP surface. Capabilities marked `runtime_available=False` are grants/overrides rather than directly invocable operations.

## 4. Public error contract freeze

The freeze inventories machine error codes emitted by shared HTTP handlers and the Booking, Queue/Waitlist, Communications/Reminders, and Requests modules. Request result-state conflict codes emitted through the shared helper are frozen explicitly as well.

The machine code and recovery/security semantics are contractual; arbitrary English prose is not. Error text may be clarified only while code, HTTP semantics, retryability/resolution behavior, security opacity, and structured details remain compatible. Cross-tenant and authority failures remain subject to the opaque normalization already proven by G06.

## 5. Machine-readable release proof

`scripts/release/prove_v3_public_api_contract.py` constructs the actual contract from the production capability registry, classified HTTP registry, installed public error handlers, and runtime FastAPI OpenAPI. It compares those values to the reviewed baseline and emits `.phase6/v3-public-api-contract.json` with:

- status and failure list;
- operation/capability/error counts;
- capability schema versions;
- a baseline fingerprint;
- a runtime contract fingerprint;
- the exact operation, capability, error, and OpenAPI metadata snapshot.

G16 is not closed merely because literal tests exist. The canonical candidate job must produce this artifact and `build_v3_evidence_manifest.py` must treat it as mandatory semantic evidence.

## 6. What counts as contract drift

The following require explicit V3 contract review and an intentional baseline update:

1. adding, removing, or renaming a `/v1/` operation;
2. changing its method or path template;
3. changing its capability assignment;
4. changing capability exposure, kind, idempotency, revision, Party authority, override, aliases, runtime availability, or schema version;
5. changing OpenAPI machine metadata for a capability-backed operation;
6. adding, removing, or renaming a public machine error code;
7. changing recovery/terminal/security semantics incompatibly;
8. changing request/response semantics incompatibly with capability schema version 1.

A deliberate future V4 or other versioned surface may change these contracts without pretending to be V3-compatible.

## 7. Evidence required for G16 PASS

G16 may move to `PASS` only when one exact branch head proves all of the following together:

- the 24-operation baseline matches the classified HTTP registry;
- the 34-capability baseline matches the production capability registry;
- the installed public error-code inventory matches the reviewed baseline;
- runtime OpenAPI contains exactly the classified `/v1/` surface;
- runtime OpenAPI metadata matches canonical capability definitions;
- the machine-readable contract artifact is generated and semantically validated by the release manifest;
- existing authentication, tenant isolation, authority, idempotency, revision, and error-envelope tests remain green;
- canonical CI produces a `VALID`, clean-tree candidate evidence bundle bound to that exact head.

Promotion of G16 does not change global `release_status: NOT_READY`. G17-G20 remain independent release gates.
