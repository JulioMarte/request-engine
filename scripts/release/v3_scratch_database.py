from __future__ import annotations

import os
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


class ScratchDatabaseError(RuntimeError):
    """A scratch database could not be created or bootstrapped."""


def _run(
    command: list[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _failure_tail(result: subprocess.CompletedProcess[str], *, limit: int = 80) -> str:
    output = (result.stdout + result.stderr).strip().splitlines()
    return "\n".join(output[-limit:])


@contextmanager
def fresh_v3_database(prefix: str) -> Generator[dict[str, str]]:
    """Yield an environment bound to a freshly bootstrapped V3 scratch database."""

    database = f"{prefix}_{uuid4().hex[:20]}"
    base_env = os.environ.copy()
    maintenance_database = base_env.get("PGMAINTENANCE_DB", "postgres")
    created = False

    create = _run(
        ["createdb", f"--maintenance-db={maintenance_database}", database],
        env=base_env,
    )
    if create.returncode != 0:
        raise ScratchDatabaseError(
            f"could not create scratch database {database}:\n{_failure_tail(create)}"
        )
    created = True

    scratch_env = {**base_env, "PGDATABASE": database}
    try:
        bootstrap = _run(
            ["bash", "scripts/db/apply_v3_candidate.sh"],
            env=scratch_env,
        )
        if bootstrap.returncode != 0:
            raise ScratchDatabaseError(
                f"could not bootstrap scratch database {database}:\n{_failure_tail(bootstrap)}"
            )
        yield scratch_env
    finally:
        if created:
            _run(
                [
                    "dropdb",
                    f"--maintenance-db={maintenance_database}",
                    "--force",
                    database,
                ],
                env=base_env,
            )
