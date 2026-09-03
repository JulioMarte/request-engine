from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path("docs/engineering-quality/calibration/pilot-observations.v1.json")
DEFAULT_OUTPUT = Path(".ci/calibration/human-model-summary.json")
HUMAN_DISPOSITIONS = {
    "TRUE_POSITIVE",
    "FALSE_POSITIVE",
    "ACCEPTED_TRADEOFF",
    "INSUFFICIENT_CONTEXT",
}
ACTIONS = {"NONE", "REFACTOR", "ARCHITECTURE_CHANGE", "POLICY_CHANGE", "DEFERRED"}
POST_CHANGE_OUTCOMES = {"NOT_APPLICABLE", "IMPROVED", "NEUTRAL", "WORSENED", "UNKNOWN"}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration input must be a JSON object")
    return payload


def _validate_human_evidence(item: dict[str, Any], case_id: str) -> None:
    human = item.get("human_verdict")
    human_fields = {
        "human_disposition": HUMAN_DISPOSITIONS,
        "action_taken": ACTIONS,
        "post_change_outcome": POST_CHANGE_OUTCOMES,
    }
    supplied = any(item.get(field) is not None for field in (*human_fields, "gaming_observed"))
    if supplied and not (isinstance(human, str) and human):
        raise ValueError(f"{case_id}: human outcome fields require a genuine human_verdict")
    for field, allowed in human_fields.items():
        value = item.get(field)
        if value is not None and value not in allowed:
            raise ValueError(f"{case_id}: unsupported {field}={value!r}")
    gaming = item.get("gaming_observed")
    if gaming is not None and not isinstance(gaming, bool):
        raise ValueError(f"{case_id}: gaming_observed must be boolean or null")


def summarize(payload: dict[str, Any]) -> dict[str, object]:
    raw = payload.get("observations", [])
    observations = raw if isinstance(raw, list) else []
    model_counts: Counter[str] = Counter()
    human_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    paired = 0
    agreed = 0
    gaming_observed_count = 0
    gaming_labeled_count = 0
    pending_human: list[str] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", "<unknown>"))
        _validate_human_evidence(item, case_id)
        model = item.get("model_verdict")
        human = item.get("human_verdict")
        if isinstance(model, str):
            model_counts[model] += 1
        if isinstance(human, str) and human:
            human_counts[human] += 1
            if isinstance(model, str):
                paired += 1
                matrix[model][human] += 1
                if model == human:
                    agreed += 1
            disposition = item.get("human_disposition")
            action = item.get("action_taken")
            outcome = item.get("post_change_outcome")
            if isinstance(disposition, str):
                disposition_counts[disposition] += 1
            if isinstance(action, str):
                action_counts[action] += 1
            if isinstance(outcome, str):
                outcome_counts[outcome] += 1
            gaming = item.get("gaming_observed")
            if isinstance(gaming, bool):
                gaming_labeled_count += 1
                if gaming:
                    gaming_observed_count += 1
        else:
            pending_human.append(case_id)
    agreement_rate = round(agreed / paired, 4) if paired else None
    false_positive_count = disposition_counts.get("FALSE_POSITIVE", 0)
    disposition_total = sum(disposition_counts.values())
    false_positive_rate = (
        round(false_positive_count / disposition_total, 4) if disposition_total else None
    )
    return {
        "schema_version": "human-model-calibration-summary/v2",
        "source_schema": payload.get("schema_version"),
        "total_model_observations": sum(model_counts.values()),
        "human_labeled_observations": sum(human_counts.values()),
        "paired_observations": paired,
        "exact_agreement_count": agreed,
        "exact_agreement_rate": agreement_rate,
        "model_verdict_counts": dict(sorted(model_counts.items())),
        "human_verdict_counts": dict(sorted(human_counts.items())),
        "human_disposition_counts": dict(sorted(disposition_counts.items())),
        "action_taken_counts": dict(sorted(action_counts.items())),
        "post_change_outcome_counts": dict(sorted(outcome_counts.items())),
        "false_positive_rate": false_positive_rate,
        "gaming_labeled_observations": gaming_labeled_count,
        "gaming_observed_count": gaming_observed_count,
        "confusion_matrix": {
            model: dict(sorted(humans.items())) for model, humans in sorted(matrix.items())
        },
        "pending_human_case_ids": pending_human,
        "interpretation": (
            "Model/human agreement and signal usefulness are separate. Missing human labels are "
            "never imputed; false-positive and remediation outcomes are reported only from "
            "explicit human dispositions."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        summary = summarize(_load(args.input))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[QUALITY-CALIBRATION-ERROR] {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "[PASS] semantic-review calibration summary: "
        f"model={summary['total_model_observations']} "
        f"human={summary['human_labeled_observations']} "
        f"paired={summary['paired_observations']} "
        f"agreement={summary['exact_agreement_rate']} "
        f"false_positive_rate={summary['false_positive_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
