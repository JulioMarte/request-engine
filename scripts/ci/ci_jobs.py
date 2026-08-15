#!/usr/bin/env python3
"""Canonical executable CI job definitions shared by GitHub Actions and local CI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    command: str
    always: bool = False
    timeout_seconds: int = 900


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
        Step("modules", "Module unit tests", "uv run pytest tests/modules -q"),
    ),
    "postgres-v2-history": (
        Step(
            "v2-design-chain",
            "Apply historical V2 design chain",
            "bash scripts/db/apply_design_chain.sh",
        ),
    ),
    "postgres-v3-bootstrap-proof": (
        Step(
            "v3-bootstrap-proof",
            "Prove repeated clean V3 candidate bootstrap",
            "bash scripts/db/prove_v3_candidate_bootstrap.sh",
            timeout_seconds=1200,
        ),
    ),
    "postgres-v3-candidate": (
        Step(
            "v3-bootstrap",
            "Apply clean V3 candidate as bootstrap principal",
            "bash scripts/db/apply_v3_candidate.sh",
        ),
        Step("uv-sync", "Resolve test environment", "uv sync --all-groups"),
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
            "V3 PostgreSQL invariant, race, and vertical tests",
            "uv run pytest tests/db tests/integration/v3_first_vertical "
            "tests/integration/v3_booking_core tests/integration/v3_booking_commitments "
            "tests/integration/v3_slot_offer_recovery tests/integration/v3_reservation_lifecycle "
            "tests/integration/v3_worker_runtime -q -m postgres",
            timeout_seconds=2400,
        ),
        Step(
            "mutation-probes",
            "Kill critical mutations",
            "uv run python scripts/release/run_v3_mutation_probes.py",
            timeout_seconds=1800,
        ),
        Step(
            "evidence-manifest",
            "Generate executable release evidence manifest",
            "uv run python scripts/release/build_v3_evidence_manifest.py "
            "--output .phase6/v3-evidence-manifest.json",
            always=True,
        ),
    ),
}


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _emit(line: str, handle: object | None) -> None:
    print(line, end="", flush=True)
    if handle is not None:
        handle.write(line)
        handle.flush()


def _run_step(
    step: Step,
    *,
    env: Mapping[str, str],
    log_dir: Path | None,
) -> dict[str, object]:
    started = time.monotonic()
    log_path = log_dir / f"{_safe_name(step.key)}.log" if log_dir else None
    handle = log_path.open("w", encoding="utf-8", newline="\n") if log_path else None
    _emit(f"\n--- {step.name} [{step.key}] ---\n", handle)
    _emit(f"$ {step.command}\n", handle)

    process = subprocess.Popen(
        ["bash", "-lc", f"set -o pipefail; {step.command}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(env),
        bufsize=1,
    )
    timed_out = False
    selector = selectors.DefaultSelector()
    try:
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + step.timeout_seconds
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                process.kill()
                break
            for key, _ in selector.select(timeout=min(0.25, remaining)):
                line = key.fileobj.readline()
                if line:
                    _emit(line, handle)
        if process.stdout is not None:
            for line in process.stdout:
                _emit(line, handle)
        returncode = process.wait()
    finally:
        selector.close()
        if handle is not None:
            handle.close()

    elapsed = round(time.monotonic() - started, 3)
    status = "TIMEOUT" if timed_out else ("PASS" if returncode == 0 else "FAIL")
    print(f"[{status}] {step.name} ({elapsed}s)", flush=True)
    return {
        "key": step.key,
        "name": step.name,
        "command": step.command,
        "status": status,
        "returncode": returncode,
        "seconds": elapsed,
        "timeout_seconds": step.timeout_seconds,
        "log": str(log_path) if log_path else None,
    }


def execute_job(
    job: str,
    *,
    only_steps: set[str] | None = None,
    log_dir: Path | None = None,
    summary_output: Path | None = None,
) -> int:
    if job not in JOBS:
        raise ValueError(f"Unknown CI job: {job}")
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    failed = False
    results: list[dict[str, object]] = []
    for step in JOBS[job]:
        if only_steps is not None and step.key not in only_steps:
            continue
        if failed and not step.always:
            results.append(
                {
                    "key": step.key,
                    "name": step.name,
                    "command": step.command,
                    "status": "SKIP",
                    "returncode": None,
                    "seconds": 0,
                    "timeout_seconds": step.timeout_seconds,
                    "log": None,
                }
            )
            continue
        result = _run_step(step, env=env, log_dir=log_dir)
        results.append(result)
        if result["status"] != "PASS" and not step.always:
            failed = True

    if summary_output:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps({"job": job, "steps": results}, indent=2) + "\n",
            encoding="utf-8",
        )
    return 1 if any(item["status"] in {"FAIL", "TIMEOUT"} for item in results) else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", choices=sorted(JOBS))
    parser.add_argument("--step", action="append", dest="steps")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--list-jobs", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_jobs:
        for job in JOBS:
            print(job)
        return 0
    if args.job is None:
        raise SystemExit("job is required unless --list-jobs is used")
    if args.list:
        for step in JOBS[args.job]:
            print(f"{step.key}\t{step.name}")
        return 0
    try:
        return execute_job(
            args.job,
            only_steps=set(args.steps) if args.steps else None,
            log_dir=args.log_dir,
            summary_output=args.summary_output,
        )
    except KeyboardInterrupt:
        print("CI job interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
