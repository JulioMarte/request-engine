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
ARCHITECTURE DIFF CONTEXT
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

The dependency guardrail now also has an adversarial conformance suite for absolute/relative cross-module surfaces and direct/transitive cycles. The suite intentionally records the remaining static-analysis limitation: dynamic imports and service-locator indirection are not falsely claimed as statically proven absent.

## Maintainability and structural review signals

The compatibility entry point `scripts/ci/check_python_file_budget.py` emits non-blocking structured evidence.

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

### Fan-in / fan-out and contract width

`scripts/ci/build_engineering_quality_baseline.py` records the actual direct AST import graph between `src/request_engine/modules/*` business modules.

For each module it reports:

```text
fan-in
    = number of distinct business modules with direct imports into this module

fan-out
    = number of distinct business modules this module directly imports
```

The graph also records, per edge, which symbols are visibly consumed through the target module's published `contracts` surface. This makes a second structural dimension observable:

```text
edge count stable
+
contract symbols consumed 2 -> 7
```

Such growth can represent legitimate orchestration or growing dependency depth. It is evidence for review, not a defect and not a numeric cliff.

There is deliberately **no** rule such as:

```text
fan-out > N -> failure
contract symbols > N -> failure
```

A stable high fan-out value or wide contract consumption is trend/outlier evidence. It does not fail CI by itself.

`QR-COUPLING-001` remains delta-driven. It appears when a change adds a new direct outbound business-module dependency. The review asks whether the synchronous edge is genuinely required, whether ownership remains correct, and whether an existing contract/event/read model provides a cleaner connection.

Metric gaming is explicitly invalid. A coding agent must not hide a dependency behind a service locator, generic shared helper, runtime import, re-export facade, or forwarding wrapper merely to reduce measured fan-out or contract width.

## Architecture Diff v1

`scripts/ci/build_architecture_diff.py` emits `.ci/architecture-diff.json` for the tested tree.

It records independent deltas for:

- added/removed direct business-module edges;
- added/removed contract symbols consumed per module edge;
- explicit suppression comments on changed Python (`noqa`, `type: ignore`, `nosec`, `pragma: no cover`);
- obvious forwarding/re-export navigation-shape changes;
- source-head / base / tested-tree provenance.

The diff deliberately computes **no architecture score**. A PR is not better because a composite number decreased. The evidence exists so reviewers can see second-order changes when a metric-focused refactor improves one number while worsening coupling, suppression pressure, or navigation.

Suppression growth is not automatically bad: a justified `type: ignore` or coverage pragma may be correct. The protected property is that silencing pressure stays visible rather than becoming an invisible path to green CI.

## File-size HARD experiment retired

The earlier calibration experiment that treated a new/crossing/growing scoped core file above 500 effective LOC as `QR-MEGA-001 INVARIANT_FAILURE` is retired as HARD.

The repository cannot defend the claim that 501 effective lines directly constitutes an architecture violation. Extreme size remains visible through file-size review evidence. A future HARD proposal would require longitudinal evidence satisfying the full HARD-gate proof obligation, including false-positive pressure, coding-agent response and second-order navigation effects.

## Governance co-occurrence

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
- direct business-module dependency edges;
- contract symbols consumed on each direct business-module edge.

Percentiles and outliers describe the repository. They do not become thresholds automatically.

`scripts/ci/finalize_quality_evidence.py` produces `quality-evidence/v2` packets for semantic-review candidates. `v1` remains a historical schema. `v2` makes provenance explicit:

```text
base_sha
source_head_sha
     = feature/source branch commit

tested_sha
     = exact checked-out tree CI actually executed

test_mode
     = PR_INTEGRATION_CANDIDATE | BRANCH_HEAD
```

For pull requests, GitHub normally tests a synthetic integration candidate. `source_head_sha` and `tested_sha` are therefore expected to differ. Evidence finalization fails if baseline, scan and architecture-diff artifacts disagree about the tested tree.

## Semantic review and human calibration

`semantic-review-protocol.md` and `agent-semantic-review-playbook.md` define the reviewer contract.

Review must consider responsibility, real reasoning complexity, side effects, cohesion, locality, ownership, abstraction value, testability, coupling and Goodhart/gaming risk.

A lower LOC/C901/fan-out value is not evidence of improvement if the remediation worsens locality, ownership, navigability, duplication or architectural clarity.

Human calibration now distinguishes **model/verdict agreement** from **signal usefulness**. Genuine human reviews may separately record true-positive/false-positive/accepted-trade-off disposition, action taken, post-change outcome and whether metric gaming was observed. Those fields are invalid without a real human verdict and are never inferred from green CI or model output.

After any remediation, deterministic proof must run again.

## Local Publish Certification

Local Publish Certification remains implemented as a developer-experience / publication-integrity adjunct. It is not an architecture fitness function and cannot replace GitHub integration CI.

## Calibration obligations before normative promotion

Before future `NORMATIVE` promotion:

1. reconcile Constitution and Fitness Specification into one coherent authority;
2. verify every HARD rule against the full HARD-gate proof obligation and guardrail conformance fixtures;
3. collect representative longitudinal human review evidence;
4. observe metric-gaming and fragmentation/navigation effects;
5. inspect fan-in/fan-out, contract-width, suppression and navigation deltas across real PRs;
6. recalibrate or retire noisy signals;
7. explicitly update `docs/README.md` precedence;
8. prove the final promoted implementation through the required GitHub integration graph.

No heuristic threshold becomes HARD because it matches a percentile, because a tool can block CI, or because an LLM repeatedly agrees with it.

## Read in this order

1. `README.md` — current lifecycle and implemented calibration model.
2. `repository-engineering-audit.md` — historical audit evidence.
3. `engineering-quality-architecture-constitution.md` — architecture principles accepted for calibration.
4. `executable-fitness-function-specification.md` — fitness-function classifications and proof obligations.
5. `hybrid-quality-review-architecture.md` — deterministic/semantic review architecture.
6. `semantic-review-protocol.md` — semantic classifications and authority.
7. `agent-semantic-review-playbook.md` — coding-agent procedure.
8. `implementation-roadmap-and-definition-of-done.md` — phase status and promotion obligations.
9. `calibration/README.md` — human/model and signal-usefulness evidence interpretation.
10. `local-publish-certification.md` — developer publication workflow, intentionally outside architecture fitness authority.
