#!/usr/bin/env python3
"""Canonical executable CI job definitions shared by GitHub Actions and local CI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


def _resolve_bash() -> str:
    if sys.platform != "win32":
        return "bash"
    git_exe = shutil.which("git")
    if git_exe:
        candidate = Path(git_exe).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("bash")
    return found or "bash"


_BASH = _resolve_bash()


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
        Step(
            "file-budget",
            "Python effective line budget",
            "python scripts/ci/check_python_file_budget.py "
            '--base-ref "${FILE_BUDGET_BASE_REF:-HEAD^}"',
        ),
        Step("uv-sync", "Resolve development environment", "uv sync --all-groups"),
        Step("lockfile", "Lockfile consistency", "uv lock --check"),
        Step("ruff-lint", "Ruff lint", "uv run ruff check ."),
        Step("ruff-format", "Ruff format check", "uv run ruff format --diff ."),
        Step("pyright", "Pyright", "uv run pyright"),
        Step(
            "secret-scan",
            "High-confidence secret scan",
            "uv run python scripts/security/scan_secrets.py",
        ),
        Step(
            "python-sast",
            "Python security static analysis",
            "uv run python scripts/security/scan_python_security.py",
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


def _write_log(handle: TextIO | None, line: str) -> None:
    if handle is None:
        return
    handle.write(line)
    handle.flush()


def _failure_excerpt(lines: Sequence[str]) -> list[str]:
    cleaned = [line.rstrip("\n") for line in lines if line.strip()]
    if not cleaned:
        return ["(step produced no output)"]

    summaries = [
        line for line in cleaned if line.lstrip().startswith(("FAILED ", "ERROR ", "E   "))
    ][-_FAILURE_SUMMARY_LINES:]
    marker_indexes = [
        index
        for index, line in enumerate(cleaned)
        if any(marker in line.lower() for marker in _FAILURE_MARKERS)
    ]
    if marker_indexes:
        start = max(0, marker_indexes[-1] - _FAILURE_CONTEXT_LINES)
        context = cleaned[start:]
    else:
        context = cleaned[-_FAILURE_TAIL_LINES:]

    excerpt: list[str] = []
    if summaries:
        excerpt.append("failure summary:")
        excerpt.extend(summaries)
        excerpt.append("last error context:")
    excerpt.extend(context[-_FAILURE_TAIL_LINES:])
    return excerpt[-(_FAILURE_TAIL_LINES + _FAILURE_SUMMARY_LINES + 2) :]


def _print_failure(
    step: Step,
    *,
    status: str,
    lines: Sequence[str],
    log_path: Path | None,
) -> None:
    print(f"[{status}] {step.name} [{step.key}]", flush=True)
    print(f"  command: {step.command}", flush=True)
    print("  problem:", flush=True)
    for line in _failure_excerpt(lines):
        print(f"    {line}", flush=True)
    if log_path is not None:
        print(f"  full log: {log_path}", flush=True)


def _run_step(
    step: Step,
    *,
    env: Mapping[str, str],
    log_dir: Path | None,
    verbose: bool,
) -> dict[str, object]:
    started = time.monotonic()
    log_path = log_dir / f"{_safe_name(step.key)}.log" if log_dir else None
    handle = log_path.open("w", encoding="utf-8", newline="\n") if log_path else None
    tail: deque[str] = deque(maxlen=300)

    _write_log(handle, f"--- {step.name} [{step.key}] ---\n")
    _write_log(handle, f"$ {step.command}\n")
    if verbose:
        print(f"\n--- {step.name} [{step.key}] ---", flush=True)
        print(f"$ {step.command}", flush=True)

    process = subprocess.Popen(
        [_BASH, "-lc", f"set -o pipefail; {step.command}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(env),
        bufsize=1,
    )
    timed_out = False

    def _pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            tail.append(line)
            _write_log(handle, line)
            if verbose:
                print(line, end="", flush=True)

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=step.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    reader.join(timeout=5)
    if handle is not None:
        handle.close()

    elapsed = round(time.monotonic() - started, 3)
    status = "TIMEOUT" if timed_out else ("PASS" if returncode == 0 else "FAIL")
    if status == "PASS":
        print(f"[PASS] {step.name} ({elapsed}s)", flush=True)
    else:
        _print_failure(step, status=status, lines=list(tail), log_path=log_path)
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
    verbose: bool = False,
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
        result = _run_step(step, env=env, log_dir=log_dir, verbose=verbose)
        results.append(result)
        if result["status"] != "PASS" and not step.always:
            failed = True

    if summary_output:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps({"job": job, "steps": results}, indent=2) + "\n",
            encoding="utf-8",
        )
    has_failure = any(item["status"] in {"FAIL", "TIMEOUT"} for item in results)
    return 1 if has_failure else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", choices=sorted(JOBS))
    parser.add_argument("--step", action="append", dest="steps")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Stream complete step output. Compact failure-focused output is the default.",
    )
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
            verbose=args.verbose,
        )
    except KeyboardInterrupt:
        print("CI job interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
