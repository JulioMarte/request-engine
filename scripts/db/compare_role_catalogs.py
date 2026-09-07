from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, object]:
    if expected == actual:
        return {
            "equivalent": True,
            "first_difference": None,
            "expected_counts": expected.get("counts"),
            "actual_counts": actual.get("counts"),
        }

    keys = sorted(set(expected) | set(actual))
    first = next(key for key in keys if expected.get(key) != actual.get(key))
    return {
        "equivalent": False,
        "first_difference": {
            "section": first,
            "expected": expected.get(first),
            "actual": actual.get(first),
        },
        "expected_counts": expected.get("counts"),
        "actual_counts": actual.get("counts"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare PostgreSQL role catalogs exactly")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = compare(_load(args.expected), _load(args.actual))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not result["equivalent"]:
        raise SystemExit("PostgreSQL role catalogs are not equivalent")


if __name__ == "__main__":
    main()
