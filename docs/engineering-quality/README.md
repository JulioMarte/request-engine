# Engineering Quality & Architecture Guardrails — proposal package

> **Status:** PROPOSED / REVIEW REQUIRED.
>
> This package defines the policy and implementation target that a later engineering phase should enforce. It deliberately does **not** change production code, architecture tests, CI, Ruff/Pyright configuration, LLM review automation, or the current 100/120 Python file-budget behavior.
>
> **Audited base:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.

## What this package is trying to achieve

Request Engine needs guardrails that make the easiest path to green CI also tend toward better ownership, lower genuine reasoning complexity, stronger locality, and clearer architecture.

The proposal rejects a model where one cheap proxy such as file LOC silently becomes architecture authority.

The refined target is a hybrid system:

```text
DETERMINISTIC PROOF
        +
DETERMINISTIC SIGNALING
        +
PROBABILISTIC SEMANTIC REVIEW
        +
DETERMINISTIC RE-VERIFICATION
```

The responsibilities are intentionally different:

```text
Deterministic code answers:
    WHAT happened?

Probabilistic semantic review answers:
    DOES it matter and WHY?

A coding agent may answer:
    HOW might we improve it?

Deterministic proof answers:
    DID the change preserve correctness and architecture?
```

An LLM is therefore an analyst of evidence, not a replacement for architecture checks, tests, type checking, PostgreSQL proof, or exact-head CI.

## Read in this order

### 1. `repository-engineering-audit.md`

Current-state evidence:

- documented vs observed vs enforced architecture;
- engineering risk model;
- gate inventory and dispositions;
- current measurement limitations;
- outlier/Goodhart/navigation analysis;
- existing policy drift;
- migration risks.

This is evidence/provenance, not the desired stable constitution.

### 2. `engineering-quality-architecture-constitution.md`

Proposed stable policy:

- architecture invariants;
- cohesion/locality/navigability principles;
- complexity and file-size philosophy;
- enforcement, exception, legacy, agent, and evolution policy.

The constitution's central rule remains:

> semantic architecture and ownership outrank structural proxies.

### 3. `hybrid-quality-review-architecture.md`

Target operating model:

- deterministic vs probabilistic division of authority;
- deterministic sensors;
- evidence packets;
- semantic review context;
- reviewer/fixer separation;
- prompt-injection boundary;
- calibration loop;
- concrete large/simple, small/complex, fragmentation, and architecture examples.

This document explains **what system we want to build and why**.

### 4. `semantic-review-protocol.md`

The contract between deterministic tooling and semantic review:

- operational classifications and merge semantics;
- trigger definitions;
- evidence-packet schema;
- trusted instruction boundary;
- reviewer reasoning frame;
- structured verdict schema;
- confidence policy;
- reviewer/fixer protocol;
- human escalation;
- trigger calibration/retirement/promotion;
- failure UX.

This document explains **how the probabilistic layer is constrained so it remains useful without becoming an unreliable merge oracle**.

### 5. `executable-fitness-function-specification.md`

Proposed deterministic fitness-function set:

- HARD proof obligations;
- direct architecture invariants;
- function complexity signal;
- file-size signal;
- navigability/fragmentation diagnostics;
- trend reporting;
- current-gate disposition;
- traceability matrix;
- adversarial simulations.

This document describes **what deterministic tooling should prove or measure**.

### 6. `implementation-roadmap-and-definition-of-done.md`

Delivery and acceptance plan:

- policy lifecycle;
- baseline measurement;
- deterministic sensor implementation;
- evidence-packet implementation;
- semantic-review pilot;
- reviewer/fixer re-proof loop;
- calibration metrics;
- enforcement migration;
- normative promotion;
- system-level Definition of Done;
- acceptance simulations;
- rollback criteria.

This document answers **how we will know the work is actually finished**.

### 7. `guardrail-decision-record.md`

Historical reasoning for controversial decisions:

- why 100/120 should not remain universal HARD architecture authority;
- why complexity starts as warning/review evidence;
- why exact private shape is not automatically architecture;
- how exceptions and ratchets should behave;
- why direct architecture boundaries remain HARD.

Decision records preserve rationale; they should not become the largest normative surface.

## Central proposed decision

The package proposes this hierarchy:

```text
1. direct architecture / ownership invariants
2. genuine local reasoning complexity
3. cohesion and locality
4. navigability
5. quantitative metrics as supporting evidence
```

The most material enforcement change proposed for the later implementation phase is:

> **File size remains visible, but a universal low file-LOC threshold no longer has enough semantic precision to be a HARD architectural blocker.**

This is not a proposal to ignore large files.

It is a proposal to change the meaning of a large-file finding from:

```text
VIOLATION: split this file to get under the limit
```

into something closer to:

```text
REVIEW CANDIDATE:
this file is an outlier;
size alone is not a defect;
inspect responsibility, local complexity, side effects, ownership and navigation before recommending structural change.
```

## What remains strongly enforced

The proposal keeps direct architectural invariants HARD:

- cross-module imports through supported public surfaces;
- explicit approved dependency direction;
- no business-module cycles;
- inward domain/application/contract boundaries;
- technical-only platform;
- composition roots do not bypass module internals.

An LLM cannot override these checks.

If a direct invariant blocks a legitimate architecture change, the correct state is:

```text
POLICY EVOLUTION REQUIRED
```

followed by explicit architecture evolution, not an AI waiver.

## What becomes semantic-review evidence

Examples:

- unusually large files;
- high function-level McCabe complexity;
- abrupt complexity growth;
- one-call forwarding wrappers;
- re-export-only files;
- file-count/delegation growth after a refactor;
- high but legal dependency fan-out;
- possible ownership diffusion.

These signals should locate code worth understanding. They should not automatically prescribe the repair.

## Example — large but healthy

```text
510 effective LOC
max McCabe 3
one declarative mapping responsibility
no side effects
```

Expected behavior:

```text
file-size candidate
-> semantic review
-> HEALTHY_AS_IS is allowed
-> no forced split
```

## Example — small but difficult

```text
88 effective LOC
McCabe 21
authorization + persistence + event publication + retry + pricing policy
```

Expected behavior:

```text
complexity candidate
-> semantic review
-> REFACTOR_RECOMMENDED when evidence supports it
-> deterministic tests/architecture checks re-run after remediation
```

The current 120-line rule can miss this case entirely.

## Example — metric gaming

```text
before:
one cohesive 180-line flow

after:
six files
four forwarding wrappers
same conceptual branches
more navigation
```

The target system MUST NOT declare this better solely because individual files became smaller or individual functions received lower complexity scores.

## Measurement limitation

The current exact-head Python quality job does not publish complete repository distributions for:

```text
effective file LOC
function LOC
McCabe complexity
nesting
fan-out
```

Therefore this proposal deliberately does **not** invent p50/p75/p90/p95 values and does not replace the current 120 cliff with another unsupported number.

The first implementation step after policy acceptance is a non-blocking deterministic baseline report followed by representative outlier classification.

## How the future system will be evaluated

The implementation must measure not only code metrics but also the quality system itself.

Useful review-system measures include:

```text
candidate count by trigger
HEALTHY_AS_IS rate
REVIEW_CONCERN rate
REFACTOR_RECOMMENDED rate
ARCHITECTURE_CONCERN rate
INSUFFICIENT_CONTEXT rate
human override rate
recommendation accepted/deferred/rejected rate
repeat-finding rate
review cost and latency
prompt-injection test results
post-fix deterministic verification results
```

These metrics evaluate whether the guardrail system is useful and calibrated. They are not developer performance scores.

## Policy lifecycle

The package should use four explicit states:

```text
PROPOSED
ACCEPTED_FOR_CALIBRATION
IMPLEMENTED
NORMATIVE
```

The constitution must not become `NORMATIVE` while blocking CI still contradicts it.

Likewise, current blocking enforcement should not be removed before the replacement sensing/review path is ready enough to preserve visibility.

Normative policy and blocking enforcement should converge in one coherent migration.

## Definition of Done — shortest form

The migration is complete only when all four questions below have the expected answer:

```text
Can a 500-line cohesive file remain intact without bypassing policy?
YES.

Can an 80-line function with severe reasoning complexity be surfaced?
YES.

Can an LLM approve around a deterministic architecture violation?
NO.

Can a coding agent claim success without deterministic re-proof?
NO.
```

The full acceptance matrix is in `implementation-roadmap-and-definition-of-done.md`.

## Approval boundary

Approval should answer three separate questions:

1. **Policy:** do we accept the architecture/maintainability principles and division of authority?
2. **Protocol:** do we accept the evidence-packet, semantic-review, trusted-context, escalation, and re-proof model?
3. **Implementation:** once policy is accepted, does later CI/tooling faithfully implement it without creating new harmful incentives?

The implementation phase should not begin by editing an existing gate and then retrofitting policy around the edit.

## Current proposal verdict

**YES for the refined architectural direction.**

**REVIEW REQUIRED before normative promotion.**

**NO** for the claim that current enforcement already matches the proposed model, principally because the current 100/120 file budget still has blocking authority disproportionate to its semantic signal quality and no semantic-review implementation exists yet.
