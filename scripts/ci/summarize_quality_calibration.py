from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path("docs/engineering-quality/calibration/pilot-observations.v1.json")
DEFAULT_OUTPUT = Path(".ci/calibration/human-model-summary.json")


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration input must be a JSON object")
    return payload


def summarize(payload: dict[str, Any]) -> dict[str, object]:
    raw = payload.get("observations", [])
    observations = raw if isinstance(raw, list) else []
    model_counts: Counter[str] = Counter()
    human_counts: Counter[str] = Counter()
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    paired = 0
    agreed = 0
    pending_human: list[str] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", "<unknown>"))
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
        else:
            pending_human.append(case_id)
    agreement_rate = round(agreed / paired, 4) if paired else None
    return {
        "schema_version": "human-model-calibration-summary/v1",
        "source_schema": payload.get("schema_version"),
        "total_model_observations": sum(model_counts.values()),
        "human_labeled_observations": sum(human_counts.values()),
        "paired_observations": paired,
        "exact_agreement_count": agreed,
        "exact_agreement_rate": agreement_rate,
        "model_verdict_counts": dict(sorted(model_counts.items())),
        "human_verdict_counts": dict(sorted(human_counts.items())),
        "confusion_matrix": {
            model: dict(sorted(humans.items())) for model, humans in sorted(matrix.items())
        },
        "pending_human_case_ids": pending_human,
        "interpretation": (
            "No agreement percentage is emitted until at least one genuine human disposition "
            "exists; missing human labels are never imputed from model output."
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
        f"agreement={summary['exact_agreement_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
