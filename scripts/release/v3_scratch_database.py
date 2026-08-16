from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
COMMAND_TIMEOUT_SECONDS = 60
BOOTSTRAP_TIMEOUT_SECONDS = 1200
DATABASE_PREFIX = re.compile(r"^[a-z_][a-z0-9_]{0,41}$")


class ScratchDatabaseError(RuntimeError):
    """A scratch database could not be created or bootstrapped."""


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: int = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScratchDatabaseError(
            f"{command[0]} timed out after {timeout_seconds} seconds"
        ) from exc


def _failure_tail(result: subprocess.CompletedProcess[str], *, limit: int = 80) -> str:
    output = (result.stdout + result.stderr).strip().splitlines()
    return "\n".join(output[-limit:])


def _drop_and_verify(
    database: str,
    *,
    maintenance_database: str,
    env: dict[str, str],
    if_exists: bool = False,
) -> None:
    drop_command = ["dropdb", f"--maintenance-db={maintenance_database}", "--force"]
    if if_exists:
        drop_command.append("--if-exists")
    drop_command.append(database)
    drop = _run(
        drop_command,
        env=env,
    )
    if drop.returncode != 0:
        raise ScratchDatabaseError(
            f"could not drop scratch database {database}:\n{_failure_tail(drop)}"
        )

    verify = _run(
        [
            "psql",
            f"--dbname={maintenance_database}",
            "--no-align",
            "--tuples-only",
            "--set=ON_ERROR_STOP=1",
            "--command",
            f"SELECT count(*) FROM pg_database WHERE datname = '{database}'",
        ],
        env=env,
    )
    if verify.returncode != 0:
        raise ScratchDatabaseError(
            f"could not verify removal of scratch database {database}:\n{_failure_tail(verify)}"
        )
    if verify.stdout.strip() != "0":
        raise ScratchDatabaseError(f"scratch database {database} still exists after dropdb")


@contextmanager
def fresh_v3_database(prefix: str) -> Generator[dict[str, str]]:
    """Yield an environment bound to a freshly bootstrapped V3 scratch database."""

    if DATABASE_PREFIX.fullmatch(prefix) is None:
        raise ScratchDatabaseError(
            "scratch database prefix must be a lowercase PostgreSQL identifier "
            "of at most 42 characters"
        )
    database = f"{prefix}_{uuid4().hex[:20]}"
    base_env = os.environ.copy()
    base_env.setdefault("PGCONNECT_TIMEOUT", "5")
    maintenance_database = base_env.get("PGMAINTENANCE_DB", "postgres")
    created = False
    body_error: BaseException | None = None

    create = _run(
        ["createdb", f"--maintenance-db={maintenance_database}", database],
        env=base_env,
    )
    if create.returncode != 0:
        create_error = ScratchDatabaseError(
            f"could not create scratch database {database}:\n{_failure_tail(create)}"
        )
        try:
            # createdb can have an ambiguous client-side failure after the server
            # committed creation. The generated name is safe to clean defensively.
            _drop_and_verify(
                database,
                maintenance_database=maintenance_database,
                env=base_env,
                if_exists=True,
            )
        except ScratchDatabaseError as cleanup_error:
            create_error.add_note(f"ambiguous create cleanup also failed: {cleanup_error}")
        raise create_error
    created = True

    scratch_env = {**base_env, "PGDATABASE": database}
    try:
        bootstrap = _run(
            ["bash", "scripts/db/apply_v3_candidate.sh"],
            env=scratch_env,
            timeout_seconds=BOOTSTRAP_TIMEOUT_SECONDS,
        )
        if bootstrap.returncode != 0:
            raise ScratchDatabaseError(
                f"could not bootstrap scratch database {database}:\n{_failure_tail(bootstrap)}"
            )
        yield scratch_env
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        if created:
            try:
                _drop_and_verify(
                    database,
                    maintenance_database=maintenance_database,
                    env=base_env,
                )
            except ScratchDatabaseError as cleanup_error:
                if body_error is None:
                    raise
                body_error.add_note(f"scratch database cleanup also failed: {cleanup_error}")
