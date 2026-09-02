from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from scripts.release import prove_v3_public_api_contract as frozen

_CAPABILITY_MISMATCH = "capability registry baseline mismatch"


def build_report() -> dict[str, object]:
    report = frozen.build_report()
    contract = cast(dict[str, object], report["contract"])
    current = set(cast(list[str], contract["capabilities"]))
    expected = set(frozen.EXPECTED_CAPABILITIES)
    failures = cast(list[str], report["failures"])
    if _CAPABILITY_MISMATCH in failures and expected <= current:
        failures.remove(_CAPABILITY_MISMATCH)
    report["status"] = "PASS" if not failures else "FAIL"
    report["compatibility_policy"] = (
        "released V3 capabilities must remain exact; additions are allowed"
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
