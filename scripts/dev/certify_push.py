from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ZERO_SHA = "0" * 40
DEFAULT_BASE_BRANCH = "development"
CACHE_SCHEMA_VERSION = "local-push-cert-cache/v1"
RUN_RETENTION_COUNT = 20


@dataclass(frozen=True)
class PushUpdate:
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str


def _git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def _repository_root() -> Path:
    return Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _git_common_dir(root: Path) -> Path:
    raw = Path(_git("rev-parse", "--git-common-dir", cwd=root).stdout.strip())
    if raw.is_absolute():
        return raw.resolve()
    return (root / raw).resolve()


def _resolve_commit(root: Path, ref: str) -> str:
    result = _git("rev-parse", f"{ref}^{{commit}}", cwd=root, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or ref
        raise RuntimeError(f"cannot resolve pushed ref to a commit: {detail}")
    return result.stdout.strip()


def parse_push_updates(payload: str) -> list[PushUpdate]:
    updates: list[PushUpdate] = []
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(
                f"pre-push input line {line_number} must contain four fields; got {len(fields)}"
            )
        updates.append(PushUpdate(*fields))
    return updates


def _base_ref_for_remote(root: Path, remote_name: str) -> str:
    candidates = (
        f"refs/remotes/{remote_name}/{DEFAULT_BASE_BRANCH}",
        f"refs/heads/{DEFAULT_BASE_BRANCH}",
    )
    for ref in candidates:
        result = _git("show-ref", "--verify", "--quiet", ref, cwd=root, check=False)
        if result.returncode == 0:
            return ref
    raise RuntimeError(
        "no local development base is available; run "
        f"`git fetch {remote_name} {DEFAULT_BASE_BRANCH}` and retry"
    )


def _working_tree_dirty(root: Path) -> bool:
    return bool(_git("status", "--porcelain", cwd=root).stdout.strip())


def _uv_version() -> str:
    result = subprocess.run(
        ["uv", "--version"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return "uv-unavailable"
    return result.stdout.strip() or "uv-unknown"


def _toolchain_fingerprint() -> str:
    return "|".join(
        (
            platform.system(),
            platform.machine(),
            f"python-{sys.version_info.major}.{sys.version_info.minor}",
            _uv_version(),
        )
    )


def _cache_key(commit_sha: str, base_sha: str, toolchain: str) -> str:
    raw = "|".join((CACHE_SCHEMA_VERSION, commit_sha, base_sha, toolchain)).encode()
    return hashlib.sha256(raw).hexdigest()


def _read_json_object(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload)


def _certificate_matches(
    certificate: dict[str, object] | None,
    *,
    commit_sha: str,
    base_sha: str,
    toolchain: str,
) -> bool:
    if certificate is None:
        return False
    return (
        certificate.get("schema_version") == CACHE_SCHEMA_VERSION
        and certificate.get("result") == "PASS"
        and certificate.get("commit_sha") == commit_sha
        and certificate.get("base_sha") == base_sha
        and certificate.get("toolchain") == toolchain
    )


def _storage_root(root: Path) -> Path:
    return _git_common_dir(root) / "request-engine" / "push-certifications"


def _append_attempt(storage: Path, record: dict[str, object]) -> None:
    storage.mkdir(parents=True, exist_ok=True)
    target = storage / "attempts.jsonl"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _prune_run_directories(storage: Path) -> None:
    runs = storage / "runs"
    if not runs.is_dir():
        return
    directories = sorted(
        (path for path in runs.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in directories[RUN_RETENTION_COUNT:]:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def _detached_worktree(root: Path, commit_sha: str) -> Iterator[Path]:
    parent = Path(tempfile.mkdtemp(prefix="request-engine-push-cert-"))
    worktree = parent / "tree"
    added = False
    try:
        result = _git(
            "worktree",
            "add",
            "--detach",
            "--quiet",
            str(worktree),
            commit_sha,
            cwd=root,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"cannot create detached certification worktree: {detail}")
        added = True
        yield worktree
    finally:
        if added:
            _git("worktree", "remove", "--force", str(worktree), cwd=root, check=False)
            _git("worktree", "prune", cwd=root, check=False)
        shutil.rmtree(parent, ignore_errors=True)


def _failed_step(summary: dict[str, object] | None) -> str | None:
    if summary is None:
        return None
    raw_steps = summary.get("steps")
    if not isinstance(raw_steps, list):
        return None
    for raw_step in cast(list[object], raw_steps):
        if not isinstance(raw_step, dict):
            continue
        step = cast(dict[str, object], raw_step)
        if step.get("status") in {"FAIL", "TIMEOUT"}:
            key = step.get("key")
            return str(key) if key is not None else "unknown"
    return None


def _quality_signal_counts(path: Path) -> tuple[int, int]:
    payload = _read_json_object(path)
    if payload is None:
        return 0, 0
    candidates = payload.get("candidates")
    failures = payload.get("invariant_failures")
    candidate_count = (
        len(cast(list[object], candidates)) if isinstance(candidates, list) else 0
    )
    failure_count = len(cast(list[object], failures)) if isinstance(failures, list) else 0
    return candidate_count, failure_count


def _run_worktree(
    *,
    base_sha: str,
    summary_output: Path,
    log_dir: Path,
    result_output: Path,
    evidence_output: Path,
    verbose: bool,
) -> int:
    script_dir = Path(__file__).resolve().parent
    ci_dir = script_dir.parent / "ci"
    if str(ci_dir) not in sys.path:
        sys.path.insert(0, str(ci_dir))

    from local_push_profile import (  # noqa: PLC0415
        POLICY_SEPARATION_SCRIPT,
        PROFILE_VERSION,
        ci_job_arguments,
    )

    env = os.environ.copy()
    env["FILE_BUDGET_BASE_REF"] = base_sha
    env["QUALITY_POLICY_BASE_REF"] = base_sha

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    result_output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        *ci_job_arguments(),
        "--summary-output",
        str(summary_output),
        "--log-dir",
        str(log_dir),
    ]
    if verbose:
        command.append("--verbose")
    quality = subprocess.run(command, check=False, env=env)

    policy_log = log_dir / "quality-policy-separation.log"
    policy = subprocess.run(
        [
            sys.executable,
            POLICY_SEPARATION_SCRIPT,
            "--base-ref",
            base_sha,
        ],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )
    policy_text = (policy.stdout or "") + (policy.stderr or "")
    policy_log.write_text(policy_text, encoding="utf-8")
    if policy.returncode == 0:
        print("[PASS] Quality-policy separation", flush=True)
    else:
        print("[FAIL] Quality-policy separation", flush=True)
        if policy_text.strip():
            print(policy_text.rstrip(), flush=True)

    signals = Path(".ci/python-quality-signals.json")
    if signals.is_file():
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(signals, evidence_output)
    candidate_count, invariant_count = _quality_signal_counts(signals)

    summary = _read_json_object(summary_output)
    failed_step = _failed_step(summary)
    if policy.returncode != 0 and failed_step is None:
        failed_step = "quality-policy-separation"
    result = "PASS" if quality.returncode == 0 and policy.returncode == 0 else "FAIL"
    payload: dict[str, object] = {
        "profile_version": PROFILE_VERSION,
        "result": result,
        "failed_step": failed_step,
        "review_candidate_count": candidate_count,
        "invariant_failure_count": invariant_count,
        "python_quality_returncode": quality.returncode,
        "policy_separation_returncode": policy.returncode,
    }
    result_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if result == "PASS" else 1


def _certify_commit(
    root: Path,
    *,
    commit_sha: str,
    base_sha: str,
    remote_name: str,
    force: bool,
    verbose: bool,
) -> int:
    storage = _storage_root(root)
    toolchain = _toolchain_fingerprint()
    key = _cache_key(commit_sha, base_sha, toolchain)
    certificate_dir = storage / "certificates"
    certificate_path = certificate_dir / f"{key}.json"
    certificate = _read_json_object(certificate_path)
    if not force and _certificate_matches(
        certificate,
        commit_sha=commit_sha,
        base_sha=base_sha,
        toolchain=toolchain,
    ):
        print(
            f"[LOCAL_PUSH_CERT] CACHED PASS {commit_sha[:12]} against {base_sha[:12]}",
            flush=True,
        )
        _append_attempt(
            storage,
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "commit_sha": commit_sha,
                "base_sha": base_sha,
                "remote_name": remote_name,
                "result": "PASS",
                "cache_hit": True,
                "seconds": 0.0,
                "failed_step": None,
            },
        )
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = storage / "runs" / f"{stamp}-{commit_sha[:12]}-{key[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_output = run_dir / "python-quality.json"
    result_output = run_dir / "local-push-result.json"
    evidence_output = run_dir / "python-quality-signals.json"
    log_dir = run_dir / "logs"

    print("", flush=True)
    print("REQUEST ENGINE LOCAL PUSH CERTIFICATION", flush=True)
    print(f"Commit: {commit_sha}", flush=True)
    print(f"Base:   {base_sha}", flush=True)
    print(
        "Scope: fast publication gate; GitHub exact-head CI remains authoritative.",
        flush=True,
    )

    started = time.monotonic()
    with _detached_worktree(root, commit_sha) as worktree:
        command = [
            sys.executable,
            str(worktree / "scripts" / "dev" / "certify_push.py"),
            "run-worktree",
            "--base-sha",
            base_sha,
            "--summary-output",
            str(summary_output),
            "--log-dir",
            str(log_dir),
            "--result-output",
            str(result_output),
            "--evidence-output",
            str(evidence_output),
        ]
        if verbose:
            command.append("--verbose")
        process = subprocess.run(command, cwd=worktree, check=False)
    elapsed = round(time.monotonic() - started, 3)

    result_payload = _read_json_object(result_output) or {}
    result = "PASS" if process.returncode == 0 else "FAIL"
    failed_step_raw = result_payload.get("failed_step")
    failed_step = str(failed_step_raw) if failed_step_raw is not None else None
    candidate_raw = result_payload.get("review_candidate_count", 0)
    candidate_count = int(candidate_raw) if isinstance(candidate_raw, int) else 0

    attempt: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "base_sha": base_sha,
        "remote_name": remote_name,
        "result": result,
        "cache_hit": False,
        "seconds": elapsed,
        "failed_step": failed_step,
        "review_candidate_count": candidate_count,
        "run_dir": str(run_dir),
    }
    _append_attempt(storage, attempt)
    _prune_run_directories(storage)

    if result == "PASS":
        certificate_dir.mkdir(parents=True, exist_ok=True)
        certificate_payload: dict[str, object] = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "authority": "local-publication-only-not-merge-evidence",
            "result": "PASS",
            "commit_sha": commit_sha,
            "base_sha": base_sha,
            "remote_name": remote_name,
            "toolchain": toolchain,
            "profile_version": result_payload.get("profile_version"),
            "certified_at_utc": datetime.now(UTC).isoformat(),
            "seconds": elapsed,
            "review_candidate_count": candidate_count,
            "run_dir": str(run_dir),
        }
        certificate_path.write_text(
            json.dumps(certificate_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"[LOCAL_PUSH_CERT] PASS {commit_sha[:12]} ({elapsed}s, "
            f"review_candidates={candidate_count})",
            flush=True,
        )
        print("Push may continue. Remote CI must still pass.", flush=True)
        return 0

    print(
        f"[LOCAL_PUSH_CERT] FAIL {commit_sha[:12]} ({elapsed}s, "
        f"failed_step={failed_step or 'unknown'})",
        flush=True,
    )
    print(f"Logs: {run_dir}", flush=True)
    print("Push was not certified. Local commits were not changed.", flush=True)
    return 1


def _certify_many(
    root: Path,
    *,
    commits: list[str],
    base_sha: str,
    remote_name: str,
    force: bool,
    verbose: bool,
) -> int:
    if _working_tree_dirty(root):
        print(
            "[LOCAL_PUSH_CERT] NOTE: uncommitted working-tree changes are intentionally "
            "excluded; certification runs against the exact pushed commit SHA.",
            flush=True,
        )
    unique_commits = list(dict.fromkeys(commits))
    for commit_sha in unique_commits:
        status = _certify_commit(
            root,
            commit_sha=commit_sha,
            base_sha=base_sha,
            remote_name=remote_name,
            force=force,
            verbose=verbose,
        )
        if status != 0:
            return status
    return 0


def _pre_push(args: argparse.Namespace) -> int:
    root = _repository_root()
    updates = parse_push_updates(sys.stdin.read())
    commits = [
        _resolve_commit(root, update.local_sha)
        for update in updates
        if update.local_sha != ZERO_SHA
    ]
    if not commits:
        print("[LOCAL_PUSH_CERT] No commit-bearing refs to certify; push may continue.")
        return 0
    base_ref = _base_ref_for_remote(root, str(args.remote_name))
    base_sha = _resolve_commit(root, base_ref)
    force = os.environ.get("REQUEST_ENGINE_PUSH_CERT_FORCE") == "1"
    verbose = os.environ.get("REQUEST_ENGINE_PUSH_CERT_VERBOSE") == "1"
    return _certify_many(
        root,
        commits=commits,
        base_sha=base_sha,
        remote_name=str(args.remote_name),
        force=force,
        verbose=verbose,
    )


def _manual_certify(args: argparse.Namespace) -> int:
    root = _repository_root()
    commit_sha = _resolve_commit(root, str(args.sha))
    base_sha = _resolve_commit(root, str(args.base_ref))
    return _certify_many(
        root,
        commits=[commit_sha],
        base_sha=base_sha,
        remote_name=str(args.remote_name),
        force=bool(args.force),
        verbose=bool(args.verbose),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certify exact Request Engine commit SHAs before local publication."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pre_push = subparsers.add_parser("pre-push")
    pre_push.add_argument("remote_name")
    pre_push.add_argument("remote_url")

    certify = subparsers.add_parser("certify")
    certify.add_argument("--sha", default="HEAD")
    certify.add_argument("--base-ref", default="refs/remotes/origin/development")
    certify.add_argument("--remote-name", default="origin")
    certify.add_argument("--force", action="store_true")
    certify.add_argument("--verbose", action="store_true")

    run_worktree = subparsers.add_parser("run-worktree", help=argparse.SUPPRESS)
    run_worktree.add_argument("--base-sha", required=True)
    run_worktree.add_argument("--summary-output", type=Path, required=True)
    run_worktree.add_argument("--log-dir", type=Path, required=True)
    run_worktree.add_argument("--result-output", type=Path, required=True)
    run_worktree.add_argument("--evidence-output", type=Path, required=True)
    run_worktree.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "pre-push":
        return _pre_push(args)
    if args.command == "certify":
        return _manual_certify(args)
    if args.command == "run-worktree":
        return _run_worktree(
            base_sha=str(args.base_sha),
            summary_output=cast(Path, args.summary_output).resolve(),
            log_dir=cast(Path, args.log_dir).resolve(),
            result_output=cast(Path, args.result_output).resolve(),
            evidence_output=cast(Path, args.evidence_output).resolve(),
            verbose=bool(args.verbose),
        )
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
