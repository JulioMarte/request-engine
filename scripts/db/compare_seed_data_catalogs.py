from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _first_difference(expected: Any, actual: Any, path: str = "$") -> dict[str, Any] | None:
    if type(expected) is not type(actual):
        return {"path": path, "kind": "type_mismatch", "expected": expected, "actual": actual}
    if isinstance(expected, dict):
        keys = sorted(set(expected) | set(actual))
        for key in keys:
            if key not in expected:
                return {"path": f"{path}.{key}", "kind": "unexpected_key"}
            if key not in actual:
                return {"path": f"{path}.{key}", "kind": "missing_key"}
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return {
                "path": path,
                "kind": "length_mismatch",
                "expected_length": len(expected),
                "actual_length": len(actual),
            }
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if expected != actual:
        return {"path": path, "kind": "value_mismatch", "expected": expected, "actual": actual}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare deterministic seed/reference catalogs")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected = _load(args.expected)
    actual = _load(args.actual)
    difference = _first_difference(expected, actual)
    result = {
        "equivalent": difference is None,
        "first_difference": difference,
        "expected_counts": expected.get("counts"),
        "actual_counts": actual.get("counts"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if difference is not None:
        raise SystemExit("seed/reference catalogs are not equivalent")


if __name__ == "__main__":
    main()
