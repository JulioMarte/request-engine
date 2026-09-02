# Engineering Quality & Architecture Guardrails — proposal package

> **Status:** PROPOSED / REVIEW REQUIRED.
>
> This package defines the policy that a later implementation phase should enforce. It deliberately does **not** change production code, architecture tests, CI, Ruff/Pyright configuration, or the current 100/120 Python file-budget behavior.
>
> **Audited base:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.

## Read in this order

1. `repository-engineering-audit.md`
   - current documented vs observed vs enforced architecture;
   - engineering risk model;
   - gate inventory and dispositions;
   - current measurement limitations;
   - outlier/Goodhart/navigation analysis;
   - migration plan;
   - final adversarial verdict.

2. `engineering-quality-architecture-constitution.md`
   - stable normative intent proposed for approval;
   - architecture invariants;
   - cohesion/locality/navigability principles;
   - complexity and file-size philosophy;
   - enforcement, exception, legacy, agent, and evolution policy.

3. `executable-fitness-function-specification.md`
   - minimal target fitness-function set;
   - HARD proof obligations;
   - severity/classification;
   - threshold register;
   - current-gate disposition;
   - traceability matrix;
   - adversarial simulations A-K.

4. `guardrail-decision-record.md`
   - historical reasoning for controversial decisions such as the 100/120 file cap, complexity calibration, exact-shape tests, exceptions, and ratchets.

## Central proposed decision

The package proposes this hierarchy:

```text
1. real architecture / ownership invariants
2. genuine local reasoning complexity
3. cohesion and locality
4. navigability
5. quantitative metrics as supporting signals
```

The most material current change proposed for the later implementation phase is:

> **File size remains visible, but a universal low file-LOC threshold no longer has enough signal quality to be a HARD architectural blocker.**

This is not a proposal to ignore large files. It is a proposal to stop equating a physical size proxy with semantic architecture.

The corresponding missing signal is function-level control-flow complexity, introduced first as warning/reporting and calibrated from repository data before any hard threshold is considered.

## What remains strongly enforced

The proposal keeps direct architectural invariants HARD:

- cross-module imports through supported contracts;
- explicit approved dependency direction;
- no business-module cycles;
- inward domain/application/contract boundaries;
- technical-only platform;
- composition roots do not bypass module internals.

It explicitly rejects making CI green by:

- re-exporting internals through contracts;
- moving business logic into `shared/common/platform`;
- duplicating business logic merely to avoid a dependency;
- replacing a required atomic transaction with asynchronous messaging for architectural aesthetics.

## Measurement limitation

The current exact-head Python quality job publishes PASS/FAIL for the effective-line budget and test/evidence inventory counts, but it does not publish full repository distributions for:

```text
effective file LOC
function LOC
McCabe complexity
nesting
fan-out
```

Therefore this proposal deliberately does **not** invent p50/p75/p90/p95 values and does not replace the current 120 cliff with another unsupported number.

The first implementation step after approval is a non-blocking deterministic baseline report followed by manual outlier classification.

## Approval boundary

Approval should answer two separate questions:

1. **Policy:** do we accept the constitution, fitness-function classifications, and decision rationale?
2. **Implementation:** once policy is accepted, does the later CI/test change implement it faithfully without creating new harmful incentives?

The implementation phase should not begin by editing the existing gate and then retrofitting policy around the edit.

## Proposed final decision

**YES, WITH EXPLICIT LIMITATIONS** for the proposed contract.

**NO** for the claim that current enforcement is already fully aligned with the proposed maintainability philosophy, principally because the current 100/120 file budget has blocking authority disproportionate to its semantic signal quality.
