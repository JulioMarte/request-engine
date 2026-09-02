# Engineering Quality & Architecture Guardrails

> **Lifecycle status:** `IMPLEMENTED_FOR_CALIBRATION` / **NOT NORMATIVE**.
>
> **Historical audit base:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.
>
> Merge readiness is determined only by the full GitHub integration CI graph for the current PR tip. This document does not self-certify a commit SHA.

## Purpose

This package defines and calibrates the engineering-quality model used to keep Request Engine maintainable without turning weak proxies into architecture policy.

The target property is:

> The normal route to green CI should, for the important cases, also be the route toward code that is cohesive, navigable, locally understandable, low in genuine reasoning complexity, correctly encapsulated, and easy to evolve.

The governing hierarchy is:

```text
semantic architecture / ownership
    > genuine local reasoning complexity
    > cohesion and locality
    > navigability
    > quantitative metrics
```

The operating model is:

```text
DETERMINISTIC PROOF
        +
DETERMINISTIC SIGNALING
        +
SEMANTIC REVIEW WHEN NEEDED
        +
DETERMINISTIC RE-VERIFICATION
```

An LLM is an analyst of evidence. It is not a replacement for architecture tests, type checking, PostgreSQL proof, security checks, or GitHub integration CI.

## Lifecycle and authority

The engineering-quality Constitution and Fitness Specification are accepted for calibration, not yet promoted to repository-wide normative precedence. Green CI proves implementation correctness for a tested integration candidate; it does not silently create architecture policy.

Current canonical repository governance outside this package remains `docs/testing/repository-governance-contract.md`. Normative promotion requires an explicit decision and `docs/README.md` precedence update.

## Current deterministic architecture authority

Existing semantic architecture/correctness checks remain blocking where they directly protect accepted invariants, including module public surfaces, approved dependency direction, cycles, inward layer dependencies, platform ownership, composition boundaries, security/authority/transactional guarantees, PostgreSQL behavior, compatibility, and product contracts.

A deterministic `INVARIANT_FAILURE` cannot be converted into a pass by semantic review.

## Maintainability and structural review signals

The compatibility entry point `scripts/ci/check_python_file_budget.py` now emits non-blocking structured evidence.

```text
effective file LOC > 120
    -> QR-FSIZE-001 REVIEW_CANDIDATE

Ruff C901 McCabe > 10
    -> QR-CPLX-001 REVIEW_CANDIDATE

new obvious forwarding/re-export indirection
    -> QR-NAV-001 REVIEW_CANDIDATE

new direct outbound business-module dependency
    -> QR-COUPLING-001 REVIEW_CANDIDATE
```

These are attention triggers, not architecture verdicts. `HEALTHY_AS_IS` and `INSUFFICIENT_CONTEXT` remain valid outcomes.

### Fan-in / fan-out

`scripts/ci/build_engineering_quality_baseline.py` records the actual direct AST import graph between `src/request_engine/modules/*` business modules.

For each module it reports:

```text
fan-in
    = number of distinct business modules with direct imports into this module

fan-out
    = number of distinct business modules this module directly imports
```

The baseline also records inbound/outbound module names, total direct edges, fan-in/fan-out distributions and highest-coupling outliers.

There is deliberately **no** rule such as:

```text
fan-out > N -> failure
```

A stable high fan-out value is trend/outlier evidence. It does not fail CI by itself.

`QR-COUPLING-001` is delta-driven. It appears when a change adds a new direct outbound business-module dependency. The review asks whether the synchronous edge is genuinely required, whether ownership remains correct, and whether an existing contract/event/read model provides a cleaner connection.

Removing an edge and changes in fan-in/fan-out are retained in the machine-readable graph delta even when they do not create a review candidate.

Metric gaming is explicitly invalid. A coding agent must not hide a dependency behind a service locator, generic shared helper, runtime import, re-export facade, or forwarding wrapper merely to reduce measured fan-out.

### File-size HARD experiment retired

The earlier calibration experiment that treated a new/crossing/growing scoped core file above 500 effective LOC as `QR-MEGA-001 INVARIANT_FAILURE` is retired as HARD.

The repository cannot defend the claim that 501 effective lines directly constitutes an architecture violation. Extreme size remains visible through file-size review evidence. A future HARD proposal would require longitudinal evidence satisfying the full HARD-gate proof obligation, including false-positive pressure, coding-agent response and second-order navigation effects.

### Governance co-occurrence

The earlier broad `QR-MEGA-GOV-001` HARD product+policy co-occurrence rule is also retired. Product and governance files may legitimately change together.

The remaining principle is causal: review whether a governance change can materially alter a verdict from which the same product change benefits. Co-occurrence alone is not an invariant failure.

## Baseline and evidence

`scripts/ci/build_engineering_quality_baseline.py` produces `engineering-quality-baseline/v1` evidence with categorized distributions for:

- effective Python file LOC;
- function LOC;
- Ruff C901 McCabe per function;
- nonblank configuration LOC;
- business-module fan-in;
- business-module fan-out;
- direct business-module dependency edges.

Percentiles and outliers describe the repository. They do not become thresholds automatically.

`scripts/ci/finalize_quality_evidence.py` produces `quality-evidence/v1` packets for semantic-review candidates. Evidence packets preserve deterministic facts, deltas, context, review questions and architecture/quality proof state.

## Semantic review

`semantic-review-protocol.md` and `agent-semantic-review-playbook.md` define the reviewer contract.

Review must consider responsibility, real reasoning complexity, side effects, cohesion, locality, ownership, abstraction value, testability, coupling and Goodhart/gaming risk.

A lower LOC/C901/fan-out value is not evidence of improvement if the remediation worsens locality, ownership, navigability, duplication or architectural clarity.

After any remediation, deterministic proof must run again.

## Local Publish Certification

Local Publish Certification remains implemented as a developer-experience / publication-integrity adjunct. It is not an architecture fitness function and cannot replace GitHub integration CI.

## Calibration obligations before normative promotion

Before future `NORMATIVE` promotion:

1. reconcile Constitution and Fitness Specification into one coherent authority;
2. verify every HARD rule against the full HARD-gate proof obligation;
3. collect representative longitudinal human review evidence;
4. observe metric-gaming and fragmentation/navigation effects;
5. inspect fan-in/fan-out deltas and recurring coupling hotspots across real PRs;
6. recalibrate or retire noisy signals;
7. explicitly update `docs/README.md` precedence;
8. prove the final promoted implementation through the required GitHub integration graph.

No heuristic threshold becomes HARD because it matches a percentile, because a tool can block CI, or because an LLM repeatedly agrees with it.

## Read in this order

1. `README.md` — current lifecycle and implemented calibration model.
2. `repository-engineering-audit.md` — historical audit evidence.
3. `engineering-quality-architecture-constitution.md` — architecture principles accepted for calibration.
4. `executable-fitness-function-specification.md` — fitness-function classifications and proof obligations, including `FF-TREND-001` fan-in/fan-out observation.
5. `hybrid-quality-review-architecture.md` — deterministic/semantic review architecture.
6. `semantic-review-protocol.md` — semantic classifications and authority.
7. `agent-semantic-review-playbook.md` — coding-agent procedure.
8. `implementation-roadmap-and-definition-of-done.md` — phase status and promotion obligations.
9. `calibration/README.md` — evidence interpretation.
10. `local-publish-certification.md` — developer publication workflow, intentionally outside architecture fitness authority.
