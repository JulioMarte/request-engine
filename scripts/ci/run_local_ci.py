#!/usr/bin/env python3
"""Run the repository GitHub Actions checks locally.

The runner syncs the Phase 6 branch first. It then executes the same CI commands inside
Linux containers and uses fresh PostgreSQL 18 containers for every PostgreSQL job.

Host requirements:
- Git
- Docker Desktop or Docker Engine
- Python 3.10+

Run:
    python scripts/ci/run_local_ci.py

Complete output is stored under .local-ci/<timestamp>/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Iterable, Mapping, Sequence

DEFAULT_BRANCH = "phase-6-v3-freeze-release-proof"
CI_IMAGE = "request-engine-local-ci:py313-pg18"
CACHE_VOLUME = "request-engine-local-ci-uv-cache"


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

    def run(self, command: Sequence[str], *, cwd: Path | None = None) -> int:
        self.write(f"$ {' '.join(command)}")
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd else None,
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


def capture(command: Sequence[str], cwd: Path) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def find_repo_root() -> Path:
    try:
        root = capture(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise LocalCIError("Run this script from inside the Request Engine repository.") from exc
    return Path(root).resolve()


def ensure_clean_worktree(root: Path) -> None:
    status = capture(["git", "status", "--porcelain", "--untracked-files=all"], root)
    if not status:
        return
    raise LocalCIError(
        "Git worktree is not clean. Commit, stash, or remove local changes first.\n"
        "The runner will never discard local work automatically.\n\n"
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
    if branch in branches:
        switch = ["git", "switch", branch]
    else:
        switch = ["git", "switch", "--track", "-c", branch, f"origin/{branch}"]
    if log.run(switch, cwd=root) != 0:
        raise LocalCIError(f"Could not switch to {branch}")

    clear_console()
    if log.run(["git", "pull", "--ff-only", "origin", branch], cwd=root) != 0:
        raise LocalCIError("Local branch diverged from origin. Resolve it before local CI.")

    head = capture(["git", "rev-parse", "HEAD"], root)
    remote = capture(["git", "rev-parse", f"origin/{branch}"], root)
    if head != remote:
        raise LocalCIError(
            f"HEAD {head} does not exactly match origin/{branch} {remote}. "
            "Reconcile or push local commits before using this run as evidence."
        )

    ensure_clean_worktree(root)
    log.write(f"Synced commit: {head}")
    return head


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


def build_runner_image(root: Path, log: Logger, force: bool) -> None:
    exists = subprocess.run(
        ["docker", "image", "inspect", CI_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if exists and not force:
        log.write(f"Using cached runner image: {CI_IMAGE}")
        return

    command = [
        "docker",
        "build",
        "--pull",
        "-f",
        "scripts/ci/Dockerfile.local-ci",
        "-t",
        CI_IMAGE,
        ".",
    ]
    if log.run(command, cwd=root) != 0:
        raise LocalCIError("Failed to build the local CI runner image.")


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
        "postgres:18",
    ]
    if log.run(command) != 0:
        raise LocalCIError(f"Could not start PostgreSQL container {name}")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", user, "-d", database],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            log.write(f"PostgreSQL ready: {name} ({database}, user={user})")
            return
        time.sleep(1)

    log.run(["docker", "logs", name])
    raise LocalCIError(f"PostgreSQL did not become healthy: {name}")


def start_runner(
    *,
    name: str,
    network: str,
    root: Path,
    env: Mapping[str, str],
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
        "-v",
        f"{root}:/workspace",
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
    command.extend([CI_IMAGE, "sleep", "infinity"])
    if log.run(command, cwd=root) != 0:
        raise LocalCIError(f"Could not start runner container {name}")


def exec_runner(
    runner: str,
    shell_command: str,
    log: Logger,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> int:
    command = ["docker", "exec"]
    for key, value in (extra_env or {}).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([runner, "bash", "-lc", f"set -o pipefail; {shell_command}"])
    return log.run(command)


def run_step(
    *,
    job: str,
    name: str,
    runner: str,
    command: str,
    log: Logger,
    results: list[dict[str, object]],
    extra_env: Mapping[str, str] | None = None,
) -> bool:
    log.write()
    log.write(f"--- {job} :: {name} ---")
    started = time.monotonic()
    returncode = exec_runner(runner, command, log, extra_env=extra_env)
    seconds = round(time.monotonic() - started, 3)
    status = "PASS" if returncode == 0 else "FAIL"
    results.append(
        {
            "job": job,
            "step": name,
            "command": command,
            "returncode": returncode,
            "seconds": seconds,
            "status": status,
        }
    )
    log.write(f"[{status}] {job} :: {name} ({seconds}s)")
    return returncode == 0


def skip_step(
    *,
    job: str,
    name: str,
    command: str,
    reason: str,
    log: Logger,
    results: list[dict[str, object]],
) -> None:
    results.append(
        {
            "job": job,
            "step": name,
            "command": command,
            "returncode": None,
            "seconds": 0,
            "status": "SKIP",
            "reason": reason,
        }
    )
    log.write(f"[SKIP] {job} :: {name} ({reason})")


def run_python_quality(
    network: str,
    root: Path,
    log: Logger,
    results: list[dict[str, object]],
) -> None:
    job = "python-quality"
    runner = f"re-local-{os.getpid()}-quality"
    start_runner(name=runner, network=network, root=root, env={}, log=log)
    try:
        commands = [
            ("Resolve development environment", "uv sync --all-groups"),
            ("Lockfile consistency", "uv lock --check"),
            ("Ruff lint", "uv run ruff check ."),
            ("Ruff format check", "uv run ruff format --diff ."),
            ("Pyright", "uv run pyright"),
            ("High-confidence secret scan", "uv run python scripts/release/scan_v3_secrets.py"),
            ("Python security static analysis", "uv run python scripts/release/scan_v3_python_security.py"),
            ("Dependency vulnerability audit", "uv run --with pip-audit==2.10.1 pip-audit --local"),
            ("Architecture tests", "uv run pytest tests/architecture -q"),
            ("Module unit tests", "uv run pytest tests/modules -q"),
        ]
        environment_ready = True
        for name, command in commands:
            if command.startswith("uv run") and not environment_ready:
                skip_step(
                    job=job,
                    name=name,
                    command=command,
                    reason="uv sync failed",
                    log=log,
                    results=results,
                )
                continue
            passed = run_step(
                job=job,
                name=name,
                runner=runner,
                command=command,
                log=log,
                results=results,
            )
            if name == "Resolve development environment" and not passed:
                environment_ready = False
    finally:
        remove_container(runner)


def run_v2_history(
    network: str,
    root: Path,
    log: Logger,
    results: list[dict[str, object]],
) -> None:
    job = "postgres-v2-history"
    database = f"re-local-{os.getpid()}-pg-v2"
    runner = f"re-local-{os.getpid()}-v2"
    start_postgres(
        name=database,
        network=network,
        database="request_engine",
        user="request_engine",
        password="request_engine",
        log=log,
    )
    env = {
        "PGHOST": database,
        "PGPORT": "5432",
        "PGUSER": "request_engine",
        "PGPASSWORD": "request_engine",
        "PGDATABASE": "request_engine",
    }
    start_runner(name=runner, network=network, root=root, env=env, log=log)
    try:
        run_step(
            job=job,
            name="Apply historical V2 design chain",
            runner=runner,
            command="bash scripts/db/apply_design_chain.sh",
            log=log,
            results=results,
        )
    finally:
        remove_container(runner)
        remove_container(database)


def run_v3_bootstrap(
    network: str,
    root: Path,
    log: Logger,
    results: list[dict[str, object]],
) -> None:
    job = "postgres-v3-bootstrap-proof"
    database = f"re-local-{os.getpid()}-pg-bootstrap"
    runner = f"re-local-{os.getpid()}-bootstrap"
    start_postgres(
        name=database,
        network=network,
        database="request_engine_v3",
        user="postgres",
        password="postgres",
        log=log,
    )
    env = {
        "PGHOST": database,
        "PGPORT": "5432",
        "PGUSER": "postgres",
        "PGPASSWORD": "postgres",
        "PGMAINTENANCE_DB": "postgres",
        "V3_PROOF_DATABASE_PREFIX": "request_engine_v3_phase6",
    }
    start_runner(name=runner, network=network, root=root, env=env, log=log)
    try:
        run_step(
            job=job,
            name="Prove repeated clean V3 candidate bootstrap",
            runner=runner,
            command="bash scripts/db/prove_v3_candidate_bootstrap.sh",
            log=log,
            results=results,
        )
    finally:
        remove_container(runner)
        remove_container(database)


def v3_dependent_steps() -> list[tuple[str, str]]:
    return [
        (
            "Generate V3 schema fingerprint",
            "mkdir -p .phase6 && uv run python scripts/db/v3_schema_fingerprint.py "
            "--json-output .phase6/v3-schema.json --sha-output .phase6/v3-schema.sha256 "
            "&& cat .phase6/v3-schema.sha256",
        ),
        (
            "Audit V3 PostgreSQL catalog",
            "uv run python scripts/db/audit_v3_catalog.py "
            "--json-output .phase6/v3-catalog-audit.json",
        ),
        (
            "Prove measured worker query plans",
            "uv run python scripts/release/prove_v3_worker_query_plans.py "
            "--output .phase6/v3-worker-query-plans.json",
        ),
        (
            "Generate and prove 0001 initial candidate equivalence",
            "uv run python scripts/db/build_v3_initial_candidate.py "
            "--output .phase6/0001_initial.candidate.sql "
            "&& uv run bash scripts/db/prove_v3_initial_equivalence.sh "
            "| tee .phase6/v3-initial-equivalence.txt",
        ),
        (
            "V3 PostgreSQL invariant, race, and vertical tests",
            "uv run pytest tests/db tests/integration/v3_first_vertical "
            "tests/integration/v3_booking_core tests/integration/v3_booking_commitments "
            "tests/integration/v3_slot_offer_recovery tests/integration/v3_reservation_lifecycle "
            "tests/integration/v3_worker_runtime -q -m postgres",
        ),
        (
            "Kill critical mutations",
            "uv run python scripts/release/run_v3_mutation_probes.py",
        ),
    ]


def run_v3_candidate(
    network: str,
    root: Path,
    commit_sha: str,
    log: Logger,
    results: list[dict[str, object]],
) -> None:
    job = "postgres-v3-candidate"
    database = f"re-local-{os.getpid()}-pg-v3"
    runner = f"re-local-{os.getpid()}-v3"
    start_postgres(
        name=database,
        network=network,
        database="request_engine_v3",
        user="postgres",
        password="postgres",
        log=log,
    )
    env = {
        "PGHOST": database,
        "PGPORT": "5432",
        "PGDATABASE": "request_engine_v3",
        "PGUSER": "postgres",
        "PGPASSWORD": "postgres",
    }
    start_runner(name=runner, network=network, root=root, env=env, log=log)
    try:
        setup_ok = run_step(
            job=job,
            name="Apply clean V3 candidate as bootstrap principal",
            runner=runner,
            command="bash scripts/db/apply_v3_candidate.sh",
            log=log,
            results=results,
        )
        environment_ok = False
        if setup_ok:
            environment_ok = run_step(
                job=job,
                name="Resolve test environment",
                runner=runner,
                command="uv sync --all-groups",
                log=log,
                results=results,
            )

        if setup_ok and environment_ok:
            for name, command in v3_dependent_steps():
                run_step(
                    job=job,
                    name=name,
                    runner=runner,
                    command=command,
                    log=log,
                    results=results,
                )
        else:
            reason = "candidate bootstrap failed" if not setup_ok else "uv sync failed"
            for name, command in v3_dependent_steps():
                skip_step(
                    job=job,
                    name=name,
                    command=command,
                    reason=reason,
                    log=log,
                    results=results,
                )

        if environment_ok:
            run_step(
                job=job,
                name="Generate executable release evidence manifest",
                runner=runner,
                command=(
                    "uv run python scripts/release/build_v3_evidence_manifest.py "
                    "--output .phase6/v3-evidence-manifest.json"
                ),
                log=log,
                results=results,
                extra_env={"PHASE6_COMMIT_SHA": commit_sha},
            )
    finally:
        remove_container(runner)
        remove_container(database)


def fix_phase6_ownership(root: Path) -> None:
    if os.name == "nt" or not hasattr(os, "getuid") or not (root / ".phase6").exists():
        return
    uid = os.getuid()
    gid = os.getgid()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root}:/workspace",
            "alpine:3.22",
            "chown",
            "-R",
            f"{uid}:{gid}",
            "/workspace/.phase6",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def write_summary(
    path: Path,
    branch: str,
    commit_sha: str,
    results: Iterable[dict[str, object]],
) -> None:
    items = list(results)
    payload = {
        "branch": branch,
        "commit_sha": commit_sha,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": sum(item["status"] == "PASS" for item in items),
        "failed": sum(item["status"] == "FAIL" for item in items),
        "skipped": sum(item["status"] == "SKIP" for item in items),
        "steps": items,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--rebuild-image", action="store_true")
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
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / ".local-ci" / timestamp
    log = Logger(run_dir / "run.log")
    results: list[dict[str, object]] = []
    commit_sha = "UNKNOWN"
    network = f"re-local-ci-{os.getpid()}"

    try:
        if args.skip_sync:
            log.write("WARNING: --skip-sync disables remote-branch evidence semantics.")
            commit_sha = capture(["git", "rev-parse", "HEAD"], root)
        else:
            commit_sha = sync_branch(root, args.branch, log)

        ensure_docker(log)
        build_runner_image(root, log, args.rebuild_image)
        remove_network(network)
        if log.run(["docker", "network", "create", network]) != 0:
            raise LocalCIError("Could not create the isolated Docker network.")

        log.write()
        log.write("=== GitHub Actions parity run ===")
        log.write(f"Branch: {args.branch}")
        log.write(f"Commit: {commit_sha}")
        log.write("PostgreSQL server: postgres:18")
        log.write("Python runner: 3.13 Linux container")

        run_python_quality(network, root, log, results)
        run_v2_history(network, root, log, results)
        run_v3_bootstrap(network, root, log, results)
        run_v3_candidate(network, root, commit_sha, log, results)

        fix_phase6_ownership(root)
        write_summary(run_dir / "summary.json", args.branch, commit_sha, results)

        failed = [item for item in results if item["status"] == "FAIL"]
        skipped = [item for item in results if item["status"] == "SKIP"]
        log.write()
        log.write("=== LOCAL CI SUMMARY ===")
        log.write(f"PASS: {sum(item['status'] == 'PASS' for item in results)}")
        log.write(f"FAIL: {len(failed)}")
        log.write(f"SKIP: {len(skipped)}")
        log.write(f"Full log: {run_dir / 'run.log'}")
        log.write(f"Summary:  {run_dir / 'summary.json'}")
        if failed:
            log.write("Failed steps:")
            for item in failed:
                log.write(f"  - {item['job']} :: {item['step']}")
            return 1
        if skipped:
            log.write("Dependent steps were skipped. Treat this run as failed.")
            return 1
        log.write("All executable CI checks passed locally.")
        return 0
    except LocalCIError as exc:
        log.write()
        log.write(f"LOCAL CI ORCHESTRATION ERROR: {exc}")
        return 2
    finally:
        for suffix in (
            "quality",
            "v2",
            "bootstrap",
            "v3",
            "pg-v2",
            "pg-bootstrap",
            "pg-v3",
        ):
            remove_container(f"re-local-{os.getpid()}-{suffix}")
        remove_network(network)
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
