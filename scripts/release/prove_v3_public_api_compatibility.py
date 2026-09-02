from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import cast

from scripts.release import prove_v3_public_api_contract as frozen

_CAPABILITY_MISMATCH = "capability registry baseline mismatch"
_LITERAL_ERROR_PREFIX = "frozen V3 public error codes are missing: "
_POST_V3_ERROR_MODULES = (Path("src/request_engine/modules/queue/api/core_error_mapping.py"),)


def _literal_error_codes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "ErrorBody":
            continue
        for keyword in node.keywords:
            if keyword.arg != "code":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                codes.add(value.value)
    return codes


def _extend_literal_error_contract(report: dict[str, object]) -> None:
    contract = cast(dict[str, object], report["contract"])
    current = set(cast(list[str], contract["literal_error_codes"]))
    for path in _POST_V3_ERROR_MODULES:
        current |= _literal_error_codes(path)
    contract["literal_error_codes"] = sorted(current)

    failures = cast(list[str], report["failures"])
    missing = frozen.EXPECTED_LITERAL_ERROR_CODES - current
    failures[:] = [failure for failure in failures if not failure.startswith(_LITERAL_ERROR_PREFIX)]
    if missing:
        failures.append(_LITERAL_ERROR_PREFIX + ", ".join(sorted(missing)))


def build_report() -> dict[str, object]:
    report = frozen.build_report()
    _extend_literal_error_contract(report)
    contract = cast(dict[str, object], report["contract"])
    current = set(cast(list[str], contract["capabilities"]))
    expected = set(frozen.EXPECTED_CAPABILITIES)
    failures = cast(list[str], report["failures"])
    if _CAPABILITY_MISMATCH in failures and expected <= current:
        failures.remove(_CAPABILITY_MISMATCH)
    report["error_code_count"] = len(
        set(cast(list[str], contract["literal_error_codes"]))
        | set(cast(list[str], contract["shared_error_codes"]))
        | set(cast(list[str], contract["request_helper_error_codes"]))
    )
    report["status"] = "PASS" if not failures else "FAIL"
    report["compatibility_policy"] = (
        "released V3 capabilities and error codes must remain present; post-V3 additions and "
        "module moves are allowed when the compatibility inventory follows the current source"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] != "PASS":
        raise SystemExit(
            "V3 public API compatibility proof failed: "
            + "; ".join(cast(list[str], report["failures"]))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
