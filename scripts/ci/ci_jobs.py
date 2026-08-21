#!/usr/bin/env python3
"""Canonical executable CI job definitions shared by GitHub Actions and local CI."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    command: str
    always: bool = False
    timeout_seconds: int = 900


NORMALIZE_SHELL = Step(
    "normalize-shell-line-endings",
    "Normalize shell line endings",
    "python scripts/ci/normalize_ci_line_endings.py",
)

JOBS: dict[str, tuple[Step, ...]] = {
    "python-quality": (
        Step("uv-sync", "Resolve development environment", "uv sync --all-groups"),
        Step("lockfile", "Lockfile consistency", "uv lock --check"),
        Step("ruff-lint", "Ruff lint", "uv run ruff check ."),
        Step("ruff-format", "Ruff format check", "uv run ruff format --diff ."),
        Step("pyright", "Pyright", "uv run pyright"),
        Step(
            "secret-scan",
            "High-confidence secret scan",
            "uv run python scripts/release/scan_v3_secrets.py",
        ),
        Step(
            "python-sast",
            "Python security static analysis",
            "uv run python scripts/release/scan_v3_python_security.py",
        ),
        Step(
            "dependency-audit",
            "Dependency vulnerability audit",
            "uv run --with pip-audit==2.10.1 pip-audit --local",
        ),
        Step("architecture", "Architecture tests", "uv run pytest tests/architecture -q"),
        Step("unit", "Unit tests", "uv run pytest tests/unit -q"),
        Step("modules", "Module unit tests", "uv run pytest tests/modules -q"),
    ),
    "postgres-v2-history": (
        NORMALIZE_SHELL,
        Step(
            "v2-design-chain",
            "Apply historical V2 design chain",
            "bash scripts/db/apply_design_chain.sh",
        ),
    ),
    "postgres-v3-bootstrap-proof": (
        NORMALIZE_SHELL,
        Step(
            "v3-bootstrap-proof",
            "Prove repeated clean V3 candidate bootstrap",
            "bash scripts/db/prove_v3_candidate_bootstrap.sh",
            timeout_seconds=1200,
        ),
    ),
    "postgres-v3-candidate": (
        NORMALIZE_SHELL,
        Step(
            "v3-bootstrap",
            "Apply clean V3 candidate as bootstrap principal",
            "bash scripts/db/apply_v3_candidate.sh",
        ),
        Step("uv-sync", "Resolve test environment", "uv sync --all-groups"),
        Step(
            "test-quality-audit",
            "Audit V3 test quality",
            "mkdir -p .phase6 && uv run python scripts/release/audit_v3_test_quality.py "
            "--output .phase6/v3-test-quality.json",
        ),
        Step(
            "test-collection-integrity",
            "Prove V3 pytest collection integrity",
            "uv run python scripts/release/prove_v3_test_collection.py "
            "--output .phase6/v3-test-collection.json",
        ),
        Step(
            "schema-fingerprint",
            "Generate V3 schema fingerprint",
            "mkdir -p .phase6 && uv run python scripts/db/v3_schema_fingerprint.py "
            "--json-output .phase6/v3-schema.json --sha-output .phase6/v3-schema.sha256 "
            "&& cat .phase6/v3-schema.sha256",
        ),
        Step(
            "catalog-audit",
            "Audit V3 PostgreSQL catalog",
            "uv run python scripts/db/audit_v3_catalog.py "
            "--json-output .phase6/v3-catalog-audit.json",
        ),
        Step(
            "worker-query-plans",
            "Prove measured worker query plans",
            "uv run python scripts/release/prove_v3_worker_query_plans.py "
            "--output .phase6/v3-worker-query-plans.json",
        ),
        Step(
            "queue-query-plans",
            "Prove measured Queue and SlotOffer query plans",
            "uv run python scripts/release/prove_v3_queue_query_plans.py "
            "--output .phase6/v3-queue-query-plans.json",
        ),
        Step(
            "booking-query-plans",
            "Prove measured Booking and capacity query plans",
            "uv run python scripts/release/prove_v3_booking_query_plans_bound.py "
            "--output .phase6/v3-booking-query-plans.json",
        ),
        Step(
            "public-api-contract",
            "Prove frozen V3 public API contract",
            "uv run python scripts/release/prove_v3_public_api_contract.py "
            "--output .phase6/v3-public-api-contract.json",
        ),
        Step(
            "initial-equivalence",
            "Generate and prove 0001 initial candidate equivalence",
            "uv run python scripts/db/build_v3_initial_candidate.py "
            "--output .phase6/0001_initial.candidate.sql "
            "&& uv run bash scripts/db/prove_v3_initial_equivalence.sh "
            "| tee .phase6/v3-initial-equivalence.txt",
            timeout_seconds=1200,
        ),
        Step(
            "v3-tests",
            "V3 PostgreSQL invariant, E2E, race, and vertical tests",
            "mkdir -p .phase6 && uv run pytest tests/db tests/e2e "
            "tests/integration/v3_first_vertical tests/integration/v3_booking_core "
            "tests/integration/v3_booking_commitments tests/integration/v3_slot_offer_recovery "
            "tests/integration/v3_reservation_lifecycle tests/integration/v3_worker_runtime "
            "tests/integration/v3_delivery "
            "-q -m postgres --tb=short --durations=20 "
            "--junitxml=.phase6/v3-tests-junit.xml",
            timeout_seconds=2400,
        ),
        Step(
            "concurrency-stability",
            "Repeat critical V3 concurrency proofs",
            "uv run python scripts/release/prove_v3_concurrency_stability.py "
            "--rounds 3 --output .phase6/v3-concurrency-stability.json",
            timeout_seconds=2400,
        ),
        Step(
            "test-order-independence",
            "Prove V3 PostgreSQL tests are order independent",
            "uv run python scripts/release/prove_v3_test_order_independence.py "
            "--output .phase6/v3-test-order-independence.json",
            timeout_seconds=2400,
        ),
        Step(
            "mutation-probes",
            "Kill critical mutations",
            "uv run python scripts/release/run_v3_mutation_probes.py "
            "--output .phase6/v3-mutation-probes.json",
            timeout_seconds=1800,
        ),
        Step(
            "adversarial-failure-proof",
            "Compose mandatory G18 adversarial and failure proof",
            "uv run python scripts/release/prove_v3_adversarial_failure.py "
            "--output .phase6/v3-adversarial-failure-proof.json",
        ),
        Step(
            "evidence-manifest",
            "Generate executable release evidence manifest",
            "uv run python scripts/release/build_v3_evidence_manifest.py "
            "--output .phase6/v3-evidence-manifest.json",
            always=True,
        ),
        Step(
            "evidence-validity",
            "Require valid V3 candidate evidence",
            "uv run python scripts/release/build_v3_evidence_manifest.py "
            "--output .phase6/v3-evidence-manifest.json --require-valid",
        ),
    ),
}

_FAILURE_MARKERS = (
    "error:",
    "error ",
    "fatal:",
    "failed",
    "failure",
    "traceback",
    "assertionerror",
    "exception:",
    "timeout",
    "permission denied",
    "syntax error",
    "does not exist",
    "violates",
)
_FAILURE_CONTEXT_LINES = 6
_FAILURE_TAIL_LINES = 60
_FAILURE_SUMMARY_LINES = 25


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _step_log_path(log_dir: Path | None, step: Step) -> Path | None:
    if log_dir is None:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{_safe_name(step.key)}.log"


def _tail_text(lines: Sequence[str], *, limit: int) -> str:
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


def _failure_excerpt(lines: Sequence[str]) -> str:
    if not lines:
        return ""
    lowered = [line.lower() for line in lines]
    marker_indexes = [
        index
        for index, line in enumerate(lowered)
        if any(marker in line for marker in _FAILURE_MARKERS)
    ]
    if marker_indexes:
        index = marker_indexes[-1]
        start = max(0, index - _FAILURE_CONTEXT_LINES)
        end = min(len(lines), index + _FAILURE_CONTEXT_LINES + 1)
        excerpt = list(lines[start:end])
        tail = list(lines[-_FAILURE_TAIL_LINES:])
        if tail and (not excerpt or tail[0] not in excerpt):
            excerpt.extend(["...", *tail])
        return "\n".join(excerpt)
    return _tail_text(lines, limit=_FAILURE_TAIL_LINES)


def _run_step(step: Step, *, log_path: Path | None) -> tuple[int, float, str]:
    started = time.monotonic()
    tail: deque[str] = deque(maxlen=2000)
    output_file = log_path.open("w", encoding="utf-8") if log_path is not None else None
    try:
        process = subprocess.Popen(
            step.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        if process.stdout is None:
            raise RuntimeError("subprocess stdout pipe was not created")

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            deadline = started + step.timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    timeout_message = f"timeout after {step.timeout_seconds}s"
                    tail.append(timeout_message)
                    if output_file is not None:
                        output_file.write(timeout_message + "\n")
                        output_file.flush()
                    return 124, time.monotonic() - started, _failure_excerpt(list(tail))

                events = selector.select(timeout=min(0.25, remaining))
                for key, _ in events:
                    line = key.fileobj.readline()
                    if line:
                        clean = line.rstrip("\n")
                        tail.append(clean)
                        if output_file is not None:
                            output_file.write(line)
                            output_file.flush()
                    elif process.poll() is not None:
                        break

                if process.poll() is not None:
                    for line in process.stdout:
                        clean = line.rstrip("\n")
                        tail.append(clean)
                        if output_file is not None:
                            output_file.write(line)
                    if output_file is not None:
                        output_file.flush()
                    break
        finally:
            selector.close()

        return (
            process.returncode,
            time.monotonic() - started,
            _failure_excerpt(list(tail)),
        )
    finally:
        if output_file is not None:
            output_file.close()


def run_job(
    job_name: str,
    *,
    summary_output: Path | None = None,
    log_dir: Path | None = None,
) -> int:
    steps = JOBS[job_name]
    results: list[dict[str, object]] = []
    blocked = False
    exit_code = 0
    for step in steps:
        if blocked and not step.always:
            print(f"[SKIP] {step.name}")
            results.append(
                {
                    "key": step.key,
                    "name": step.name,
                    "status": "skipped",
                    "command": step.command,
                }
            )
            continue
        log_path = _step_log_path(log_dir, step)
        code, duration, excerpt = _run_step(step, log_path=log_path)
        status = "passed" if code == 0 else "failed"
        results.append(
            {
                "key": step.key,
                "name": step.name,
                "status": status,
                "exit_code": code,
                "duration_seconds": round(duration, 3),
                "command": step.command,
                "log_path": str(log_path) if log_path is not None else None,
                "failure_excerpt": excerpt if code != 0 else None,
            }
        )
        if code == 0:
            print(f"[PASS] {step.name} ({duration:.3f}s)")
            continue
        print(f"[FAIL] {step.name} [{step.key}]")
        print(f"  command: {step.command}")
        if excerpt:
            print("  problem:")
            for line in excerpt.splitlines()[:_FAILURE_SUMMARY_LINES]:
                print(f"    {line}")
        if log_path is not None:
            print(f"  full log: {log_path}")
        blocked = True
        exit_code = code

    if summary_output is not None:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps(
                {
                    "job": job_name,
                    "status": "passed" if exit_code == 0 else "failed",
                    "steps": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--log-dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_job(
        args.job,
        summary_output=args.summary_output,
        log_dir=args.log_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
