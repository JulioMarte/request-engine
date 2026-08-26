#!/usr/bin/env python3
"""Run the current Request Engine GitHub CI locally through Docker.

The host only needs Python, Git, and Docker. Test jobs run in the same
Linux/Python/PostgreSQL family used by ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

POSTGRES_IMAGE = "postgres:18"
CACHE_VOLUME = "request-engine-local-ci-uv-cache"
RUNNER_DOCKERFILE = "scripts/ci/Dockerfile.local-ci"
WORKFLOW_PATH = ".github/workflows/ci.yml"
WORKFLOW_BLOB_SHA = "40b9ff5c06385691785ed04edc2216cb973abef3"
IMAGE_INPUTS = (
    RUNNER_DOCKERFILE,
    WORKFLOW_PATH,
    "pyproject.toml",
    "uv.lock",
    ".python-version",
)
SYNC_ENV = "REQUEST_ENGINE_LOCAL_CI_SYNCED_SHA"


class LocalCIError(RuntimeError):
    """Raised when local orchestration cannot produce trustworthy CI evidence."""


@dataclass(frozen=True, slots=True)
class Job:
    key: str
    command: str
    postgres: tuple[str, str, str] | None = None
    env: Mapping[str, str] | None = None
    depends_on: tuple[str, ...] = ()


JOBS = (
    Job(
        "python-quality",
        "python scripts/ci/ci_jobs.py python-quality "
        "--summary-output /ci-artifacts/python-quality.json "
        "--log-dir /ci-artifacts/python-quality-logs && "
        "python scripts/ci/audit_test_architecture.py "
        "--output /ci-artifacts/test-architecture.json",
        env={"FILE_BUDGET_BASE_REF": "origin/development"},
    ),
    Job(
        "observability-contract",
        "uv sync --frozen --no-dev && "
        "uv pip install -r deploy/observability/requirements.txt && "
        "uv run --no-sync python scripts/observability/run_with_otel.py "
        "--service-name request-engine-local-ci --check && "
        "uv run --no-sync python scripts/observability/smoke_otel.py",
        depends_on=("python-quality",),
    ),
    Job(
        "postgres-v2-history",
        "python scripts/ci/ci_jobs.py postgres-v2-history",
        postgres=("request_engine", "request_engine", "request_engine"),
        depends_on=("python-quality",),
    ),
    Job(
        "postgres-v3-bootstrap-proof",
        "python scripts/ci/ci_jobs.py postgres-v3-bootstrap-proof",
        postgres=("request_engine_v3", "postgres", "postgres"),
        env={
            "PGMAINTENANCE_DB": "postgres",
            "V3_PROOF_DATABASE_PREFIX": "request_engine_v3_phase6",
        },
        depends_on=("python-quality",),
    ),
    Job(
        "postgres-production-head",
        "CURRENT_PRODUCT_CI_ARTIFACT_DIR=/ci-artifacts/current-product "
        "bash scripts/ci/run_current_product.sh",
        postgres=("request_engine_current", "postgres", "postgres"),
        depends_on=("python-quality",),
    ),
    Job(
        "postgres-v3-candidate-proof",
        "bash scripts/ci/run_v3_frozen_compatibility.sh && "
        "uv run pytest tests/historical -q --tb=short",
        postgres=("request_engine_v3", "postgres", "postgres"),
        depends_on=(
            "python-quality",
            "observability-contract",
            "postgres-v3-bootstrap-proof",
        ),
    ),
)


def capture(command: Sequence[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def stream(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    log: Path | None = None,
) -> int:
    handle = log.open("w", encoding="utf-8", newline="\n") if log else None
    try:
        print("$ " + " ".join(command), flush=True)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            if handle:
                handle.write(line)
                handle.flush()
        return process.wait()
    finally:
        if handle:
            handle.close()


def require_program(name: str) -> None:
    if shutil.which(name) is None:
        raise LocalCIError(f"Required executable not found on PATH: {name}")


def repo_root() -> Path:
    try:
        return Path(capture(["git", "rev-parse", "--show-toplevel"])).resolve()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise LocalCIError("Run this script from inside the Request Engine repository.") from exc


def current_branch(root: Path) -> str:
    try:
        branch = capture(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            root,
        )
    except subprocess.CalledProcessError as exc:
        raise LocalCIError("Local CI requires a checked-out branch, not detached HEAD.") from exc
    if not branch:
        raise LocalCIError("Local CI requires a checked-out branch, not detached HEAD.")
    return branch


def ensure_clean(root: Path) -> None:
    status = capture(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        root,
    )
    if status:
        raise LocalCIError(
            "Working tree is dirty. Commit, stash, or remove local changes before local CI.\n"
            + status
        )


def sync_exact_remote(root: Path, requested_branch: str | None) -> tuple[str, str]:
    ensure_clean(root)
    branch = requested_branch or current_branch(root)
    if stream(["git", "fetch", "--prune", "origin"], cwd=root) != 0:
        raise LocalCIError("git fetch --prune origin failed")
    try:
        capture(["git", "rev-parse", f"origin/{branch}"], root)
        capture(["git", "rev-parse", "origin/development"], root)
    except subprocess.CalledProcessError as exc:
        raise LocalCIError(
            f"Required remote ref is missing for {branch} or development."
        ) from exc
    if current_branch(root) != branch:
        local_branches = capture(
            ["git", "branch", "--format=%(refname:short)"],
            root,
        ).splitlines()
        switch = ["git", "switch", branch]
        if branch not in local_branches:
            switch = [
                "git",
                "switch",
                "--track",
                "-c",
                branch,
                f"origin/{branch}",
            ]
        if stream(switch, cwd=root) != 0:
            raise LocalCIError(f"Could not switch to {branch}")
    remote_sha = capture(["git", "rev-parse", f"origin/{branch}"], root)
    print(
        f"Force-synchronizing clean checkout to origin/{branch} ({remote_sha})",
        flush=True,
    )
    if stream(["git", "reset", "--hard", f"origin/{branch}"], cwd=root) != 0:
        raise LocalCIError("git reset --hard to the remote branch failed")
    head = capture(["git", "rev-parse", "HEAD"], root)
    ensure_clean(root)
    if head != remote_sha:
        raise LocalCIError(f"Exact-head sync failed: local={head} remote={remote_sha}")
    return branch, head


def reexec_synced_runner(root: Path, sha: str) -> None:
    if os.environ.get(SYNC_ENV) == sha:
        return
    env = os.environ.copy()
    env[SYNC_ENV] = sha
    script = root / "scripts/ci/run_local_ci.py"
    os.execve(
        sys.executable,
        [sys.executable, str(script), *sys.argv[1:]],
        env,
    )


def verify_workflow_parity(root: Path) -> None:
    actual = capture(["git", "rev-parse", f"HEAD:{WORKFLOW_PATH}"], root)
    if actual != WORKFLOW_BLOB_SHA:
        raise LocalCIError(
            "Local CI mapping is stale: .github/workflows/ci.yml changed without "
            "updating scripts/ci/run_local_ci.py. Refusing potentially false evidence."
        )


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in IMAGE_INPUTS:
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def docker_ready() -> None:
    require_program("docker")
    if stream(["docker", "version", "--format", "{{.Server.Version}}"] ) != 0:
        raise LocalCIError("Docker Desktop/Engine is not available.")
    os_type = capture(["docker", "info", "--format", "{{.OSType}}"])
    if os_type != "linux":
        raise LocalCIError(
            "Docker must be running Linux containers to reproduce GitHub CI."
        )


def image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def prepare_images(root: Path, rebuild: bool) -> str:
    if stream(["docker", "pull", POSTGRES_IMAGE], cwd=root) != 0:
        raise LocalCIError(f"Could not pull {POSTGRES_IMAGE}")
    tag = f"request-engine-local-ci:{fingerprint(root)[:16]}"
    if rebuild or not image_exists(tag):
        command = [
            "docker",
            "build",
            "--pull",
            "-f",
            RUNNER_DOCKERFILE,
            "-t",
            tag,
            ".",
        ]
        if stream(command, cwd=root) != 0:
            raise LocalCIError("Local CI runner image build failed.")
    return tag


def rm_container(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def rm_network(name: str) -> None:
    subprocess.run(
        ["docker", "network", "rm", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def rm_volume(name: str) -> None:
    subprocess.run(
        ["docker", "volume", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def start_postgres(
    name: str,
    network: str,
    config: tuple[str, str, str],
) -> None:
    database, user, password = config
    rm_container(name)
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-e",
        f"POSTGRES_DB={database}",
        "-e",
        f"POSTGRES_USER={user}",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        POSTGRES_IMAGE,
    ]
    if stream(command) != 0:
        raise LocalCIError(f"Could not start {name}")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ready = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "pg_isready",
                "-U",
                user,
                "-d",
                database,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    stream(["docker", "logs", name])
    raise LocalCIError(f"PostgreSQL did not become healthy: {name}")


def job_environment(job: Job, pg_name: str | None) -> dict[str, str]:
    env = dict(job.env or {})
    if job.postgres and pg_name:
        database, user, password = job.postgres
        env.update(
            {
                "PGHOST": pg_name,
                "PGPORT": "5432",
                "PGDATABASE": database,
                "PGUSER": user,
                "PGPASSWORD": password,
            }
        )
        if job.key in {
            "postgres-production-head",
            "postgres-v3-candidate-proof",
        }:
            env["MIGRATION_DATABASE_URL"] = (
                f"postgresql+psycopg://{user}:{password}@{pg_name}:5432/{database}"
            )
    return env


def run_job(
    job: Job,
    *,
    root: Path,
    run_dir: Path,
    image: str,
    network: str,
) -> dict[str, object]:
    token = f"re-ci-{os.getpid()}-{job.key}"
    pg_name = f"{token}-pg" if job.postgres else None
    venv_volume = f"{token}-venv"
    rm_volume(venv_volume)
    if job.postgres and pg_name:
        start_postgres(pg_name, network, job.postgres)
    env = job_environment(job, pg_name)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{token}-runner",
        "--network",
        network,
        "-v",
        f"{root}:/workspace",
        "-v",
        f"{run_dir}:/ci-artifacts",
        "-v",
        f"{CACHE_VOLUME}:/uv-cache",
        "--mount",
        f"type=volume,source={venv_volume},target=/workspace/.venv",
        "-w",
        "/workspace",
        "-e",
        "UV_CACHE_DIR=/uv-cache",
        "-e",
        "PYTHONUNBUFFERED=1",
    ]
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    shell = (
        "git config --global --add safe.directory /workspace && "
        "python scripts/ci/normalize_ci_line_endings.py && "
        + job.command
    )
    command.extend([image, "bash", "-lc", shell])
    started = time.monotonic()
    status = 125
    try:
        status = stream(
            command,
            cwd=root,
            log=run_dir / f"{job.key}.log",
        )
        if pg_name and status != 0:
            stream(
                ["docker", "logs", pg_name],
                log=run_dir / f"{job.key}-postgres.log",
            )
    finally:
        if pg_name:
            rm_container(pg_name)
        rm_volume(venv_volume)
    return {
        "job": job.key,
        "status": "PASS" if status == 0 else "FAIL",
        "returncode": status,
        "seconds": round(time.monotonic() - started, 3),
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--branch",
        help="Remote branch to test; defaults to the checked-out branch.",
    )
    parser.add_argument("--rebuild-image", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_program("git")
    root = repo_root()
    branch, sha = sync_exact_remote(root, args.branch)
    reexec_synced_runner(root, sha)
    verify_workflow_parity(root)
    docker_ready()
    image = prepare_images(root, args.rebuild_image)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{sha[:12]}"
    run_dir = root / ".local-ci" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    network = f"request-engine-local-ci-{os.getpid()}"
    rm_network(network)
    if stream(["docker", "network", "create", network]) != 0:
        raise LocalCIError("Could not create the local CI Docker network.")
    results: list[dict[str, object]] = []
    try:
        status_by_job: dict[str, str] = {}
        for job in JOBS:
            blocked = [
                dependency
                for dependency in job.depends_on
                if status_by_job.get(dependency) != "PASS"
            ]
            if blocked:
                result: dict[str, object] = {
                    "job": job.key,
                    "status": "SKIP",
                    "blocked_by": blocked,
                }
            else:
                print(f"\n=== {job.key} ===", flush=True)
                result = run_job(
                    job,
                    root=root,
                    run_dir=run_dir,
                    image=image,
                    network=network,
                )
            results.append(result)
            status_by_job[job.key] = str(result["status"])
    finally:
        rm_network(network)
    dirty = capture(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        root,
    )
    aggregate = all(item["status"] == "PASS" for item in results) and not dirty
    summary = {
        "schema_version": 1,
        "status": "PASS" if aggregate else "FAIL",
        "branch": branch,
        "commit_sha": sha,
        "workflow_blob_sha": WORKFLOW_BLOB_SHA,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "runner_image": image,
        "postgres_image": POSTGRES_IMAGE,
        "jobs": results,
        "tracked_worktree_dirty_after_run": dirty,
    }
    write_json(run_dir / "summary.json", summary)
    write_json(
        root / ".local-ci/latest.json",
        {"summary": str(run_dir / "summary.json")},
    )
    print("\n=== LOCAL CI SUMMARY ===", flush=True)
    for item in results:
        print(f"{item['status']:>4}  {item['job']}", flush=True)
    print(f"Exact tested SHA: {sha}", flush=True)
    print(f"Summary: {run_dir / 'summary.json'}", flush=True)
    if dirty:
        print(
            "Tracked files changed during CI; evidence is invalid:\n" + dirty,
            flush=True,
        )
    return 0 if aggregate else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalCIError as exc:
        print(f"LOCAL CI ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
