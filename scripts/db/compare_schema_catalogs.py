from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _normalized_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: dict[tuple[str, str], int] = {}
    normalized: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["schema_name"]), str(row["relation_name"]))
        position = positions.get(key, 0) + 1
        positions[key] = position
        normalized.append({**row, "ordinal": position})
    return normalized


def _normalize(catalog: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(catalog)
    columns = cast(list[dict[str, Any]], catalog.get("columns", []))
    normalized["columns"] = _normalized_columns(columns)
    return normalized


def _first_difference(
    expected: dict[str, Any], actual: dict[str, Any]
) -> dict[str, object] | None:
    keys = sorted(set(expected) | set(actual))
    for key in keys:
        if key not in expected:
            return {"section": key, "kind": "unexpected_section"}
        if key not in actual:
            return {"section": key, "kind": "missing_section"}
        if expected[key] == actual[key]:
            continue
        expected_value = expected[key]
        actual_value = actual[key]
        if isinstance(expected_value, list) and isinstance(actual_value, list):
            limit = min(len(expected_value), len(actual_value))
            for index in range(limit):
                if expected_value[index] != actual_value[index]:
                    return {
                        "section": key,
                        "kind": "value_mismatch",
                        "index": index,
                        "expected": expected_value[index],
                        "actual": actual_value[index],
                    }
            return {
                "section": key,
                "kind": "length_mismatch",
                "expected_length": len(expected_value),
                "actual_length": len(actual_value),
            }
        return {
            "section": key,
            "kind": "value_mismatch",
            "expected": expected_value,
            "actual": actual_value,
        }
    return None


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, object]:
    difference = _first_difference(_normalize(expected), _normalize(actual))
    return {
        "equivalent": difference is None,
        "first_difference": difference,
        "expected_counts": expected.get("counts"),
        "actual_counts": actual.get("counts"),
        "normalizations": [
            "column ordinals are densified per relation to ignore DROP COLUMN attnum gaps"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two effective schema catalogs")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = compare(_load(args.expected), _load(args.actual))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not result["equivalent"]:
        raise SystemExit("effective schema catalogs are not equivalent")


if __name__ == "__main__":
    main()
