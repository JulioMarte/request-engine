# QR-MEGA-001 — Extreme Core File Review Signal

> **Status:** `RETIRED_AS_HARD` / retained as calibration provenance.
>
> **Current authority:** file size is a heuristic maintainability signal. It does not define an architectural invariant. The normative repository governance contract in `docs/testing/repository-governance-contract.md` takes precedence.

## Decision

The experimental rule:

```text
new / crossing / growing scoped core file > 500 effective LOC
    -> QR-MEGA-001 INVARIANT_FAILURE
```

is no longer blocking.

The reason is semantic rather than numerical: the repository cannot defend the claim that `501` effective lines directly implies an architecture violation. The earlier experiment itself acknowledged that a 501-line file can remain cohesive, locally understandable, and correctly owned. Calling that state an `INVARIANT_FAILURE` therefore overstated what the measurement proved.

Current behavior is:

```text
effective file LOC > 120
    -> QR-FSIZE-001 REVIEW_CANDIDATE
    -> semantic review

files far into the tail, including > 500 eLOC core files
    -> remain highly salient review evidence
    -> do not fail CI solely because of line count
```

## Protected property

Request Engine SHOULD detect unusually large concentrations of handwritten core product code early enough for reviewers to ask whether responsibilities, ownership, or reasoning surfaces have accumulated improperly.

The protected property is **not** `file <= 500 lines`.

A healthy review asks:

- Does the file contain multiple independently changing responsibilities?
- Is the file large but mostly declarative or linear?
- Is the difficult reasoning concentrated in one function even if the file is moderate in size?
- Would extraction create a real ownership/responsibility boundary?
- Would extraction instead create wrappers, helpers, re-exports, or extra navigation?

## Why the HARD experiment was retired

The original 500 eLOC experiment had useful properties:

- it was scoped to core product categories rather than universal;
- it used repository measurements before choosing an extreme region;
- it anticipated coding-agent threshold gaming;
- it prevented same-change self-approved exceptions;
- it distinguished generated provenance from source comments.

Those properties made it a much better experiment than the old universal 100/120 hard cap.

They did not solve the central HARD-gate proof problem:

```text
file size
    !=
cohesion
    !=
architectural integrity
```

The normal literal response of a coding agent to a blocking numeric cliff can still be:

```text
501-line cohesive file
    -> split into 450 + 51
    -> add a helper/forwarder
    -> CI green
```

That is exactly the Goodhart behavior the engineering-quality contract is intended to prevent.

## Current classification

`QR-MEGA-001` is best understood as:

```text
HIGH-SIGNAL STRUCTURAL REVIEW CONCEPT
```

not:

```text
DIRECT INVARIANT
```

A future dedicated extreme-outlier review candidate MAY be implemented if it contributes useful independent evidence beyond `QR-FSIZE-001`. It MUST remain non-blocking until a new HARD-gate review demonstrates that the proxy is precise enough to justify blocking.

## Calibration required before any future HARD proposal

A future proposal to make an extreme size region blocking MUST include longitudinal repository evidence, not only a baseline distribution. At minimum it should answer:

1. How often did the extreme signal fire on real changes?
2. What fraction were `HEALTHY_AS_IS` or acceptable trade-offs?
3. What fraction represented genuine maintainability problems?
4. What remediations did humans and coding agents choose?
5. How often did remediation create wrapper/helper/file fragmentation?
6. Did navigation cost rise after metric-driven fixes?
7. Would a different signal such as function complexity, fan-out, or responsibility evidence have predicted the problem more directly?
8. Is the false-positive rate low enough for HARD enforcement?

Percentiles alone do not answer these questions.

## Exception registry

`mega-file-exceptions.v1.json` is retained temporarily as calibration/historical evidence for the abandoned HARD experiment. It is not current merge authorization and is not needed to keep a cohesive >500 eLOC file in the repository while file size remains review-only.

If a future HARD rule is approved, exception semantics must be specified by that newer normative decision rather than inferred from this historical experiment.

## QR-MEGA-GOV-001 disposition

The former rule rejected any ordinary change containing both core product Python and a broad set of quality-policy authority paths.

That predicate was broader than the risk it attempted to prevent. It could reject an unrelated product change and developer-experience/governance maintenance merely because both occurred in one PR.

Therefore `QR-MEGA-GOV-001` is also retired as a HARD co-occurrence invariant.

The underlying principle remains useful:

> A change SHOULD NOT weaken a gate in a way that materially changes the verdict from which that same change benefits.

That is a causal governance-review principle. If future tooling can detect that relationship precisely enough, it may emit review evidence. Ordinary product+policy co-occurrence is not itself an architecture violation.

## What remains HARD

This decision does **not** weaken semantic architecture invariants. Deterministic violations such as the following remain blocking under their existing fitness functions and governance:

- unsupported cross-module internal dependencies;
- unapproved dependency direction;
- dependency cycles;
- domain/application/framework leakage;
- business-policy leakage into technical platform through forbidden dependencies;
- composition bypass of supported module surfaces;
- security, authority, transactional, PostgreSQL, compatibility, and product-contract invariants already governed elsewhere.

An LLM or human review cannot waive those deterministic invariant failures.

## Revisit trigger

Revisit a dedicated extreme-file signal when representative real-PR evidence exists. The goal is not to preserve the number `500`; the goal is to detect responsibility concentration without teaching humans or agents to optimize line count at the expense of cohesion and locality.
