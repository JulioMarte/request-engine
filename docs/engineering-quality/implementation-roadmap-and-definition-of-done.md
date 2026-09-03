# Engineering Quality Hybrid Review — Current Roadmap and Definition of Done

> **Lifecycle status:** `IMPLEMENTED_FOR_CALIBRATION` / calibration incomplete / normative promotion pending.
>
> **Historical audit base:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.
>
> This file records the current implementation/calibration state. The branch remains **not NORMATIVE** until the explicit promotion phase is completed.

## 1. Purpose

This roadmap answers two different questions that must not be conflated:

1. **What has been implemented and can be proven today?**
2. **What evidence is still required before the model may become normative?**

A green implementation PR proves the implementation at one tested integration candidate. It does not manufacture longitudinal calibration evidence and it does not implicitly ratify architecture policy.

## 2. Target operating model

```text
DETERMINISTIC PROOF
    -> accepted architecture/correctness invariants

DETERMINISTIC SIGNALING
    -> reproducible maintainability/coupling facts and candidates

SEMANTIC REVIEW
    -> contextual interpretation with constrained authority

DETERMINISTIC RE-PROOF
    -> independently verify any applied remediation
```

The target property remains:

> Optimizing for green should normally improve cohesion, navigability, local reasoning, encapsulation, ownership clarity and evolvability rather than reward fragmentation, hidden coupling or metric gaming.

## 3. Lifecycle states

### `HISTORICAL_SNAPSHOT`

Evidence describes a specific past SHA and must not be read as current repository state.

### `PROPOSED`

Design exists but has not been accepted for executable calibration.

### `ACCEPTED_FOR_CALIBRATION`

The direction is accepted strongly enough to implement and measure. It is not yet normative architecture policy.

### `IMPLEMENTED_FOR_CALIBRATION`

Executable mechanisms exist and have repository tests/evidence. Their usefulness, ergonomics, thresholds, or long-term authority are still being calibrated.

### `NORMATIVE`

Canonical governance and executable enforcement have been explicitly promoted and agree. This requires an intentional architecture/governance decision; it is never inferred from CI alone.

## 4. Current phase summary

| Phase | Current state | Evidence / remaining obligation |
|---|---|---|
| 0. Policy direction | `ACCEPTED_FOR_CALIBRATION` | semantic-over-metric authority defined; normative promotion pending |
| 1. Repository baseline | `IMPLEMENTED_FOR_CALIBRATION` | categorized LOC/function/C901 and module fan-in/fan-out distributions exist |
| 2. Deterministic sensors | `IMPLEMENTED_FOR_CALIBRATION` | QR-FSIZE, QR-CPLX, QR-NAV and QR-COUPLING are executable and non-blocking |
| 3. Evidence packets | `IMPLEMENTED_FOR_CALIBRATION` | `quality-scan/v1` discovery, current `quality-evidence/v2` packets, schema and validator exist (`quality-evidence/v1` is historical) |
| 4. Semantic review pilot | `IMPLEMENTED_FOR_CALIBRATION` | playbook/protocol and pilot observations exist; more real-PR/human data needed |
| 5. Reviewer/fixer + re-proof | `IMPLEMENTED_FOR_CALIBRATION` | separation rules and deterministic re-proof remain authoritative |
| 6. Calibration | `ACTIVE / INCOMPLETE` | longitudinal human labels, cost/latency, coupling outcomes and disagreement data remain incomplete |
| 7. Enforcement alignment | `IMPLEMENTED_FOR_CALIBRATION` | low numeric maintainability cliffs retired; semantic architecture invariants remain blocking |
| 7A. Local publish certification | `IMPLEMENTED_FOR_CALIBRATION` | DX/publication-integrity adjunct; ergonomics still being measured |
| 8. Normative promotion | `PENDING` | explicit approval and consolidated normative docs required after calibration |

## 5. Phase 0 — Policy direction

The repository now has an explicit authority model:

```text
accepted deterministic invariant
    > deterministic fact
    > constrained semantic interpretation
    > coding-agent remediation proposal
```

File LOC, McCabe, fan-in, fan-out and navigation observations are not architecture invariants merely because they are measurable.

The semantic reviewer cannot waive `INVARIANT_FAILURE`.

## 6. Phase 1 — Repository baseline

`scripts/ci/build_engineering_quality_baseline.py` produces versioned categorized evidence.

Current deterministic measurement families include:

```text
effective Python file LOC
function LOC
per-function Ruff C901 McCabe
nonblank configuration LOC
business-module fan-in
business-module fan-out
direct business-module dependency edges
```

Numeric distributions expose nearest-rank:

```text
count
min
p50
p75
p90
p95
p99
max
```

The business-module graph also records each module's inbound/outbound neighbor sets and top fan-in/fan-out outliers.

### Remaining calibration work

- accumulate baseline movement over a representative development interval;
- inspect recurring healthy and unhealthy outliers by category;
- inspect stable and rapidly growing coupling hubs;
- use observations to recalibrate signals rather than convert percentiles directly to policy.

## 7. Phase 2 — Deterministic maintainability/coupling sensors

### QR-FSIZE-001

```text
effective file LOC > 120
    -> REVIEW_CANDIDATE
```

This is a question, not a forced split.

### QR-CPLX-001

```text
Ruff C901 McCabe > 10
    -> REVIEW_CANDIDATE
```

C901 remains outside the global blocking Ruff selection.

### QR-NAV-001

Conservative forwarding/re-export/navigation evidence can surface likely fragmentation without asserting that every small boundary file is wrong.

### QR-COUPLING-001

```text
new direct outbound business-module dependency
    -> REVIEW_CANDIDATE
```

The signal is **delta-driven**, not threshold-driven. Stable fan-in/fan-out values remain trend evidence. There is deliberately no `fan-out > N = failure` rule.

For each changed source module, review asks:

- why each new synchronous edge is required;
- whether the source module remains the correct owner/coordinator;
- whether an existing public contract/event/read model expresses the relationship better;
- whether any proposed remediation merely hides coupling behind service locators, runtime imports, shared helpers, re-export facades or forwarding wrappers.

The scanner records added and removed dependency edges in the machine-readable report even when no candidate is emitted for a removal.

### Retired QR-MEGA HARD experiment

The former `QR-MEGA-001` 500/501 eLOC `INVARIANT_FAILURE` experiment is retired. Extreme file size remains review evidence. Reintroducing a HARD size rule would require longitudinal evidence satisfying the full HARD-gate proof obligation.

### Retired broad governance co-occurrence HARD

Product+quality-policy co-occurrence is not itself an invariant failure. Review remains causal: a change should not weaken a gate in a way that materially changes a verdict from which the same product change benefits.

## 8. Phase 3 — Evidence Packet

Discovery and semantic handoff remain separate:

```text
quality-scan/v1
    -> run-level discovery and graph deltas

quality-evidence/v2
    -> candidate-level review packet (v1 is historical)
```

Evidence packets include candidate/trigger IDs, repository/base/head SHA, scope/module/category/files, deterministic facts/deltas, architecture/quality state, context manifest, review questions, provenance and authority metadata.

## 9. Phase 4 — Semantic review pilot

Semantic review remains constrained by the evidence packet and repository authority. Valid outcomes include `HEALTHY_AS_IS` and `INSUFFICIENT_CONTEXT`.

A lower LOC, C901, file count or fan-out value is not a successful remediation when cohesion, locality, ownership, navigation or architectural clarity worsens.

## 10. Phase 5 — Reviewer/fixer separation and deterministic re-proof

Review and modification are separate roles/phases. Any code remediation must be followed by the deterministic proof appropriate to the changed guarantee.

No coding agent may self-certify architecture correctness from an improved metric.

## 11. Phase 6 — Calibration

Calibration remains incomplete.

Required evidence includes:

- representative human dispositions across real PRs;
- review cost/latency;
- repeated model/human disagreement;
- false-positive/false-negative examples;
- fragmentation responses to LOC/C901 signals;
- dependency-hiding attempts or service-locator responses to coupling review;
- actual outcomes of fan-out expansions and contractions;
- repeated healthy coupling hubs that should remain untouched.

## 12. Phase 7 — Enforcement alignment

The current target is intentionally asymmetric:

```text
semantic architecture/correctness invariants
    -> HARD when precise and directly measurable

maintainability/coupling heuristics
    -> REVIEW / INFORMATIONAL during calibration
```

A future proposal to make LOC, McCabe, fan-in, fan-out, fragmentation or another heuristic merge-blocking must satisfy the HARD-gate proof obligation and explicit normative approval.

## 13. Phase 7A — Local publish certification

Local Publish Certification remains a developer-experience/publication-integrity adjunct. It is not architecture authority and cannot replace GitHub integration proof.

## 14. Phase 8 — Normative promotion

Promotion requires all of:

1. Constitution and Fitness Specification reconciled into one coherent authority;
2. every HARD rule re-checked against the full proof obligation;
3. representative longitudinal human evidence;
4. observed Goodhart/coding-agent effects;
5. calibrated or retired noisy signals;
6. explicit `docs/README.md` precedence change;
7. final required GitHub integration proof.

A green calibration PR alone is insufficient.

## Definition of Done

The engineering-quality system is ready for normative promotion only when we can defend all of these statements with evidence:

- direct architecture boundaries fail precisely and with actionable remediation;
- maintainability metrics do not force mechanical splitting or wrapper extraction;
- new module coupling is visible without creating numeric coupling cliffs;
- coding agents are explicitly warned not to hide dependencies to improve fan-out;
- healthy high-fan-out orchestration can remain healthy when semantically justified;
- baselines and evidence describe actual repository state reproducibly;
- semantic review cannot override deterministic invariants;
- governance cost remains proportionate to the risks protected;
- architecture can evolve through explicit contract change rather than implementation hacks.
