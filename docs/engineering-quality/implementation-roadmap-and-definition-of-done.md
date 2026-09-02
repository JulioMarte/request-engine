# Engineering Quality Hybrid Review — Current Roadmap and Definition of Done

> **Lifecycle status:** `IMPLEMENTED_FOR_CALIBRATION` / calibration incomplete / normative promotion pending.
>
> **Historical audit base:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.
>
> **Current integration base for PR #110:** `development@21ab0f5872d5ef9c79e7c4b65e283253f40c13b7`.
>
> This file supersedes the earlier roadmap statement that the PR was documentation-only. The branch now contains executable sensors, governance tests, evidence schemas, calibration artifacts, a scoped mega-file circuit breaker, local publish certification, and CI persistence. It remains **not NORMATIVE** until the explicit promotion phase is completed.

## 1. Purpose

This roadmap answers two different questions that must not be conflated:

1. **What has been implemented and can be proven today?**
2. **What evidence is still required before the model may become normative?**

A green implementation PR proves the implementation at one exact SHA. It does not manufacture longitudinal calibration evidence and it does not implicitly ratify architecture policy.

## 2. Target operating model

```text
DETERMINISTIC PROOF
    -> accepted architecture/correctness invariants

DETERMINISTIC SIGNALING
    -> reproducible maintainability facts and candidates

PROBABILISTIC SEMANTIC REVIEW
    -> contextual interpretation with constrained authority

DETERMINISTIC RE-PROOF
    -> independently verify any applied remediation
```

The target property remains:

> Optimizing for green should normally improve cohesion, navigability, local reasoning, encapsulation, and evolvability rather than reward fragmentation or metric gaming.

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
| 0. Policy direction | `ACCEPTED_FOR_CALIBRATION` | deterministic-vs-semantic authority is defined; normative promotion still pending |
| 1. Repository baseline | `IMPLEMENTED_FOR_CALIBRATION` | baseline builder and categorized distributions exist; longitudinal interpretation continues |
| 2. Deterministic sensors | `IMPLEMENTED_FOR_CALIBRATION` | QR-FSIZE, QR-CPLX, QR-NAV and QR-MEGA paths are executable and tested |
| 3. Evidence packets | `IMPLEMENTED_FOR_CALIBRATION` | `quality-scan/v1`, `quality-evidence/v1`, formal schema and validator exist |
| 4. Semantic review pilot | `IMPLEMENTED_FOR_CALIBRATION` | SRP-1/playbook and committed pilot observations exist; more real-PR/human data needed |
| 5. Reviewer/fixer + re-proof | `IMPLEMENTED_FOR_CALIBRATION` | separation rules and before/after evidence exist; deterministic proof remains external authority |
| 6. Calibration | `ACTIVE / INCOMPLETE` | real human labels, longitudinal rates, cost/latency and repeated disagreement data remain incomplete |
| 7. Enforcement alignment | `IMPLEMENTED_FOR_CALIBRATION` | old universal low 120-line HARD behavior is replaced by review signaling plus scoped QR-MEGA; exact-head CI required for each actual merge candidate |
| 7A. Local publish certification | `IMPLEMENTED_FOR_CALIBRATION` | exact-SHA pre-push workflow exists; ergonomics/remote-miss data still being measured |
| 8. Normative promotion | `PENDING` | explicit approval and consolidated normative docs required after calibration |

## 5. Phase 0 — Policy direction

### Implemented

The repository now has an explicit authority model:

```text
accepted deterministic invariant
    > deterministic fact
    > constrained semantic interpretation
    > coding-agent remediation proposal
```

The semantic reviewer cannot waive `INVARIANT_FAILURE`.

File LOC and McCabe are not universal architecture invariants merely because they are easy to measure.

No synthetic maintainability score is used.

### Still required for completion

- explicit normative promotion after calibration;
- consolidated wording in proposal-era documents when their historical framing is no longer useful.

## 6. Phase 1 — Repository baseline

### Implemented

`scripts/ci/build_engineering_quality_baseline.py` produces versioned categorized evidence.

Current deterministic measurement families include:

```text
effective Python file LOC
function LOC
per-function Ruff C901 McCabe
nonblank configuration LOC
```

Categories distinguish production subtypes, tests, scripts, migrations, configuration, and controlled generated exclusions.

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

### Remaining calibration work

- accumulate baseline movement over a representative development interval;
- inspect recurring healthy and unhealthy outliers by category;
- use observations to recalibrate signals rather than convert percentiles directly to policy.

## 7. Phase 2 — Deterministic maintainability sensors

### Implemented

#### QR-FSIZE-001

```text
effective file LOC > 120
    -> REVIEW_CANDIDATE
```

This is a question, not a forced split.

#### QR-CPLX-001

```text
Ruff C901 McCabe > 10
    -> REVIEW_CANDIDATE
```

C901 remains outside the global blocking Ruff selection.

#### QR-NAV-001

Conservative forwarding/re-export/navigation evidence can surface likely fragmentation without asserting that every small boundary file is wrong.

#### QR-MEGA-001

```text
new / crossing / growing handwritten core product Python > 500 eLOC
    -> INVARIANT_FAILURE
```

This is a separately justified extreme circuit breaker, not a universal repository cap.

#### QR-MEGA-GOV-001

An ordinary product implementation cannot rewrite the quality-policy authority judging that same implementation.

### Required properties already protected

- deterministic output for equal source/tool inputs;
- code-category scope;
- fact/interpretation separation;
- fixture tests;
- nonblocking semantics for heuristic candidates;
- controlled generated provenance;
- explicit anti-gaming instructions.

## 8. Phase 3 — Evidence Packet

### Implemented

Discovery and semantic handoff are separate:

```text
quality-scan/v1
    -> run-level discovery

quality-evidence/v1
    -> candidate-level review packet
```

Evidence packets include:

- schema version;
- candidate and trigger IDs;
- repository/base/head SHA;
- scope/module/category/files;
- deterministic facts and deltas;
- architecture/quality result state;
- context manifest;
- review questions;
- provenance/tool versions;
- authority metadata.

The formal JSON Schema is committed and validated in CI.

### Remaining work

Schema evolution must remain versioned and backward-conscious as real pilot data exposes missing fields. Semantic adjectives must not leak into deterministic facts merely for convenience.

## 9. Phase 4 — Semantic review pilot

### Implemented

The SRP-1 playbook requires a reviewer to examine:

- responsibility/cohesion;
- genuine reasoning complexity;
- side effects;
- locality/navigation;
- ownership;
- abstraction value;
- testability;
- metric-gaming risk.

Supported verdicts include:

```text
HEALTHY_AS_IS
REVIEW_CONCERN
REFACTOR_RECOMMENDED
ARCHITECTURE_CONCERN
INSUFFICIENT_CONTEXT
```

Prompt-injection boundaries treat source comments, strings, fixtures, arbitrary Markdown, and generated text as data rather than reviewer authority.

Committed pilot observations exist under `calibration/`.

### Remaining calibration work

- collect more representative real-PR candidates;
- obtain genuine human verdicts for a meaningful sample;
- investigate repeated model/human disagreement rather than invent an arbitrary agreement target;
- measure token/cost/latency where available.

The semantic reviewer remains advisory for heuristic candidates. It is not a probabilistic merge oracle.

## 10. Phase 5 — Reviewer/fixer and re-proof

### Implemented

The process is explicitly:

```text
candidate
-> reviewer
-> disposition
-> separate fixer when remediation is justified
-> patch
-> deterministic sensors again
-> architecture/type/lint/tests again
-> service-heavy proof when affected semantics require it
```

A fixer cannot self-certify success.

Committed reviewer/fixer before-after evidence exists.

### Definition of success

Success is **not**:

```text
LOC went down
C901 went down
file count changed
```

Success requires the protected property to improve or the concern to be resolved **and** independent deterministic proof to remain green.

## 11. Phase 6 — Calibration

### Current state: ACTIVE / INCOMPLETE

This is the principal reason the package is not `NORMATIVE`.

Track at least:

### Trigger usefulness

```text
candidate count by trigger
HEALTHY_AS_IS rate
REVIEW_CONCERN rate
REFACTOR_RECOMMENDED rate
ARCHITECTURE_CONCERN rate
INSUFFICIENT_CONTEXT rate
```

### Genuine human comparison

```text
paired human/model observations
exact agreement where meaningful
confusion/disagreement patterns
human override reasons
```

No human label may be inferred from green CI, merge status, silence, or owner acceptance of the overall policy.

### Gaming indicators

Look for cases such as:

```text
LOC decreases while delegation/file count rises materially
C901 moves across helpers without reducing conceptual complexity
new generic shared/platform abstractions after boundary pressure
new suppressions/exceptions created only to silence quality warnings
```

These are investigation signals, not automatic accusations.

### Cost and ergonomics

Track semantic-review volume, input size, latency/cost where observable, and whether findings are specific enough to act on.

For local publish certification, also track:

```text
certification duration
cache-hit rate
first failing step
bypass/friction reports
local-green -> remote-red misses
```

### Exit condition

Calibration can leave `ACTIVE` only after a representative development interval produces enough real evidence to decide which signals should be retained, modified, narrowed, or retired.

## 12. Phase 7 — Enforcement alignment

### Implemented for calibration

The old low universal shape pressure has been migrated:

```text
historical:
100 target / 120 hard blocker

current calibration model:
>120 -> review candidate
C901 >10 -> review candidate
conservative navigation signals -> review candidate
scoped >500 core mega-file transition -> hard circuit breaker
semantic architecture invariants -> deterministic blockers
```

The repository governance contract and coding-agent instructions describe this distinction.

### Exact-head requirement

No implementation branch is merge-ready merely because an earlier SHA was green.

Before merge:

```text
final branch content
-> exact GitHub PR head SHA
-> full required CI graph
-> every required lane complete
-> only then claim merge readiness
```

Documentation-only final edits count as head changes and therefore require a new exact-head run.

## 13. Phase 7A — Local Publish Certification

### Implemented for calibration

The managed pre-push workflow:

1. resolves each commit-bearing pushed ref to its exact SHA;
2. binds the certificate to the locally known `development` base;
3. starts from a managed bootstrap certifier outside the mutable working tree;
4. creates a temporary detached worktree at the pushed SHA;
5. selects canonical Python-quality step IDs;
6. runs quality-policy separation;
7. persists bounded evidence/logs;
8. aborts normal publication on failure.

The local profile is deliberately faster than full CI. PostgreSQL/current-product, historical compatibility, observability, dependency vulnerability lookup, and other heavy remote proof remain GitHub responsibilities during calibration.

`git push --no-verify` is technically possible because client hooks are not a security boundary. Repository agents are explicitly forbidden from using that bypass to manufacture progress or certification claims.

### Remaining calibration work

Use observed local-vs-remote failure data and duration/friction to decide whether the profile should change. Do not duplicate full CI locally merely for symmetry.

## 14. Phase 8 — Normative promotion

### Current state: PENDING

Normative promotion requires all of the following:

```text
[ ] representative longitudinal calibration exists
[ ] noisy signals have explicit dispositions
[ ] genuine human review data has been sampled
[ ] cost/latency/ergonomics are understood well enough for the intended use
[ ] proposal-era documents are consolidated so current policy is unambiguous
[ ] canonical governance and executable enforcement agree
[ ] explicit architecture/governance approval is recorded
[ ] final promotion change passes exact-head CI
```

A green PR does not check these boxes automatically.

## 15. Current system acceptance simulations

### Cohesive 500-line core file

Expected:

```text
QR-FSIZE-001 candidate
HEALTHY_AS_IS allowed
no forced split
no QR-MEGA-001 at exactly 500
```

### New 501-line scoped core file

Expected:

```text
QR-FSIZE-001 candidate
QR-MEGA-001 INVARIANT_FAILURE
semantic reviewer cannot waive it
```

### Small but genuinely complex orchestration

Expected:

```text
QR-CPLX-001 candidate even when file size is modest
semantic review addresses reasoning/side-effect concern rather than file size
```

### Mechanical split into wrappers

Expected:

```text
lower LOC is not automatic success
navigation/fragmentation evidence may surface
semantic reviewer checks locality and abstraction value
```

### Legitimate one-function boundary adapter

Expected:

```text
shape may be observable
HEALTHY_AS_IS remains valid when ownership/boundary value is real
```

### Direct architecture violation

Expected:

```text
deterministic HARD failure
no LLM waiver
```

### Prompt injection in source

Expected:

```text
source text treated as data
review protocol unchanged
```

### Reviewer lacks context

Expected:

```text
INSUFFICIENT_CONTEXT
no invented architecture conclusion
```

### Fix lowers metrics but breaks tests

Expected:

```text
re-proof fails
no success claim
```

### Same-change exception/self-policy rewrite

Expected:

```text
base-authority or QR-MEGA-GOV protection prevents self-approval
```

## 16. Definition of Done

The migration may be declared **implemented for calibration** when:

```text
[x] direct semantic architecture invariants remain deterministic blockers
[x] file LOC is measured without being universal low HARD design authority
[x] per-function McCabe is measured as a candidate signal
[x] a conservative navigation/fragmentation signal exists
[x] categories distinguish production/tests/scripts/migrations/generated intent
[x] quality scan and candidate packet schemas are distinct and versioned
[x] packets include SHA/provenance/context/architecture result state
[x] HEALTHY_AS_IS is supported
[x] INSUFFICIENT_CONTEXT is supported
[x] source comments/strings cannot redefine reviewer instructions
[x] semantic review cannot override invariant failures
[x] reviewer and fixer are distinct phases
[x] deterministic re-proof is mandatory after remediation
[x] QR-MEGA has scoped base-authorized exception governance
[x] same-change product/policy self-approval is blocked
[x] local commits remain cheap checkpoints
[x] normal local push has exact-SHA publication certification
[x] local certification never substitutes for GitHub exact-head CI
[x] CI persists machine-readable calibration evidence
```

The migration may be declared **NORMATIVE** only when:

```text
[ ] longitudinal calibration is representative
[ ] genuine human comparison data has been sampled
[ ] cost/latency/ergonomics have been reviewed
[ ] trigger changes/retirements from calibration are resolved
[ ] normative surfaces are consolidated and explicitly approved
[ ] canonical governance and implementation agree after that promotion
[ ] exact-head CI proves the promotion change
```

## 17. Final completion test

Ask these questions against the implemented repository:

1. Can a cohesive 500-line core file remain intact without bypassing policy? **YES**.
2. Can a new/crossing/growing 501-line scoped core file enter silently? **NO**.
3. Can a small but difficult function be surfaced despite modest file size? **YES**.
4. Can an LLM approve code that violates a deterministic accepted invariant? **NO**.
5. Can a coding agent claim a refactor succeeded without deterministic re-proof? **NO**.
6. Can local WIP/red commits exist? **YES**.
7. Can normal local publication certify dirty uncommitted content instead of the pushed SHA? **NO**.
8. Can local certification be reported as remote merge proof? **NO**.
9. Can a green implementation PR silently promote this package to `NORMATIVE`? **NO**.

The first eight are executable design properties. The ninth preserves governance integrity.

## 18. Completion statement

The engineering-quality implementation is **operational in calibration** when deterministic tooling proves explicit invariants, deterministic sensors locate maintainability candidates, constrained semantic review interprets those candidates, and deterministic re-verification proves applied remediations while local publication and remote integration evidence remain distinct.

The engineering-quality architecture becomes **normative** only after representative calibration evidence and an explicit governance promotion establish that the implemented mechanisms are useful, not merely functional.
