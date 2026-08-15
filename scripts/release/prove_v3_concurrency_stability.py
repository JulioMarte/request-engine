#!/usr/bin/env python3
"""Repeat the critical V3 concurrency suite to reject one-shot/flaky race evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Final

from v3_scratch_database import ScratchDatabaseError, fresh_v3_database

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
TARGETS: Final = (
    "tests/db",
    "tests/integration/v3_first_vertical",
    "tests/integration/v3_booking_core",
    "tests/integration/v3_booking_commitments",
    "tests/integration/v3_slot_offer_recovery",
    "tests/integration/v3_reservation_lifecycle",
    "tests/integration/v3_worker_runtime",
)


def _run_round(round_number: int) -> dict[str, object]:
    command = [
        "uv",
        "run",
        "pytest",
        *TARGETS,
        "-q",
        "-m",
        "postgres and concurrency",
        "--tb=short",
        "--maxfail=1",
    ]
    started = time.monotonic()
    try:
        with fresh_v3_database("request_engine_concurrency") as scratch_env:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=scratch_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
    except ScratchDatabaseError as exc:
        elapsed = round(time.monotonic() - started, 3)
        return {
            "round": round_number,
            "status": "FAIL",
            "returncode": 2,
            "seconds": elapsed,
            "output_tail": str(exc).splitlines()[-80:],
        }
    elapsed = round(time.monotonic() - started, 3)
    output = (result.stdout + result.stderr).strip().splitlines()
    return {
        "round": round_number,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "returncode": result.returncode,
        "seconds": elapsed,
        "output_tail": output[-80:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 2 <= args.rounds <= 10:
        raise SystemExit("--rounds must be between 2 and 10")

    rounds: list[dict[str, object]] = []
    for round_number in range(1, args.rounds + 1):
        result = _run_round(round_number)
        rounds.append(result)
        if result["status"] != "PASS":
            break

    completed_all_rounds = len(rounds) == args.rounds
    all_passed = all(result["status"] == "PASS" for result in rounds)
    payload = {
        "status": "PASS" if completed_all_rounds and all_passed else "FAIL",
        "requested_rounds": args.rounds,
        "completed_rounds": len(rounds),
        "selector": "postgres and concurrency",
        "targets": list(TARGETS),
        "rounds": rounds,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if payload["status"] == "PASS":
        total_seconds = sum(float(result["seconds"]) for result in rounds)
        print(
            f"V3 concurrency stability passed {args.rounds}/{args.rounds} rounds "
            f"({total_seconds:.3f}s)."
        )
        return 0

    failed = rounds[-1]
    print(
        "V3 concurrency stability failed: "
        f"round {failed['round']}/{args.rounds}, returncode={failed['returncode']}"
    )
    for line in failed["output_tail"]:
        print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
