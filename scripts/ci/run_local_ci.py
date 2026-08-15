#!/usr/bin/env python3
"""Run Request Engine CI locally with Git sync, isolation, and diagnostics.

This script keeps its stable public name while delegating job definitions to
scripts/ci/ci_jobs.py, which GitHub Actions also executes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Mapping, Sequence

DEFAULT_BRANCH = "phase-6-v3-freeze-release-proof"
POSTGRES_IMAGE = "postgres:18"
CACHE_VOLUME = "request-engine-local-ci-uv-cache"
IMAGE_INPUTS = (
    "scripts/ci/Dockerfile.local-ci",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
)


class LocalCIError(RuntimeError):
    """An orchestration error that prevents a trustworthy local CI run."""


class Logger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._handle = path.open("w", encoding="utf-8", newline="\n")

    def close(self) -> None:
        self._handle.close()

    def write(self, message: str = "") -> None:
        print(message, flush=True)
        self._handle.write(message + "\n")
        self._handle.flush()

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        self.write(f"$ {' '.join(command)}")
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            print(line, flush=True)
            self._handle.write(line + "\n")
            self._handle.flush()
        return process.wait()


def require_program(name: str) -> None:
    if shutil.which(name) is None:
        raise LocalCIError(f"Required executable not found on PATH: {name}")


def capture(command: Sequence[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_repo_root() -> Path:
    try:
        root = capture(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise LocalCIError("Run this script from inside the Request Engine repository.") from exc
    return Path(root).resolve()


def ensure_clean_worktree(root: Path) -> None:
    status = capture(["git", "status", "--porcelain", "--untracked-files=all"], root)
    if status:
        raise LocalCIError(
            "Git worktree is not clean. Commit, stash, or remove local changes first.\n"
            "The runner never discards local work automatically.\n\n"
            f"{status}"
        )


def clear_console() -> None:
    command = ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
    subprocess.run(command, check=False)


def sync_branch(root: Path, branch: str, log: Logger) -> str:
    log.write("=== Git sync ===")
    ensure_clean_worktree(root)
    if log.run(["git", "fetch", "--prune", "origin", branch], cwd=root) != 0:
        raise LocalCIError("git fetch failed")

    branches = capture(["git", "branch", "--format=%(refname:short)"], root).splitlines()
    switch = ["git", "switch", branch]
    if branch not in branches:
        switch = ["git", "switch", "--track", "-c", branch, f"origin/{branch}"]
    if log.run(switch, cwd=root) != 0:
        raise LocalCIError(f"Could not switch to {branch}")

    clear_console()
    if log.run(["git", "pull", "--ff-only", "origin", branch], cwd=root) != 0:
        raise LocalCIError("Local branch diverged from origin. Resolve it before local CI.")

    head = capture(["git", "rev-parse", "HEAD"], root)
    remote = capture(["git", "rev-parse", f"origin/{branch}"], root)
    if head != remote:
        raise LocalCIError(f"HEAD {head} does not match origin/{branch} {remote}.")
    ensure_clean_worktree(root)
    log.write(f"Synced commit: {head}")
    return head


def maybe_reexec_after_sync(script_before: str, root: Path, log: Logger) -> None:
    script_path = root / "scripts/ci/run_local_ci.py"
    script_after = file_sha256(script_path)
    if script_after == script_before or os.environ.get("REQUEST_ENGINE_LOCAL_CI_REEXEC") == "1":
        return
    log.write("Local CI runner changed during git pull; restarting with the synced version.")
    log.close()
    env = os.environ.copy()
    env["REQUEST_ENGINE_LOCAL_CI_REEXEC"] = "1"
    os.execve(sys.executable, [sys.executable, str(script_path), *sys.argv[1:]], env)


def docker_exists(kind: str, name: str) -> bool:
    return subprocess.run(
        ["docker", kind, "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def remove_container(name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def remove_network(name: str) -> None:
    subprocess.run(
        ["docker", "network", "rm", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def ensure_docker(log: Logger) -> None:
    require_program("docker")
    if log.run(["docker", "version", "--format", "{{.Server.Version}}"]) != 0:
        raise LocalCIError("Docker is unavailable. Start Docker Desktop or Docker Engine.")


def image_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in IMAGE_INPUTS:
        path = root / relative
        if not path.exists():
            raise LocalCIError(f"Missing local CI image input: {relative}")
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_images(
    root: Path,
    log: Logger,
    *,
    rebuild: bool,
    offline: bool,
) -> tuple[str, str]:
    fingerprint = image_fingerprint(root)
    runner_image = f"request-engine-local-ci:{fingerprint[:16]}"

    if not offline:
        if log.run(["docker", "pull", POSTGRES_IMAGE]) != 0:
            raise LocalCIError(f"Could not refresh {POSTGRES_IMAGE}")

    if rebuild or not docker_exists("image", runner_image):
        command = [
            "docker",
            "build",
            "--pull" if not offline else "--no-cache",
            "-f",
            "scripts/ci/Dockerfile.local-ci",
            "-t",
            runner_image,
            ".",
        ]
        if log.run(command, cwd=root) != 0:
            raise LocalCIError("Failed to build the fingerprinted local CI image.")
    else:
        log.write(f"Using fingerprinted runner image: {runner_image}")

    return runner_image, fingerprint


def list_jobs(root: Path) -> list[str]:
    output = capture([sys.executable, "scripts/ci/ci_jobs.py", "--list-jobs"], root)
    jobs = [line.strip() for line in output.splitlines() if line.strip()]
    if not jobs:
        raise LocalCIError("Canonical CI job registry is empty.")
    return jobs


def list_steps(root: Path, job: str) -> list[str]:
    output = capture([sys.executable, "scripts/ci/ci_jobs.py", job, "--list"], root)
    return [line.split("\t", 1)[0] for line in output.splitlines() if line.strip()]


def resolve_selected_steps(root: Path, job: str, requested: list[str]) -> list[str]:
    available = list_steps(root, job)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise LocalCIError(f"Unknown step(s) for {job}: {', '.join(unknown)}")

    selected = set(requested)
    if job == "python-quality" and "uv-sync" not in selected:
        selected.add("uv-sync")
    if job == "postgres-v3-candidate":
        if selected != {"v3-bootstrap"}:
            selected.add("v3-bootstrap")
        after_sync = set(available[2:])
        if selected & after_sync:
            selected.add("uv-sync")
    return [step for step in available if step in selected]


def create_isolated_worktree(root: Path, run_id: str, log: Logger) -> Path:
    workspace_root = root.parent / ".request-engine-local-ci"
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace = workspace_root / run_id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    if log.run(["git", "worktree", "add", "--detach", str(workspace), "HEAD"], cwd=root) != 0:
        raise LocalCIError("Could not create isolated git worktree for local CI.")
    return workspace


def remove_worktree(root: Path, workspace: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(workspace)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def start_postgres(
    *,
    name: str,
    network: str,
    database: str,
    user: str,
    password: str,
    log: Logger,
) -> None:
    remove_container(name)
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
    if log.run(command) != 0:
        raise LocalCIError(f"Could not start PostgreSQL container {name}")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", user, "-d", database],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if ready.returncode == 0:
            log.write(f"PostgreSQL ready: {name} ({database}, user={user})")
            return
        time.sleep(1)
    log.run(["docker", "logs", name])
    raise LocalCIError(f"PostgreSQL did not become healthy: {name}")


def start_runner(
    *,
    name: str,
    network: str,
    workspace: Path,
    job_log_dir: Path,
    runner_image: str,
    env: Mapping[str, str],
    log: Logger,
) -> None:
    remove_container(name)
    job_log_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-v",
        f"{workspace}:/workspace",
        "-v",
        f"{job_log_dir}:/ci-logs",
        "-v",
        f"{CACHE_VOLUME}:/uv-cache",
        "-w",
        "/workspace",
        "-e",
        "UV_PROJECT_ENVIRONMENT=/tmp/request-engine-venv",
        "-e",
        "UV_CACHE_DIR=/uv-cache",
    ]
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([runner_image, "sleep", "infinity"])
    if log.run(command) != 0:
        raise LocalCIError(f"Could not start runner container {name}")


def postgres_job_config(job: str, commit_sha: str) -> tuple[str, str, str, dict[str, str]] | None:
    if job == "postgres-v2-history":
        return (
            "request_engine",
            "request_engine",
            "request_engine",
            {
                "PGUSER": "request_engine",
                "PGPASSWORD": "request_engine",
                "PGDATABASE": "request_engine",
            },
        )
    if job == "postgres-v3-bootstrap-proof":
        return (
            "request_engine_v3",
            "postgres",
            "postgres",
            {
                "PGUSER": "postgres",
                "PGPASSWORD": "postgres",
                "PGMAINTENANCE_DB": "postgres",
                "V3_PROOF_DATABASE_PREFIX": "request_engine_v3_phase6",
            },
        )
    if job == "postgres-v3-candidate":
        return (
            "request_engine_v3",
            "postgres",
            "postgres",
            {
                "PGUSER": "postgres",
                "PGPASSWORD": "postgres",
                "PGDATABASE": "request_engine_v3",
                "PHASE6_COMMIT_SHA": commit_sha,
            },
        )
    return None


def write_command_output(path: Path, command: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        subprocess.run(
            list(command),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )


def collect_postgres_diagnostics(
    *,
    container: str,
    database: str,
    user: str,
    output_dir: Path,
) -> None:
    write_command_output(output_dir / "docker-logs.txt", ["docker", "logs", container])
    write_command_output(output_dir / "docker-inspect.json", ["docker", "inspect", container])
    queries = (
        "SELECT version();",
        "SELECT pid, usename, datname, state, wait_event_type, wait_event, query "
        "FROM pg_stat_activity ORDER BY pid;",
        "SELECT locktype, database, relation, page, tuple, virtualxid, transactionid, "
        "classid, objid, objsubid, virtualtransaction, pid, mode, granted, fastpath "
        "FROM pg_locks ORDER BY pid, locktype, mode;",
    )
    for index, query in enumerate(queries, start=1):
        write_command_output(
            output_dir / f"postgres-{index}.txt",
            ["docker", "exec", container, "psql", "-X", "-U", user, "-d", database, "-c", query],
        )


def run_canonical_job(
    *,
    job: str,
    selected_steps: list[str] | None,
    workspace: Path,
    run_dir: Path,
    network: str,
    runner_image: str,
    commit_sha: str,
    log: Logger,
    keep_on_failure: bool,
    preserved: list[str],
) -> dict[str, object]:
    token = f"{os.getpid()}-{job.replace('_', '-')}"
    runner = f"re-local-{token}-runner"
    postgres = f"re-local-{token}-pg"
    job_log_dir = run_dir / "steps" / job
    env: dict[str, str] = {}
    database: str | None = None
    user: str | None = None

    pg_config = postgres_job_config(job, commit_sha)
    if pg_config is not None:
        database, user, password, pg_env = pg_config
        start_postgres(
            name=postgres,
            network=network,
            database=database,
            user=user,
            password=password,
            log=log,
        )
        env.update(pg_env)
        env.update({"PGHOST": postgres, "PGPORT": "5432"})

    start_runner(
        name=runner,
        network=network,
        workspace=workspace,
        job_log_dir=job_log_dir,
        runner_image=runner_image,
        env=env,
        log=log,
    )

    command = [
        "docker",
        "exec",
        runner,
        "python",
        "scripts/ci/ci_jobs.py",
        job,
        "--log-dir",
        "/ci-logs",
        "--summary-output",
        "/ci-logs/job-summary.json",
    ]
    for step in selected_steps or []:
        command.extend(["--step", step])

    started = time.monotonic()
    returncode = log.run(command)
    elapsed = round(time.monotonic() - started, 3)
    status = "PASS" if returncode == 0 else "FAIL"

    summary_path = job_log_dir / "job-summary.json"
    step_results: list[dict[str, object]] = []
    if summary_path.exists():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        step_results = list(payload.get("steps", []))

    if returncode != 0 and database and user:
        collect_postgres_diagnostics(
            container=postgres,
            database=database,
            user=user,
            output_dir=run_dir / "diagnostics" / job,
        )

    if returncode != 0 and keep_on_failure:
        preserved.extend([runner, postgres] if pg_config else [runner])
        log.write(f"Preserved failed job containers: {', '.join(preserved)}")
    else:
        remove_container(runner)
        if pg_config is not None:
            remove_container(postgres)

    return {
        "job": job,
        "status": status,
        "returncode": returncode,
        "seconds": elapsed,
        "steps": step_results,
    }


def inspect_value(command: Sequence[str]) -> str:
    try:
        return capture(command)
    except subprocess.CalledProcessError as exc:
        return f"ERROR({exc.returncode})"


def build_environment_manifest(
    *,
    branch: str,
    commit_sha: str,
    runner_image: str,
    image_fingerprint_value: str,
) -> dict[str, object]:
    return {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "branch": branch,
        "commit_sha": commit_sha,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "docker": {
            "server": inspect_value(["docker", "version", "--format", "{{.Server.Version}}"]),
            "runner_image": runner_image,
            "runner_image_id": inspect_value(
                ["docker", "image", "inspect", runner_image, "--format", "{{.Id}}"]
            ),
            "runner_fingerprint": image_fingerprint_value,
            "postgres_image": POSTGRES_IMAGE,
            "postgres_image_id": inspect_value(
                ["docker", "image", "inspect", POSTGRES_IMAGE, "--format", "{{.Id}}"]
            ),
            "postgres_repo_digests": inspect_value(
                [
                    "docker",
                    "image",
                    "inspect",
                    POSTGRES_IMAGE,
                    "--format",
                    "{{json .RepoDigests}}",
                ]
            ),
        },
        "runtime": {
            "runner_python": inspect_value(["docker", "run", "--rm", runner_image, "python", "--version"]),
            "uv": inspect_value(["docker", "run", "--rm", runner_image, "uv", "--version"]),
            "postgres": inspect_value(
                ["docker", "run", "--rm", POSTGRES_IMAGE, "postgres", "--version"]
            ),
        },
    }


def previous_failed_jobs(root: Path) -> list[str]:
    latest = root / ".local-ci/latest.json"
    if not latest.exists():
        raise LocalCIError("No previous local CI run exists for --rerun-failed.")
    pointer = json.loads(latest.read_text(encoding="utf-8"))
    summary_path = Path(pointer["summary"])
    if not summary_path.exists():
        raise LocalCIError(f"Previous summary does not exist: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    failed = [item["job"] for item in summary.get("jobs", []) if item.get("status") != "PASS"]
    if not failed:
        raise LocalCIError("The previous local CI run has no failed jobs.")
    return failed


def copy_phase6_artifacts(workspace: Path, run_dir: Path) -> None:
    source = workspace / ".phase6"
    if not source.exists():
        return
    target = run_dir / "phase6"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)


def fix_ownership(root: Path, paths: Sequence[Path]) -> None:
    if os.name == "nt" or not hasattr(os, "getuid"):
        return
    uid = os.getuid()
    gid = os.getgid()
    existing = [path for path in paths if path.exists()]
    if not existing:
        return
    command = ["docker", "run", "--rm"]
    for index, path in enumerate(existing):
        command.extend(["-v", f"{path}:/target-{index}"])
    command.extend(["alpine:3.22", "sh", "-lc"])
    targets = " ".join(f"/target-{index}" for index in range(len(existing)))
    command.append(f"chown -R {uid}:{gid} {targets}")
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--job", action="append", help="Run only this canonical CI job; repeatable.")
    parser.add_argument("--step", action="append", help="Debug one or more steps; requires one --job.")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--keep-on-failure", action="store_true")
    parser.add_argument("--rebuild-image", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Do not docker pull fresh images.")
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Debug only. A run without sync is not release evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_program("git")
    root = find_repo_root()
    script_before = file_sha256(Path(__file__).resolve())
    run_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    run_dir = root / ".local-ci" / run_id
    log = Logger(run_dir / "run.log")
    workspace: Path | None = None
    network = f"re-local-ci-{os.getpid()}"
    preserved: list[str] = []
    commit_sha = "UNKNOWN"
    runner_image = "UNKNOWN"
    fingerprint = "UNKNOWN"
    job_results: list[dict[str, object]] = []
    interrupted = False

    try:
        if args.skip_sync:
            log.write("WARNING: --skip-sync disables remote-branch evidence semantics.")
            commit_sha = capture(["git", "rev-parse", "HEAD"], root)
        else:
            commit_sha = sync_branch(root, args.branch, log)
            maybe_reexec_after_sync(script_before, root, log)

        ensure_docker(log)
        runner_image, fingerprint = prepare_images(
            root,
            log,
            rebuild=args.rebuild_image,
            offline=args.offline,
        )

        canonical_jobs = list_jobs(root)
        if args.rerun_failed and args.job:
            raise LocalCIError("Use either --rerun-failed or --job, not both.")
        if args.rerun_failed:
            selected_jobs = previous_failed_jobs(root)
        elif args.job:
            unknown_jobs = sorted(set(args.job) - set(canonical_jobs))
            if unknown_jobs:
                raise LocalCIError(f"Unknown CI job(s): {', '.join(unknown_jobs)}")
            selected_jobs = args.job
        else:
            selected_jobs = canonical_jobs

        if args.step and len(selected_jobs) != 1:
            raise LocalCIError("--step requires exactly one selected --job.")
        selected_steps = None
        if args.step:
            selected_steps = resolve_selected_steps(root, selected_jobs[0], args.step)

        environment = build_environment_manifest(
            branch=args.branch,
            commit_sha=commit_sha,
            runner_image=runner_image,
            image_fingerprint_value=fingerprint,
        )
        write_json(run_dir / "environment.json", environment)

        log.write()
        log.write("=== REQUEST ENGINE LOCAL CI ===")
        log.write(f"Branch:       {args.branch}")
        log.write(f"Commit:       {commit_sha}")
        log.write(f"Host:         {environment['host']['platform']}")
        log.write(f"Docker:       {environment['docker']['server']}")
        log.write(f"Runner image: {runner_image}")
        log.write(f"PostgreSQL:   {environment['runtime']['postgres']}")
        log.write(f"Jobs:         {', '.join(selected_jobs)}")

        workspace = create_isolated_worktree(root, run_id, log)
        remove_network(network)
        if log.run(["docker", "network", "create", network]) != 0:
            raise LocalCIError("Could not create isolated Docker network.")

        for job in selected_jobs:
            log.write()
            log.write(f"=== JOB: {job} ===")
            job_results.append(
                run_canonical_job(
                    job=job,
                    selected_steps=selected_steps if job == selected_jobs[0] else None,
                    workspace=workspace,
                    run_dir=run_dir,
                    network=network,
                    runner_image=runner_image,
                    commit_sha=commit_sha,
                    log=log,
                    keep_on_failure=args.keep_on_failure,
                    preserved=preserved,
                )
            )

        copy_phase6_artifacts(workspace, run_dir)
        dirty = capture(["git", "status", "--porcelain", "--untracked-files=no"], workspace)
        workspace_clean = not dirty
        if dirty:
            log.write("Isolated CI worktree ended dirty:")
            log.write(dirty)

        failed = [item for item in job_results if item["status"] != "PASS"]
        if not workspace_clean:
            failed.append({"job": "worktree-integrity", "status": "FAIL"})

        summary = {
            "branch": args.branch,
            "commit_sha": commit_sha,
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "runner_image": runner_image,
            "runner_fingerprint": fingerprint,
            "jobs": job_results,
            "workspace_clean": workspace_clean,
            "preserved_containers": preserved,
            "status": "PASS" if not failed else "FAIL",
        }
        write_json(run_dir / "summary.json", summary)
        write_json(
            root / ".local-ci/latest.json",
            {
                "run_dir": str(run_dir),
                "summary": str(run_dir / "summary.json"),
                "log": str(run_dir / "run.log"),
            },
        )

        log.write()
        log.write("=== LOCAL CI SUMMARY ===")
        log.write(f"PASS: {sum(item['status'] == 'PASS' for item in job_results)}")
        log.write(f"FAIL: {sum(item['status'] != 'PASS' for item in job_results)}")
        log.write(f"Worktree clean: {workspace_clean}")
        log.write(f"Full log: {run_dir / 'run.log'}")
        log.write(f"Summary:  {run_dir / 'summary.json'}")
        log.write(f"Environment: {run_dir / 'environment.json'}")
        if preserved:
            log.write(f"Preserved containers: {', '.join(preserved)}")
            log.write(f"Preserved worktree: {workspace}")
        return 1 if failed else 0
    except KeyboardInterrupt:
        interrupted = True
        log.write()
        log.write("LOCAL CI INTERRUPTED BY USER")
        return 130
    except LocalCIError as exc:
        log.write()
        log.write(f"LOCAL CI ORCHESTRATION ERROR: {exc}")
        return 2
    finally:
        preserve_workspace = bool(preserved) and args.keep_on_failure and not interrupted
        if not preserve_workspace:
            for name in preserved:
                remove_container(name)
            remove_network(network)
            if workspace is not None:
                fix_ownership(root, [workspace, run_dir])
                remove_worktree(root, workspace)
        else:
            log.write("Docker network and isolated worktree preserved for failure debugging.")
        fix_ownership(root, [run_dir])
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
