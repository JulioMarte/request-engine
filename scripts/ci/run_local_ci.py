#!/usr/bin/env python3
"""Run the current Request Engine GitHub CI locally through Docker."""

from __future__ import annotations

import argparse
import datetime as dt
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
SYNC_ENV = "REQUEST_ENGINE_LOCAL_CI_SYNCED_SHA"


class LocalCIError(RuntimeError):
    """Raised when local orchestration cannot produce trustworthy evidence."""


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
        errors="replace",
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


def quiet(command: Sequence[str]) -> int:
    return subprocess.run(
        list(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode


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
        return capture(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            root,
        )
    except subprocess.CalledProcessError as exc:
        raise LocalCIError("Local CI requires a checked-out branch.") from exc


def ensure_clean(root: Path) -> None:
    status = capture(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        root,
    )
    if status:
        raise LocalCIError(
            "Working tree is dirty. Commit, stash, or remove changes first.\n" + status
        )


def sync_exact_remote(
    root: Path,
    requested_branch: str | None,
) -> tuple[str, str, str]:
    ensure_clean(root)
    branch = requested_branch or current_branch(root)
    if stream(["git", "fetch", "--prune", "origin"], cwd=root) != 0:
        raise LocalCIError("git fetch --prune origin failed")
    try:
        remote_sha = capture(["git", "rev-parse", f"origin/{branch}"], root)
        development_sha = capture(
            ["git", "rev-parse", "origin/development"],
            root,
        )
    except subprocess.CalledProcessError as exc:
        message = f"Required origin/{branch} or origin/development ref is missing."
        raise LocalCIError(message) from exc
    if current_branch(root) != branch:
        branches = capture(
            ["git", "branch", "--format=%(refname:short)"],
            root,
        ).splitlines()
        switch = ["git", "switch", branch]
        if branch not in branches:
            switch = ["git", "switch", "--track", "-c", branch, f"origin/{branch}"]
        if stream(switch, cwd=root) != 0:
            raise LocalCIError(f"Could not switch to {branch}")
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
    return branch, head, development_sha


def reexec_synced_runner(root: Path, sha: str) -> None:
    if os.environ.get(SYNC_ENV) == sha:
        return
    env = os.environ.copy()
    env[SYNC_ENV] = sha
    script = root / "scripts/ci/run_local_ci.py"
    os.execve(sys.executable, [sys.executable, str(script), *sys.argv[1:]], env)


def verify_workflow_parity(root: Path) -> None:
    actual = capture(["git", "rev-parse", f"HEAD:{WORKFLOW_PATH}"], root)
    if actual != WORKFLOW_BLOB_SHA:
        raise LocalCIError(
            "ci.yml changed without updating run_local_ci.py; refusing stale evidence."
        )


def docker_ready() -> tuple[str, str]:
    require_program("docker")
    check = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check.returncode != 0:
        detail = (check.stderr or check.stdout).strip()
        raise LocalCIError(
            "Docker engine unavailable. Start Docker Desktop with Linux containers.\n" + detail
        )
    os_type = capture(["docker", "info", "--format", "{{.OSType}}"])
    architecture = capture(["docker", "info", "--format", "{{.Architecture}}"])
    if os_type != "linux":
        raise LocalCIError("Docker must use Linux containers to reproduce GitHub CI.")
    version = check.stdout.strip()
    print(f"Docker engine: Linux/{architecture} ({version})", flush=True)
    return architecture, version


def image_exists(image: str) -> bool:
    return quiet(["docker", "image", "inspect", image]) == 0


def image_id(image: str) -> str:
    return capture(["docker", "image", "inspect", "--format", "{{.Id}}", image])


def runner_image_tag(root: Path) -> str:
    blob = capture(["git", "rev-parse", f"HEAD:{RUNNER_DOCKERFILE}"], root)
    return f"request-engine-local-ci:toolchain-{blob[:16]}"


def ensure_image(image: str, *, refresh: bool, root: Path) -> None:
    if image_exists(image) and not refresh:
        print(f"Reusing local image: {image}", flush=True)
        return
    if stream(["docker", "pull", image], cwd=root) != 0:
        raise LocalCIError(f"Could not pull {image}")


def prepare_images(root: Path, *, rebuild: bool, refresh: bool) -> str:
    ensure_image(POSTGRES_IMAGE, refresh=refresh, root=root)
    tag = runner_image_tag(root)
    if rebuild or not image_exists(tag):
        command = ["docker", "build"]
        if refresh:
            command.append("--pull")
        command.extend(["-f", RUNNER_DOCKERFILE, "-t", tag, "."])
        if stream(command, cwd=root) != 0:
            raise LocalCIError("Local CI runner image build failed.")
    else:
        print(f"Reusing local CI toolchain: {tag}", flush=True)
    return tag


def remove(kind: str, name: str) -> None:
    quiet(["docker", kind, "rm", "-f", name])


def create_linux_source(
    *,
    root: Path,
    image: str,
    volume: str,
    sha: str,
    development_sha: str,
) -> None:
    remove("volume", volume)
    shell = (
        "git config --global --add safe.directory /host-repo && "
        "git clone --no-hardlinks --no-checkout /host-repo /source && "
        "cd /source && git config core.autocrlf false && "
        f"git update-ref refs/remotes/origin/development {development_sha} && "
        f"git checkout --detach {sha} && "
        f'test "$(git rev-parse HEAD)" = "{sha}" && '
        'test -z "$(git status --porcelain --untracked-files=no)"'
    )
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{root}:/host-repo:ro",
        "--mount",
        f"type=volume,source={volume},target=/source",
        image,
        "bash",
        "-lc",
        shell,
    ]
    if stream(command, cwd=root) != 0:
        remove("volume", volume)
        raise LocalCIError("Could not create the Linux-native source repository.")


def create_linux_workspace(
    *,
    image: str,
    source: str,
    workspace: str,
    sha: str,
    development_sha: str,
) -> None:
    remove("volume", workspace)
    shell = (
        "git clone --no-hardlinks --no-checkout /source /workspace && "
        "cd /workspace && git config core.autocrlf false && "
        f"git update-ref refs/remotes/origin/development {development_sha} && "
        f"git checkout --detach {sha} && "
        'test -z "$(git status --porcelain --untracked-files=no)"'
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=volume,source={source},target=/source,readonly",
        "--mount",
        f"type=volume,source={workspace},target=/workspace",
        image,
        "bash",
        "-lc",
        shell,
    ]
    if stream(command) != 0:
        remove("volume", workspace)
        raise LocalCIError("Could not create an isolated Linux CI workspace.")


def start_postgres(name: str, network: str, config: tuple[str, str, str]) -> None:
    database, user, password = config
    remove("container", name)
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
        ready = quiet(["docker", "exec", name, "pg_isready", "-U", user, "-d", database])
        if ready == 0:
            return
        time.sleep(1)
    stream(["docker", "logs", name])
    raise LocalCIError(f"PostgreSQL did not become healthy: {name}")


def job_environment(job: Job, pg_name: str | None) -> dict[str, str]:
    env = dict(job.env or {})
    if not job.postgres or not pg_name:
        return env
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
    migration_jobs = {"postgres-production-head", "postgres-v3-candidate-proof"}
    if job.key in migration_jobs:
        env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://{user}:{password}@{pg_name}:5432/{database}"
        )
    return env


def copy_phase6(image: str, workspace: str, run_dir: Path, job: str) -> None:
    shell = (
        "if [ -d /workspace/.phase6 ]; then "
        f"cp -a /workspace/.phase6 /ci-artifacts/{job}-phase6; fi"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=volume,source={workspace},target=/workspace,readonly",
        "-v",
        f"{run_dir}:/ci-artifacts",
        image,
        "bash",
        "-lc",
        shell,
    ]
    quiet(command)


def linux_workspace_dirty(image: str, workspace: str) -> str:
    return capture(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=volume,source={workspace},target=/workspace",
            "-w",
            "/workspace",
            image,
            "git",
            "status",
            "--porcelain",
            "--untracked-files=no",
        ]
    )


def runner_command(
    *,
    job: Job,
    root: Path,
    run_dir: Path,
    image: str,
    workspace: str,
    network: str,
    token: str,
    pg_name: str | None,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{token}-runner",
        "--network",
        network,
        "--mount",
        f"type=volume,source={workspace},target=/workspace",
        "-v",
        f"{run_dir}:/ci-artifacts",
        "-v",
        f"{CACHE_VOLUME}:/uv-cache",
        "-w",
        "/workspace",
        "-e",
        "UV_CACHE_DIR=/uv-cache",
        "-e",
        "UV_LINK_MODE=copy",
        "-e",
        "PYTHONUNBUFFERED=1",
    ]
    for key, value in job_environment(job, pg_name).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([image, "bash", "-lc", job.command])
    return command


def run_job(
    job: Job,
    *,
    root: Path,
    run_dir: Path,
    image: str,
    source: str,
    network: str,
    sha: str,
    development_sha: str,
) -> dict[str, object]:
    token = f"re-ci-{os.getpid()}-{job.key}"
    workspace = f"{token}-workspace"
    pg_name = f"{token}-pg" if job.postgres else None
    create_linux_workspace(
        image=image,
        source=source,
        workspace=workspace,
        sha=sha,
        development_sha=development_sha,
    )
    if job.postgres and pg_name:
        start_postgres(pg_name, network, job.postgres)
    command = runner_command(
        job=job,
        root=root,
        run_dir=run_dir,
        image=image,
        workspace=workspace,
        network=network,
        token=token,
        pg_name=pg_name,
    )
    started = time.monotonic()
    status = 125
    dirty = "UNKNOWN"
    try:
        status = stream(command, cwd=root, log=run_dir / f"{job.key}.log")
        copy_phase6(image, workspace, run_dir, job.key)
        dirty = linux_workspace_dirty(image, workspace)
        if pg_name and status != 0:
            stream(
                ["docker", "logs", pg_name],
                log=run_dir / f"{job.key}-postgres.log",
            )
    finally:
        if pg_name:
            remove("container", pg_name)
        remove("volume", workspace)
    passed = status == 0 and not dirty
    return {
        "job": job.key,
        "status": "PASS" if passed else "FAIL",
        "returncode": status,
        "seconds": round(time.monotonic() - started, 3),
        "linux_workspace_dirty": dirty,
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
    parser.add_argument(
        "--rebuild-image",
        action="store_true",
        help="Rebuild the CI toolchain using cached/local base layers.",
    )
    parser.add_argument(
        "--refresh-images",
        action="store_true",
        help="Pull base/service images and rebuild the CI toolchain.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_program("git")
    root = repo_root()
    branch, sha, development_sha = sync_exact_remote(root, args.branch)
    reexec_synced_runner(root, sha)
    verify_workflow_parity(root)
    docker_architecture, docker_version = docker_ready()
    image = prepare_images(
        root,
        rebuild=args.rebuild_image or args.refresh_images,
        refresh=args.refresh_images,
    )
    run_id = f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{sha[:12]}"
    run_dir = root / ".local-ci" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    token = f"request-engine-local-ci-{os.getpid()}"
    network = token
    source = f"{token}-source"
    remove("network", network)
    if stream(["docker", "network", "create", network]) != 0:
        raise LocalCIError("Could not create the local CI Docker network.")
    results: list[dict[str, object]] = []
    try:
        create_linux_source(
            root=root,
            image=image,
            volume=source,
            sha=sha,
            development_sha=development_sha,
        )
        status_by_job: dict[str, str] = {}
        for job in JOBS:
            blocked = [name for name in job.depends_on if status_by_job.get(name) != "PASS"]
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
                    source=source,
                    network=network,
                    sha=sha,
                    development_sha=development_sha,
                )
            results.append(result)
            status_by_job[job.key] = str(result["status"])
    finally:
        remove("volume", source)
        remove("network", network)
    host_dirty = capture(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        root,
    )
    aggregate = all(item["status"] == "PASS" for item in results) and not host_dirty
    summary = {
        "schema_version": 3,
        "status": "PASS" if aggregate else "FAIL",
        "branch": branch,
        "commit_sha": sha,
        "development_sha": development_sha,
        "workflow_blob_sha": WORKFLOW_BLOB_SHA,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "docker": {"architecture": docker_architecture, "version": docker_version},
        "execution": "one Linux source seed plus fresh Linux workspace per job",
        "runner_image": image,
        "runner_image_id": image_id(image),
        "postgres_image": POSTGRES_IMAGE,
        "postgres_image_id": image_id(POSTGRES_IMAGE),
        "refresh_images": args.refresh_images,
        "jobs": results,
        "host_tracked_worktree_dirty_after_run": host_dirty,
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
    print(f"Runner image: {image}", flush=True)
    print(f"Summary: {run_dir / 'summary.json'}", flush=True)
    return 0 if aggregate else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalCIError as exc:
        print(f"LOCAL CI ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
