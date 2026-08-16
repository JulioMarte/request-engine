#!/usr/bin/env python3
"""Prove release PostgreSQL tests do not depend on canonical collection order."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Final, cast

from v3_scratch_database import ScratchDatabaseError, fresh_v3_database

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
)


def _collect_node_ids() -> tuple[list[str], list[str]]:
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
    if result.returncode != 0:
        raise RuntimeError("pytest collection failed:\n" + "\n".join(output[-80:]))
    node_ids = [line.strip() for line in output if "::" in line and not line.startswith(" ")]
    if not node_ids:
        raise RuntimeError("pytest collection returned no PostgreSQL release tests")
    return node_ids, output


def _run_reverse(node_ids: list[str]) -> dict[str, object]:
    command = [
        "uv",
        "run",
        "pytest",
        *reversed(node_ids),
        "-q",
        "--tb=short",
        "--maxfail=1",
    ]
    started = time.monotonic()
    try:
        with fresh_v3_database("request_engine_v3_reverse") as env:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
    except ScratchDatabaseError as exc:
        return {
            "status": "FAIL",
            "returncode": 2,
            "seconds": round(time.monotonic() - started, 3),
            "output_tail": str(exc).splitlines()[-100:],
        }
    elapsed = round(time.monotonic() - started, 3)
    output = (result.stdout + result.stderr).strip().splitlines()
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "returncode": result.returncode,
        "seconds": elapsed,
        "output_tail": output[-100:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        node_ids, collection_output = _collect_node_ids()
    except RuntimeError as exc:
        payload = {
            "status": "FAIL",
            "phase": "collection",
            "error": str(exc),
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(str(exc))
        return 1

    reverse = _run_reverse(node_ids)
    payload = {
        "status": reverse["status"],
        "phase": "reverse-order",
        "node_count": len(node_ids),
        "canonical_first": node_ids[0],
        "canonical_last": node_ids[-1],
        "reverse_first": node_ids[-1],
        "reverse_last": node_ids[0],
        "collection_tail": collection_output[-20:],
        "reverse": reverse,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if reverse["status"] == "PASS":
        print(
            f"V3 test order independence passed for {len(node_ids)} PostgreSQL tests "
            f"({reverse['seconds']}s reverse-order run)."
        )
        return 0

    print(
        "V3 test order independence failed during reverse execution: "
        f"{len(node_ids)} collected tests."
    )
    for line in cast(list[str], reverse["output_tail"]):
        print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
