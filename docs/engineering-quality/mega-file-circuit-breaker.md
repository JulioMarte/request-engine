# QR-MEGA-001 — Core Mega-File Circuit Breaker

> **Status:** executable policy in calibration.
>
> **Purpose:** prevent accidental or agent-driven concentration of core handwritten product logic into extreme files without reviving the old universal low-LOC architecture proxy.

## Protected property

Request Engine should not admit an extreme new concentration of core product code by accident. This rule is a **circuit breaker**, not a claim that 501 lines are inherently bad architecture.

The maintainability model remains:

```text
> 120 effective LOC
    -> QR-FSIZE-001 REVIEW_CANDIDATE
    -> semantic review

> 500 effective LOC in scoped core handwritten Python
    -> QR-MEGA-001 INVARIANT_FAILURE
    -> explicit intervention required
```

The first threshold asks a question. The second stops an extreme shape from entering silently.

## Scope

`QR-MEGA-001` applies only to handwritten Python classified as:

```text
production_domain
production_application
production_contracts
production_api
production_composition
```

It does not become a universal 500-line repository cap.

Adapters, tests, scripts, migrations, configuration, and generated code retain their differentiated policies. They may still produce `QR-FSIZE-001`, `QR-CPLX-001`, `QR-NAV-001`, or other review evidence.

## Why 500 is defensible here

The repository-wide baseline measured before this gate showed core-file maxima materially below 500 effective LOC while other categories had very different distributions. In the observed baseline, application/contracts/API/domain/composition maxima were roughly 118–355 eLOC, while adapters, tests, scripts, and migrations reached much larger sizes.

Therefore 500 is intentionally positioned as an **extreme core outlier circuit breaker**, not as the repository's definition of maintainability.

The number must be revisited if repository distributions or legitimate exception pressure change materially.

## Blocking semantics

A scoped core file fails `QR-MEGA-001` when a changed file:

- is newly introduced above 500 effective LOC;
- crosses from `<=500` to `>500`; or
- is already legacy `>500` and grows beyond its previous effective LOC without a valid base-approved exception.

A legacy mega-file may shrink without first obtaining an exception. Shrinkage is not blocked merely because the resulting file remains above 500.

## Exception authority

Exceptions live in:

`docs/engineering-quality/mega-file-exceptions.v1.json`

Each exception must identify:

```text
exact Python path
bounded max_effective_loc ceiling
substantive rationale
approval_ref
```

The critical authorization rule is:

> **The implementation gate reads the exception registry from the branch base, not from the changed working tree.**

Therefore an exception created or modified in the same implementation PR cannot authorize that PR.

A valid new exception requires a separate architecture/governance decision to be reviewed and merged into the integration base first. The implementation must then be rebuilt/rebased from that base and re-proved.

This is deliberate protection against self-approval by both humans and coding agents.

## Invalid justification

The following do **not** waive `QR-MEGA-001`:

- an LLM saying `HEALTHY_AS_IS`;
- the file author stating that the file is cohesive;
- a PR description or comment;
- source comments/docstrings;
- generated review text;
- lowering C901 while remaining above the mega-file threshold;
- adding an exception entry in the same implementation change;
- editing the checker/test to make the current change pass.

A semantic explanation can support a **separate exception decision**, but it cannot be its own authorization.

## Valid remediation

When the gate fires, there are two legitimate paths.

### 1. Improve the design

Refactor only when there is a real semantic boundary such as:

- independently changing responsibility;
- clear ownership split;
- pure policy separable from effectful orchestration;
- stable public/adapter boundary;
- materially shorter reasoning path.

The goal is not `499`.

A change such as:

```text
701-line cohesive file
    -> 480-line file
    -> 221-line forwarding/helper file
```

is not automatically an improvement and should be challenged by `QR-NAV-001` and semantic review.

### 2. Obtain a prior exception

Stop the implementation. Create a separate architecture/governance change containing the exact-path bounded exception and rationale. Have that decision reviewed and merged into the base. Then rebuild/rebase the implementation and rerun exact-head deterministic proof.

The exception ceiling must be finite. If the file later exceeds that ceiling, the gate blocks again.

## Coding-agent threat model

A coding agent is good at producing plausible rationale and at optimizing literal thresholds. The policy therefore assumes these likely gaming strategies:

```text
write 700 lines -> add exception -> claim cohesion
write 700 lines -> split into wrapper/helper files
write 700 lines -> lower C901 but preserve one giant responsibility container
write 700 lines -> edit the test/allowlist
```

The countermeasures are:

```text
base-ref-only exception authority
+
QR-NAV-001 fragmentation diagnostics
+
C901/function evidence
+
semantic review
+
unchanged HARD architecture invariants
+
exact-head re-proof
```

## Failure UX

A failure must tell the agent:

```text
WHAT: QR-MEGA-001 failed
WHERE: exact path
FACT: current and previous effective LOC
AUTHORITY: exception registry is read from base ref only
INVALID: self-justification/same-change exception
VALID PATHS: meaningful semantic refactor OR separate pre-approved exception
RE-PROOF: exact-head deterministic CI required afterward
```

A message that only says `701 > 500` is insufficient because it teaches metric optimization instead of the policy.

## Acceptance tests

The implementation is correct only if all of these remain true:

```text
500-line scoped core file
    -> no QR-MEGA-001 failure
    -> QR-FSIZE-001 review remains possible

501-line new application file, no base exception
    -> QR-MEGA-001 INVARIANT_FAILURE

900-line script
    -> no QR-MEGA-001
    -> review signals may still apply

620 -> 590 legacy core file
    -> allowed shrink

480 -> 640 core file with base-approved ceiling 650
    -> allowed by the circuit breaker

480 -> 651 with base-approved ceiling 650
    -> QR-MEGA-001 failure

implementation PR adds 700-line core file + its own exception
    -> still QR-MEGA-001 failure

exception merged first, implementation rebased afterward
    -> exception may authorize only its exact path and ceiling
```

## Revisit triggers

Recalibrate this rule if any of the following becomes true:

- repeated legitimate exceptions accumulate;
- core baseline distributions move materially toward 500;
- the normal repair repeatedly causes harmful fragmentation despite QR-NAV review;
- a different metric predicts extreme responsibility concentration with materially better precision;
- core category definitions change.

The goal is to prevent accidental mega-files, not to preserve the number 500 forever.
