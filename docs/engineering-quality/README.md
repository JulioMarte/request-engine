# Engineering Quality & Architecture Guardrails

> **Lifecycle:** `IMPLEMENTED_FOR_CALIBRATION` / **NOT NORMATIVE**.
>
> The normative repository-governance contract remains `docs/testing/repository-governance-contract.md` until an explicit promotion updates repository precedence.

## Purpose

Request Engine quality governance exists to make the normal route to green CI align with code that is cohesive, navigable, locally understandable, low in genuine reasoning complexity, correctly owned, and easy to evolve.

The governing priority is:

```text
semantic architecture / ownership
    > genuine local reasoning complexity
    > cohesion and locality
    > navigability
    > quantitative metrics
```

A metric is evidence. It is not architecture merely because CI can measure it.

## Current operating model

```text
DETERMINISTIC PROOF
        +
DETERMINISTIC SIGNALING
        +
SEMANTIC REVIEW WHEN NEEDED
        +
DETERMINISTIC RE-VERIFICATION
```

Deterministic architecture/correctness invariants remain blocking. Semantic review cannot waive them.

Maintainability sensors are intentionally non-blocking:

```text
effective file LOC > 120
    -> QR-FSIZE-001 REVIEW_CANDIDATE

Ruff C901 McCabe > 10
    -> QR-CPLX-001 REVIEW_CANDIDATE

new obvious forwarding/re-export indirection
    -> QR-NAV-001 REVIEW_CANDIDATE
```

`HEALTHY_AS_IS` is a valid outcome. A change MUST NOT be called a maintainability improvement solely because a metric decreases while cohesion, locality, navigability, ownership clarity, or architectural integrity gets worse.

## Architecture invariants

The strongest engineering-quality gates remain semantic and deterministic. They protect properties such as:

- cross-module use of supported contract surfaces;
- approved dependency direction;
- acyclic business-module dependencies;
- inward domain/application dependency boundaries;
- technical `platform` ownership;
- composition through supported module surfaces.

These are fundamentally different from LOC, McCabe, file count, or similar proxies.

## File-size policy

File size is a secondary maintainability signal, not an architectural invariant and not a direct measurement of cohesion.

The experimental `QR-MEGA-001` rule that treated a new/crossing/growing scoped core file above 500 effective LOC as `INVARIANT_FAILURE` has been **retired as HARD during calibration**.

A 501-line file may be healthy, an acceptable trade-off, or a real maintainability problem. The number alone cannot decide which.

Files above 500 eLOC are still automatically visible through `QR-FSIZE-001` because they exceed the ordinary review threshold. Review should ask whether there is a real independently changing responsibility, not how to reach 499 lines.

See `mega-file-circuit-breaker.md` for the experiment disposition and evidence required before any future HARD proposal.

## Governance self-modification

The former `QR-MEGA-GOV-001` HARD rule rejected broad product+policy co-occurrence. That was wider than the protected risk and could force unrelated PR splitting.

Current policy is narrower:

> A change SHOULD NOT weaken a gate in a way that materially changes the verdict from which that same change benefits.

`scripts/ci/check_quality_policy_separation.py` now surfaces product/policy co-occurrence for causal governance review. Co-occurrence alone does not fail CI.

## Semantic review

When a maintainability candidate is emitted, use:

- `agent-semantic-review-playbook.md` for coding-agent procedure;
- `semantic-review-protocol.md` for evidence/disposition semantics.

Review must consider responsibility, real reasoning complexity, side effects, locality, ownership, abstraction value, testability, and Goodhart/gaming risk.

Do not split files, extract wrappers, add interfaces, or move logic solely to reduce LOC/C901/file count.

## Measurement and calibration

`scripts/ci/build_engineering_quality_baseline.py` records repository distributions by code category for available maintainability signals. Percentiles describe the repository; they do not become policy automatically.

Calibration should increasingly focus on independent structural evidence, especially dependency/fan-out hotspots and whether metric-triggered remediation increases fragmentation/navigation cost.

A future proposal to make any heuristic HARD must satisfy the documented HARD-gate proof obligation with longitudinal repository evidence, including false positives, false negatives, gaming behavior, likely coding-agent remediation, and second-order architecture effects.

## Evidence packets

`quality-scan/v1` records deterministic measurements and review candidates.

`quality-evidence/v1` provides validated per-candidate review context. Evidence infrastructure is supporting machinery, not a second architecture authority.

If evidence governance becomes more expensive than the decisions it improves, simplify it.

## Local Publish Certification

`local-publish-certification.md` is a **developer-experience / publication-integrity adjunct**, not an architecture fitness function and not part of the semantic quality hierarchy above.

It may certify a local pushed SHA before publication, but it cannot waive or replace GitHub integration proof and it must not be used as evidence that a maintainability metric is architecturally correct.

Keeping this distinction explicit prevents workflow tooling from silently becoming architecture policy.

## Current document roles

| Document | Role |
|---|---|
| `engineering-quality-architecture-constitution.md` | accepted-for-calibration design principles; not normative yet |
| `executable-fitness-function-specification.md` | proposed target fitness functions and HARD proof obligations |
| `repository-engineering-audit.md` | historical audit evidence |
| `guardrail-decision-record.md` | design provenance |
| `semantic-review-protocol.md` | semantic-review evidence contract |
| `agent-semantic-review-playbook.md` | agent review procedure |
| `mega-file-circuit-breaker.md` | retired HARD experiment and recalibration requirements |
| `local-publish-certification.md` | separate developer-experience/publication-integrity design |
| `implementation-roadmap-and-definition-of-done.md` | implementation/calibration/promotion status |
| `calibration/` | pilot and future longitudinal evidence |

## Promotion rule

This package does not become normative because a PR is green.

Promotion requires an explicit governance decision that:

1. reconciles the Constitution and Fitness Specification into one coherent authority;
2. confirms every HARD rule satisfies the proof obligation;
3. demonstrates that heuristic signals remain non-blocking unless independently justified;
4. reviews calibration evidence and exception pressure;
5. updates `docs/README.md` precedence explicitly;
6. proves the promoted implementation through the required integration CI.

## Acceptance test for the governance system

The quality system is healthy only if the cheapest normal response to a failure or warning tends to improve the property actually being protected.

It must have sufficient reason **not** to prefer:

```text
smaller files + more wrappers + more hops
```

over:

```text
cohesive responsibilities + clear ownership + short reasoning paths + explicit boundaries
```

That is the standard against which the guardrails themselves must continue to be reviewed.
