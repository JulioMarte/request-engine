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

`scripts/ci/summarize_quality_calibration.py` intentionally emits:

```text
paired_observations = 0
exact_agreement_rate = null
```

when no genuine paired labels exist. This is valid calibration output, not missing-data fabrication.

When human labels are added, the same script reports model/human verdict counts, exact agreement, a confusion matrix, and remaining unlabeled case IDs.

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
6. deterministic re-proof and exact head;
7. any remaining unrelated failure.

Reviewer and fixer roles remain distinct even when the same automation system invokes both phases.
