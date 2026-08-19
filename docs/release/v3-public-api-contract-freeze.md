# V3 public API, capability, and error contract freeze

Status: **Phase 6 G16 PASS** on the current branch. The rebuilt post-G15 contract freeze passed canonical exact-head CI and its machine-readable artifact is mandatory semantic evidence in the release manifest.

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

`build_v3_evidence_manifest.py` now treats that artifact as mandatory semantic evidence. It requires 24 operations, 34 capabilities, schema version `[1]`, 51 public machine error codes, exact snapshot cardinalities, valid SHA-256 fingerprints, and recomputes the runtime-contract fingerprint from the embedded snapshot before accepting the artifact.

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

## 7. G16 PASS evidence

Canonical CI #1138 (`32205998999`) passed on exact implementation head `824b74836acdf6014e34a98ed931dcf21c07cfa1`: Python quality/architecture, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and the aggregate candidate-and-verticals check all succeeded.

Artifact `v3-candidate-release-proof` `9349299370` (`sha256:b34aa22e91aa8974e62f7ad670e8dc34429835936676f3120c38f873995033f2`) is bound to that head. Its release manifest reports `evidence_status: VALID`, `artifact_set_complete: true`, `missing_artifacts: []`, `validation_errors: []`, a clean working tree and `artifact_validation.public_api_contract.status: PASS`. The public-contract artifact SHA is `83e5e76350c572e8bc879671b8fbf553ca19dff81aaec32cb527054c45111cad`; the contract proof itself reports 24 operations, 34 capabilities, capability schema versions `[1]`, 51 public machine error codes, 24 OpenAPI snapshots and `failures: []`.

The #1138 manifest still records G16 as `PARTIAL` because it predates this registry promotion. Therefore this promotion must itself survive one final canonical exact-head CI. Only that post-promotion artifact can be merge-authoritative for PR #65.

Promotion of G16 does not change global `release_status: NOT_READY`. G17-G20 remain independent release gates, and final promotion to `main` must regenerate this contract evidence on the eventual frozen release candidate.
