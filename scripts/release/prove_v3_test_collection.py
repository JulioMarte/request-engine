#!/usr/bin/env python3
"""Prove every release test file contributes unique pytest nodes to the V3 gate."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
TARGETS: Final = (
    "tests/db",
    "tests/e2e",
    "tests/integration/v3_first_vertical",
    "tests/integration/v3_booking_core",
    "tests/integration/v3_booking_commitments",
    "tests/integration/v3_slot_offer_recovery",
    "tests/integration/v3_reservation_lifecycle",
    "tests/integration/v3_worker_runtime",
    "tests/integration/v3_delivery",
)


def _expected_files() -> list[str]:
    files: set[str] = set()
    for target in TARGETS:
        root = REPO_ROOT / target
        files.update(path.relative_to(REPO_ROOT).as_posix() for path in root.glob("test_*.py"))
    return sorted(files)


def _collect() -> tuple[int, list[str], list[str]]:
    command = [
        "uv",
        "run",
        "pytest",
        *TARGETS,
        "-q",
        "-m",
        "postgres",
        "--collect-only",
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (result.stdout + result.stderr).strip().splitlines()
    node_ids = [line.strip() for line in output if "::" in line and not line.startswith(" ")]
    return result.returncode, node_ids, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected_files = _expected_files()
    returncode, node_ids, output = _collect()
    counts = Counter(node_ids)
    duplicates = sorted(node_id for node_id, count in counts.items() if count != 1)
    collected_files = sorted({node_id.split("::", 1)[0] for node_id in node_ids})
    missing_files = sorted(set(expected_files) - set(collected_files))
    unexpected_files = sorted(set(collected_files) - set(expected_files))

    errors: list[str] = []
    if returncode != 0:
        errors.append(f"pytest collection returned {returncode}")
    if not node_ids:
        errors.append("pytest collected zero PostgreSQL release nodes")
    if duplicates:
        errors.append(f"duplicate node ids: {duplicates[:20]}")
    if missing_files:
        errors.append(f"release test files with no collected postgres nodes: {missing_files}")
    if unexpected_files:
        errors.append(f"unexpected collected test files: {unexpected_files}")
    if not any(path.startswith("tests/e2e/") for path in collected_files):
        errors.append("no E2E test was collected into the PostgreSQL release gate")

    payload = {
        "status": "PASS" if not errors else "FAIL",
        "node_count": len(node_ids),
        "expected_file_count": len(expected_files),
        "collected_file_count": len(collected_files),
        "errors": errors,
        "expected_files": expected_files,
        "collected_files": collected_files,
        "collection_tail": output[-40:],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if errors:
        print("V3 pytest collection integrity failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "V3 pytest collection integrity passed: "
        f"{len(node_ids)} nodes from {len(collected_files)} release files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
