# Engineering-quality semantic review calibration

This directory contains versioned evidence used to evaluate the probabilistic semantic-review layer without turning model opinion into merge authority.

## Files

- `pilot-observations.v1.json` — actual model review observations recorded against specific repository SHAs.
- `reviewer-fixer-evidence.v1.json` — before/review/fix/re-proof examples with concrete commits and CI evidence where available.

Generated CI output lives under `.ci/calibration/` and is uploaded with the Python quality evidence artifact. Generated data is not committed back into the repository.

## Human/model agreement rule

A human label is data only when an actual human supplied it.

Do not infer `human_verdict` from a merge, approval silence, a green test, a model recommendation being applied, or repository-owner acceptance of the broader quality policy.

Until a human reviews a pilot case, its record remains:

```json
{
  "human_verdict": null,
  "human_reviewer": null,
  "human_rationale": null
}
```

`scripts/ci/summarize_quality_calibration.py` intentionally emits no agreement or false-positive percentage until genuine human evidence exists. Missing labels are never imputed from model output.

## Separate verdict agreement from signal usefulness

Exact model/human agreement is not enough to judge a guardrail. A model may choose a different semantic verdict while the underlying signal was still useful, or may happen to choose the same verdict even when the metric was a poor trigger.

When an actual human disposes a case, the record MAY add:

```json
{
  "human_disposition": "TRUE_POSITIVE | FALSE_POSITIVE | ACCEPTED_TRADEOFF | INSUFFICIENT_CONTEXT",
  "action_taken": "NONE | REFACTOR | ARCHITECTURE_CHANGE | POLICY_CHANGE | DEFERRED",
  "post_change_outcome": "NOT_APPLICABLE | IMPROVED | NEUTRAL | WORSENED | UNKNOWN",
  "gaming_observed": false
}
```

These fields are invalid unless `human_verdict` is also genuinely populated. CI validates that relationship so model output cannot manufacture human usefulness evidence.

The generated calibration summary reports independently:

- model verdict counts;
- human verdict counts;
- exact agreement and confusion matrix;
- true-positive / false-positive / accepted-trade-off dispositions;
- actions actually taken;
- post-change outcomes;
- observed metric-gaming cases;
- still-unlabeled cases.

A future proposal to strengthen a heuristic should use these human dispositions and outcomes, not merely the fact that the signal fired or that a refactor reduced a metric.

## Pilot interpretation

The pilot is useful when it demonstrates both kinds of outcome:

- a detector can surface a real concern that warrants remediation;
- a detector can surface a healthy outlier that should remain unchanged.

A reviewer that always recommends refactoring is considered miscalibrated.

## Before/after evidence

A remediation record is not complete because a metric decreased. It must identify:

1. the reviewed candidate/case;
2. before SHA;
3. semantic verdict and protected property;
4. fixer commit/patch;
5. post-change facts;
6. deterministic re-proof and exact tested tree;
7. any remaining unrelated failure;
8. whether navigation/coupling or suppression pressure worsened even if the original metric improved.

Reviewer and fixer roles remain distinct even when the same automation system invokes both phases.
