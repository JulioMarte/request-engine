#!/usr/bin/env python3
"""Run the current Request Engine GitHub CI locally through Docker."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
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
MAX_FAILURE_LINES = 120


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


def run_logged(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    log: Path | None = None,
    verbose: bool = True,
) -> int:
    handle = log.open("w", encoding="utf-8", newline="\n") if log else None
    try:
        if verbose:
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
            if verbose:
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
        return capture(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], root)
    except subprocess.CalledProcessError as exc:
        raise LocalCIError("Local CI requires a checked-out branch.") from exc


def ensure_clean(root: Path) -> None:
    status = capture(["git", "status", "--porcelain", "--untracked-files=all"], root)
    if status:
        raise LocalCIError(
            "Working tree is dirty. Commit, stash, or remove changes first.\n" + status
        )


def sync_exact_remote(root: Path, requested: str | None) -> tuple[str, str, str]:
    ensure_clean(root)
    branch = requested or current_branch(root)
    if run_logged(["git", "fetch", "--prune", "origin"], cwd=root) != 0:
        raise LocalCIError("git fetch --prune origin failed")
    try:
        remote_sha = capture(["git", "rev-parse", f"origin/{branch}"], root)
        development_sha = capture(["git", "rev-parse", "origin/development"], root)
    except subprocess.CalledProcessError as exc:
        message = f"Required origin/{branch} or origin/development ref is missing."
        raise LocalCIError(message) from exc
    if current_branch(root) != branch:
        branches = capture(["git", "branch", "--format=%(refname:short)"], root).splitlines()
        switch = ["git", "switch", branch]
        if branch not in branches:
            switch = ["git", "switch", "--track", "-c", branch, f"origin/{branch}"]
        if run_logged(switch, cwd=root) != 0:
            raise LocalCIError(f"Could not switch to {branch}")
    print(f"Sync exact remote: origin/{branch} @ {remote_sha[:12]}", flush=True)
    if run_logged(["git", "reset", "--hard", f"origin/{branch}"], cwd=root, verbose=False) != 0:
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
        print(f"Image ready: {image}", flush=True)
        return
    if run_logged(["docker", "pull", image], cwd=root) != 0:
        raise LocalCIError(f"Could not pull {image}")


def prepare_images(root: Path, *, rebuild: bool, refresh: bool) -> str:
    ensure_image(POSTGRES_IMAGE, refresh=refresh, root=root)
    tag = runner_image_tag(root)
    if rebuild or not image_exists(tag):
        command = ["docker", "build"]
        if refresh:
            command.append("--pull")
        command.extend(["-f", RUNNER_DOCKERFILE, "-t", tag, "."])
        if run_logged(command, cwd=root) != 0:
            raise LocalCIError("Local CI runner image build failed.")
    else:
        print(f"Toolchain ready: {tag}", flush=True)
    return tag


def remove(kind: str, name: str) -> None:
    quiet(["docker", kind, "rm", "-f", name])


def create_linux_source(
    *, root: Path, image: str, volume: str, sha: str, development_sha: str
) -> None:
    remove("volume", volume)
    shell = (
        "git config --global --add safe.directory /host-repo && "
        "git clone --quiet --no-hardlinks --no-checkout /host-repo /source && "
        "cd /source && git config core.autocrlf false && "
        f"git update-ref refs/remotes/origin/development {development_sha} && "
        f"git checkout --quiet --detach {sha} && "
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
    if run_logged(command, cwd=root, verbose=False) != 0:
        remove("volume", volume)
        raise LocalCIError("Could not create the Linux-native source repository.")


def create_linux_workspace(
    *, image: str, source: str, workspace: str, sha: str, development_sha: str
) -> None:
    remove("volume", workspace)
    shell = (
        "git clone --quiet --no-hardlinks --no-checkout /source /workspace && "
        "cd /workspace && git config core.autocrlf false && "
        f"git update-ref refs/remotes/origin/development {development_sha} && "
        f"git checkout --quiet --detach {sha} && "
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
    if run_logged(command, verbose=False) != 0:
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
    if run_logged(command, verbose=False) != 0:
        raise LocalCIError(f"Could not start {name}")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ready = quiet(["docker", "exec", name, "pg_isready", "-U", user, "-d", database])
        if ready == 0:
            return
        time.sleep(1)
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
    if job.key in {"postgres-production-head", "postgres-v3-candidate-proof"}:
        env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://{user}:{password}@{pg_name}:5432/{database}"
        )
    return env


def copy_phase6(image: str, workspace: str, run_dir: Path, job: str) -> None:
    shell = (
        "if [ -d /workspace/.phase6 ]; then "
        f"cp -a /workspace/.phase6 /ci-artifacts/{job}-phase6; fi"
    )
    quiet(
        [
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
    )


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


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def compact_pytest_failure(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if " FAILURES " in line),
        None,
    )
    if start is None:
        return []
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if "short test summary info" in lines[i]
        ),
        len(lines),
    )
    block = lines[start:end]
    failed = [line for line in lines if line.startswith("FAILED ")]
    return (block + failed)[:MAX_FAILURE_LINES]


def compact_generic_failure(text: str) -> list[str]:
    lines = text.splitlines()
    pattern = re.compile(
        r"(FAIL|FAILED|ERROR|Traceback|AssertionError|E\s{3}|F\d{3}|E\d{3}|error:)",
        re.IGNORECASE,
    )
    hits: list[str] = []
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        for candidate in lines[max(0, index - 2) : min(len(lines), index + 4)]:
            if candidate not in hits:
                hits.append(candidate)
        if len(hits) >= MAX_FAILURE_LINES:
            break
    if hits:
        return hits[:MAX_FAILURE_LINES]
    return lines[-40:]


def python_quality_failure(run_dir: Path) -> dict[str, object] | None:
    path = run_dir / "python-quality.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    failed = next(
        (step for step in payload.get("steps", []) if step.get("status") == "FAIL"),
        None,
    )
    if not failed:
        return None
    key = str(failed.get("key", "unknown"))
    step_log = run_dir / "python-quality-logs" / f"{key}.log"
    detail = compact_generic_failure(read_text(step_log))
    return {
        "step": key,
        "name": failed.get("name"),
        "command": failed.get("command"),
        "detail": detail,
    }


def diagnose_failure(job: Job, run_dir: Path) -> dict[str, object]:
    log_path = run_dir / f"{job.key}.log"
    text = read_text(log_path)
    detail = compact_pytest_failure(text) or compact_generic_failure(text)
    diagnostic: dict[str, object] = {
        "job": job.key,
        "command": job.command,
        "log": str(log_path),
        "detail": detail,
    }
    if job.key == "python-quality":
        structured = python_quality_failure(run_dir)
        if structured:
            diagnostic["structured_step"] = structured
    if job.postgres and not detail:
        pg_log = run_dir / f"{job.key}-postgres.log"
        diagnostic["postgres_tail"] = read_text(pg_log).splitlines()[-30:]
    return diagnostic


def print_failure(diagnostic: Mapping[str, object]) -> None:
    print("\n--- ACTIONABLE FAILURE ---", flush=True)
    print(f"job: {diagnostic['job']}", flush=True)
    structured = diagnostic.get("structured_step")
    if isinstance(structured, dict):
        print(
            f"step: {structured.get('step')} ({structured.get('name')})",
            flush=True,
        )
        print(f"command: {structured.get('command')}", flush=True)
        detail = structured.get("detail", [])
    else:
        print(f"command: {diagnostic['command']}", flush=True)
        detail = diagnostic.get("detail", [])
    if isinstance(detail, list):
        for line in detail:
            print(str(line), flush=True)
    print(f"full log: {diagnostic['log']}", flush=True)


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
    verbose: bool,
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
        run_dir=run_dir,
        image=image,
        workspace=workspace,
        network=network,
        token=token,
        pg_name=pg_name,
    )
    log_path = run_dir / f"{job.key}.log"
    print(f"RUN   {job.key}", flush=True)
    started = time.monotonic()
    status = 125
    dirty = "UNKNOWN"
    try:
        status = run_logged(command, cwd=root, log=log_path, verbose=verbose)
        copy_phase6(image, workspace, run_dir, job.key)
        dirty = linux_workspace_dirty(image, workspace)
        if pg_name and status != 0:
            run_logged(
                ["docker", "logs", pg_name],
                log=run_dir / f"{job.key}-postgres.log",
                verbose=False,
            )
    finally:
        if pg_name:
            remove("container", pg_name)
        remove("volume", workspace)
    seconds = round(time.monotonic() - started, 3)
    passed = status == 0 and not dirty
    result: dict[str, object] = {
        "job": job.key,
        "status": "PASS" if passed else "FAIL",
        "returncode": status,
        "seconds": seconds,
        "linux_workspace_dirty": dirty,
    }
    print(f"{result['status']:<5} {job.key} ({seconds:.1f}s)", flush=True)
    if not passed:
        diagnostic = diagnose_failure(job, run_dir)
        result["diagnostic"] = diagnostic
        print_failure(diagnostic)
    return result


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_failure_report(
    run_dir: Path,
    *,
    branch: str,
    sha: str,
    results: list[dict[str, object]],
) -> Path | None:
    failures = [item for item in results if item.get("status") == "FAIL"]
    if not failures:
        return None
    report = {
        "schema_version": 1,
        "branch": branch,
        "commit_sha": sha,
        "failures": [item.get("diagnostic", item) for item in failures],
    }
    json_path = run_dir / "failure-report.json"
    write_json(json_path, report)
    lines = [
        "REQUEST ENGINE LOCAL CI FAILURE REPORT",
        f"branch: {branch}",
        f"commit: {sha}",
        "",
    ]
    for failure in failures:
        diagnostic = failure.get("diagnostic")
        if not isinstance(diagnostic, dict):
            continue
        lines.append(f"=== {diagnostic.get('job')} ===")
        structured = diagnostic.get("structured_step")
        if isinstance(structured, dict):
            lines.append(f"step: {structured.get('step')} ({structured.get('name')})")
            lines.append(f"command: {structured.get('command')}")
            detail = structured.get("detail", [])
        else:
            lines.append(f"command: {diagnostic.get('command')}")
            detail = diagnostic.get("detail", [])
        if isinstance(detail, list):
            lines.extend(str(line) for line in detail)
        lines.append(f"full log: {diagnostic.get('log')}")
        lines.append("")
    text_path = run_dir / "failure-report.txt"
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return text_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--branch", help="Remote branch to test; defaults to checked-out branch."
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Stream complete job output instead of concise progress only.",
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
    if run_logged(["docker", "network", "create", network], verbose=False) != 0:
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
            blocked = [
                name for name in job.depends_on if status_by_job.get(name) != "PASS"
            ]
            if blocked:
                result: dict[str, object] = {
                    "job": job.key,
                    "status": "SKIP",
                    "blocked_by": blocked,
                }
                print(f"SKIP  {job.key} (blocked by {', '.join(blocked)})", flush=True)
            else:
                result = run_job(
                    job,
                    root=root,
                    run_dir=run_dir,
                    image=image,
                    source=source,
                    network=network,
                    sha=sha,
                    development_sha=development_sha,
                    verbose=args.verbose,
                )
            results.append(result)
            status_by_job[job.key] = str(result["status"])
    finally:
        remove("volume", source)
        remove("network", network)
    host_dirty = capture(["git", "status", "--porcelain", "--untracked-files=no"], root)
    aggregate = all(item["status"] == "PASS" for item in results) and not host_dirty
    failure_report = write_failure_report(run_dir, branch=branch, sha=sha, results=results)
    summary = {
        "schema_version": 4,
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
        "verbose": args.verbose,
        "jobs": results,
        "failure_report": str(failure_report) if failure_report else None,
        "host_tracked_worktree_dirty_after_run": host_dirty,
    }
    write_json(run_dir / "summary.json", summary)
    write_json(
        root / ".local-ci/latest.json",
        {
            "summary": str(run_dir / "summary.json"),
            "failure_report": str(failure_report) if failure_report else None,
        },
    )
    print("\n=== LOCAL CI SUMMARY ===", flush=True)
    for item in results:
        seconds = item.get("seconds")
        timing = f" ({seconds:.1f}s)" if isinstance(seconds, float) else ""
        print(f"{item['status']:>4}  {item['job']}{timing}", flush=True)
    print(f"Exact tested SHA: {sha}", flush=True)
    if failure_report:
        print(f"Single failure report to share: {failure_report}", flush=True)
    else:
        print("Failure report: none (all jobs passed)", flush=True)
    print(f"Summary: {run_dir / 'summary.json'}", flush=True)
    return 0 if aggregate else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalCIError as exc:
        print(f"LOCAL CI ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
